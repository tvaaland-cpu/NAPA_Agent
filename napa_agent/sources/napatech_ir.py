from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from napa_agent.util.retry import retry_call

IR_PATHS = ["press-releases/", "reports-presentations/"]


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text = ""

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag != "a":
            return
        self._href = dict(attrs).get("href", "")
        self._text = ""

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        self._text += data

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag == "a" and self._href:
            self.links.append((self._text.strip(), self._href))
            self._href = ""
            self._text = ""


@retry_call(attempts=3, base_delay=1, max_delay=10)
def fetch_ir_updates(base_url: str, timeout: int = 30) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for path in IR_PATHS:
        page_url = urljoin(base_url, path)
        request = Request(page_url, headers={"User-Agent": "napa-agent/0.1"})
        with urlopen(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="ignore")

        parser = _LinkParser()
        parser.feed(html)

        for title, href in parser.links:
            if not href or not title:
                continue
            if len(title) < 8:
                continue
            if not any(k in title.lower() for k in ["report", "presentation", "release", "interim", "announcement"]):
                continue
            full_url = urljoin(page_url, href)
            item_id = full_url.rstrip("/").split("/")[-1] or title
            items.append({"id": item_id, "title": title, "url": full_url, "section": path.rstrip("/")})

    dedup = {(i["id"], i["url"]): i for i in items}
    return list(dedup.values())[:40]
