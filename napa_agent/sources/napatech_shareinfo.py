from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from pydantic import BaseModel

from napa_agent.util.retry import retry_call

logger = logging.getLogger(__name__)


class ShareholderRow(BaseModel):
    rank: int
    holder_name: str
    shares: int
    pct: float
    holder_type: str | None = None
    country: str | None = None


class ShareholderSnapshot(BaseModel):
    updated_label: str | None = None
    fetched_at: datetime
    rows: list[ShareholderRow]
    source_url: str


class _TableCaptureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self.all_text: list[str] = []
        self._table_stack = 0
        self._in_row = False
        self._in_cell = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag == "table":
            self._table_stack += 1
            if self._table_stack == 1:
                self._current_table = []
        if self._table_stack and tag == "tr":
            self._in_row = True
            self._current_row = []
        if self._in_row and tag in {"th", "td"}:
            self._in_cell = True
            self._current_cell = []

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        stripped = data.strip()
        if stripped:
            self.all_text.append(stripped)
        if self._in_cell:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if self._in_cell and tag in {"th", "td"}:
            self._in_cell = False
            cell_value = " ".join("".join(self._current_cell).split())
            self._current_row.append(cell_value)
            self._current_cell = []
        if self._in_row and tag == "tr":
            self._in_row = False
            if any(cell for cell in self._current_row):
                self._current_table.append(self._current_row)
        if tag == "table" and self._table_stack:
            self._table_stack -= 1
            if self._table_stack == 0 and self._current_table:
                self.tables.append(self._current_table)
                self._current_table = []


def parse_shareholder_snapshot(
    html: str,
    *,
    source_url: str,
    fetched_at: datetime | None = None,
) -> ShareholderSnapshot:
    parser = _TableCaptureParser()
    parser.feed(html)

    updated_label = _extract_updated_label(" ".join(parser.all_text))
    rows = _parse_rows(_find_candidate_table(parser.tables))

    if not rows:
        logger.warning("Top 20 shareholder table was not found or had no rows")

    return ShareholderSnapshot(
        updated_label=updated_label,
        fetched_at=fetched_at or datetime.now(timezone.utc),
        rows=rows,
        source_url=source_url,
    )


@retry_call(attempts=3, base_delay=1, max_delay=10)
def fetch_shareholders(url: str, timeout: int = 30) -> ShareholderSnapshot:
    request = Request(url, headers={"User-Agent": "napa-agent/0.1"})
    with urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="ignore")
    return parse_shareholder_snapshot(html, source_url=url)


