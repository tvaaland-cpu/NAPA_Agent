from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from napa_agent.util.retry import retry_call

logger = logging.getLogger(__name__)


class _Top20TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.current_cell = ""
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []
        self._cell_tag = ""

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag == "table":
            self.in_table = True
        if self.in_table and tag == "tr":
            self.in_row = True
            self.current_row = []
        if self.in_row and tag in {"td", "th"}:
            self._cell_tag = tag
            self.current_cell = ""

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if self.in_row and tag in {"td", "th"} and self._cell_tag == tag:
            self.current_row.append(self.current_cell.strip())
            self._cell_tag = ""
        if self.in_row and tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
            self.in_row = False
        if tag == "table" and self.in_table:
            self.in_table = False

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._cell_tag:
            self.current_cell += data


@retry_call(attempts=3, base_delay=1, max_delay=10)
def fetch_shareholders(url: str, timeout: int = 30) -> list[dict[str, int | str]]:
    request = Request(url, headers={"User-Agent": "napa-agent/0.1"})
    with urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="ignore")
    return parse_top20_html(html)


def parse_top20_html(html: str) -> list[dict[str, int | str]]:
    parser = _Top20TableParser()
    parser.feed(html)

    holders: list[dict[str, int | str]] = []
    for row in parser.rows:
        if len(row) < 2:
            continue
        if row[0].strip().lower() in {"shareholder", "name"}:
            continue
        shares = _parse_int(row[1])
        if shares is None:
            continue
        holders.append({"holder": row[0].strip(), "shares": shares})

    if not holders:
        logger.warning("Top 20 table was not found in HTML")
    return holders


def _parse_int(value: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", value)
    if not digits:
        return None
    return int(digits)
