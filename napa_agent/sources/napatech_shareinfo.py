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

    for table in tables:
        header_line = " ".join(table[0]).lower() if table else ""
        if "shareholder" in header_line and ("share" in header_line or "%" in header_line):
            return table

    best: list[list[str]] = []
    best_rows = 0
    for table in tables:
        rows_with_numbers = 0
        for row in table:
            if any(_parse_int(cell) is not None for cell in row[1:]):
                rows_with_numbers += 1
        if rows_with_numbers > best_rows:
            best_rows = rows_with_numbers
            best = table
    return best


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
        holder_name = _value_at(row, index_map.get("holder"))
        shares_raw = _value_at(row, index_map.get("shares"))
        pct_raw = _value_at(row, index_map.get("pct"))
        if not holder_name or not shares_raw or not pct_raw:
            continue

        shares = _parse_int(shares_raw)
        pct = _parse_pct(pct_raw)
        if shares is None or pct is None:
            continue

        rank_raw = _value_at(row, index_map.get("rank"))
        rank = _parse_int(rank_raw or "") or (len(parsed) + 1)

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

    return parsed


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
        "holder": locate("shareholder", "holder", "name"),
        "shares": locate("shares", "number of shares"),
        "pct": locate("%", "ownership", "capital"),
        "holder_type": locate("type", "investor type"),
        "country": locate("country"),
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
    return "shareholder" in joined and ("share" in joined or "%" in joined)


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
