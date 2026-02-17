from napa_agent.sources import napatech_ir


class _MockResponse:
    def __init__(self, body: str) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_fetch_ir_updates_uses_only_base_url_and_builds_absolute_links(monkeypatch) -> None:
    called_urls: list[str] = []

    html = """
    <html>
      <body>
        <a href="/investor-relations/files/Annual-Report-2024.pdf">Annual Report 2024-03-01</a>
        <a href="presentation-q1-2025.pdf">Q1 Presentation 01/05/2025</a>
        <a href="/contact/">Contact</a>
      </body>
    </html>
    """

    def fake_urlopen(request, timeout=30):
        called_urls.append(request.full_url)
        return _MockResponse(html)

    monkeypatch.setattr(napatech_ir, "urlopen", fake_urlopen)

    base_url = "https://www.napatech.com/investor-relations/reports-and-presentations/"
    items = napatech_ir.fetch_ir_updates(base_url)

    assert called_urls == [base_url]
    assert len(items) == 2
    assert items[0]["url"] == "https://www.napatech.com/investor-relations/files/Annual-Report-2024.pdf"
    assert items[1]["url"] == "https://www.napatech.com/investor-relations/reports-and-presentations/presentation-q1-2025.pdf"
    assert items[0]["published_at"] is not None
    assert items[1]["published_at"] is not None
