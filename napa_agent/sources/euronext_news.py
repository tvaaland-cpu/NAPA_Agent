from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from napa_agent.util.retry import retry_call


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text = ""

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag != "a":
            return
        data = dict(attrs)
        self._href = data.get("href", "")
        self._text = ""

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        self._text += data

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag == "a" and self._href:
            self.links.append((self._text.strip(), self._href))
            self._href = ""
            self._text = ""


@retry_call(attempts=3, base_delay=1, max_delay=10)
def fetch_company_news(url: str, timeout: int = 30) -> list[dict[str, str]]:
    request = Request(url, headers={"User-Agent": "napa-agent/0.1"})
    with urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="ignore")

    parser = _LinkParser()
    parser.feed(html)

    items: list[dict[str, str]] = []
    for text, href in parser.links:
        if not href or not text:
            continue
        if "news" not in text.lower() and "release" not in text.lower():
            continue
        full_url = urljoin(url, href)
        item_id = full_url.rstrip("/").split("/")[-1] or text
        items.append({"id": item_id, "title": text, "url": full_url})

    dedup = {(i["id"], i["url"]): i for i in items}
    return list(dedup.values())[:20]