def _extract_updated_label(text: str) -> str | None:
    match = re.search(r"(Updated\s+[A-Za-z]+\s+\d{1,2}[\.,]?\s+\d{4})", text, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _find_candidate_table(tables: list[list[list[str]]]) -> list[list[str]]:
    if not tables:
        return []

    preferred: list[tuple[int, list[list[str]]]] = []
    fallback: list[tuple[int, list[list[str]]]] = []
    for table in tables:
        if not table:
            continue
        score = _top20_shape_score(table)
        if score >= 100:
            preferred.append((score, table))
        elif score > 0:
            fallback.append((score, table))

    if preferred:
        preferred.sort(key=lambda item: item[0], reverse=True)
        return preferred[0][1]

    if fallback:
        fallback.sort(key=lambda item: item[0], reverse=True)
        return fallback[0][1]

    # Last-resort fallback: only consider numeric-heavy tables with rank pattern.
    numeric_ranked: list[tuple[int, list[list[str]]]] = []
    for table in tables:
        if not table:
            continue
        if not _has_rank_pattern(table):
            continue
        rows_with_numbers = 0
        for row in table:
            if any(_parse_int(cell) is not None for cell in row):
                rows_with_numbers += 1
        if rows_with_numbers:
            numeric_ranked.append((rows_with_numbers, table))

    if numeric_ranked:
        numeric_ranked.sort(key=lambda item: item[0], reverse=True)
        return numeric_ranked[0][1]
    return []


def _parse_rows(table: list[list[str]]) -> list[ShareholderRow]:
    if not table:
        return []

    header = table[0]
    index_map = _build_index_map(header)
    data_rows = table[1:] if _is_header_like(header) else table

    parsed: list[ShareholderRow] = []
    for row in data_rows:
        if _is_header_like(row):
            continue
        
        # Skip summary rows (total rows, ranks > 20, empty ranks)
        rank_raw = _value_at(row, index_map.get("rank"))
        if rank_raw:
            rank = _parse_int(rank_raw or "")
            if rank is None or rank > 20:
                continue
        
        holder_name = _value_at(row, index_map.get("holder"))
        shares_raw = _value_at(row, index_map.get("shares"))
        pct_raw = _value_at(row, index_map.get("pct"))
        
        # Skip rows with missing critical fields
        if not holder_name or not shares_raw or not pct_raw:
            continue
        
        # Reject rows where holder_name is purely numeric (parsing error)
        if holder_name.isdigit():
            logger.debug(f"Skipping row with numeric-only holder_name: {holder_name}")
            continue
        
        # Skip total/summary rows by name patterns
        holder_lower = holder_name.lower()
        if any(keyword in holder_lower for keyword in ["total", "other shareholders", "grand total"]):
            continue

        shares = _parse_int(shares_raw)
        pct = _parse_pct(pct_raw)
        if shares is None or pct is None:
            continue

        # Assign rank: if present in table use it, else auto-assign based on position
        if rank_raw:
            rank = _parse_int(rank_raw) or (len(parsed) + 1)
        else:
            rank = len(parsed) + 1

        parsed.append(
            ShareholderRow(
                rank=rank,
                holder_name=holder_name,
                shares=shares,
                pct=pct,
                holder_type=_value_at(row, index_map.get("holder_type")),
                country=_value_at(row, index_map.get("country")),
            )
        )
        
        # Stop after collecting 20 rows
        if len(parsed) >= 20:
            break

    return parsed[:20]


def _build_index_map(header: list[str]) -> dict[str, int]:
    normalized = [h.lower() for h in header]

    def locate(*tokens: str) -> int | None:
        for idx, cell in enumerate(normalized):
            if any(token in cell for token in tokens):
                return idx
        return None

    index_map: dict[str, int] = {}
    mapping = {
        "rank": locate("rank", "#", "no."),
        "holder": locate("investor", "shareholder", "holder", "name"),
        "shares": locate("shares", "number of shares"),
        "pct": locate("%", "ownership", "capital"),
        "holder_type": locate("type", "investor type"),
        "country": locate("country", "citizenship"),
    }
    for key, value in mapping.items():
        if value is not None:
            index_map[key] = value

    if "holder" not in index_map:
        index_map["holder"] = 1
    if "shares" not in index_map:
        index_map["shares"] = 2
    if "pct" not in index_map:
        index_map["pct"] = 3
    return index_map


def _value_at(values: list[str], idx: int | None) -> str | None:
    if idx is None or idx >= len(values):
        return None
    value = values[idx].strip()
    return value or None


def _is_header_like(values: list[str]) -> bool:
    joined = " ".join(values).lower()
    has_name_hint = any(
        token in joined
        for token in (
            "shareholder",
            "shareholders",
            "largest shareholders",
            "largest investor",
            "largest investors",
            "investor",
            "holder",
            "name",
        )
    )
    has_value_hint = any(
        token in joined
        for token in (
            "share",
            "number of shares",
            "%",
            "ownership",
            "capital",
        )
    )
    return has_name_hint and has_value_hint


def _has_rank_pattern(table: list[list[str]]) -> bool:
    header = table[0]
    index_map = _build_index_map(header)
    data_rows = table[1:] if _is_header_like(header) else table
    rank_idx = index_map.get("rank")
    if rank_idx is None:
        return False

    ranks: set[int] = set()
    for row in data_rows:
        value = _value_at(row, rank_idx)
        if not value:
            continue
        rank = _parse_int(value)
        if rank is not None:
            ranks.add(rank)
    return set(range(1, 21)).issubset(ranks)


def _top20_shape_score(table: list[list[str]]) -> int:
    header = table[0]
    header_like = _is_header_like(header)
    index_map = _build_index_map(header)
    data_rows = table[1:] if header_like else table

    valid_rows = 0
    non_numeric_names = 0
    shares_numeric = 0
    pct_numeric = 0
    ranks: set[int] = set()

    for row in data_rows:
        holder_name = _value_at(row, index_map.get("holder"))
        shares_raw = _value_at(row, index_map.get("shares"))
        pct_raw = _value_at(row, index_map.get("pct"))
        rank_raw = _value_at(row, index_map.get("rank"))

        if not holder_name or not shares_raw or not pct_raw:
            continue

        shares = _parse_int(shares_raw)
        pct = _parse_pct(pct_raw)
        if shares is None or pct is None:
            continue

        valid_rows += 1
        shares_numeric += 1
        pct_numeric += 1
        if not holder_name.isdigit():
            non_numeric_names += 1

        if rank_raw:
            rank = _parse_int(rank_raw)
            if rank is not None:
                ranks.add(rank)

    if valid_rows == 0:
        return 0

    score = 0
    if header_like:
        score += 30
    if valid_rows >= 20:
        score += 30
    if non_numeric_names >= 20:
        score += 20
    if shares_numeric >= 20 and pct_numeric >= 20:
        score += 20
    if set(range(1, 21)).issubset(ranks):
        score += 100
    return score


def _parse_int(value: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", value)
    return int(digits) if digits else None


def _parse_pct(value: str) -> float | None:
    cleaned = value.replace("%", "").replace(" ", "")
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")

    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(match.group(0)) if match else None
