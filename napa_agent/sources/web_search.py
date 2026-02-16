from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def search_web(query: str, endpoint_url: str | None) -> tuple[list[dict[str, str]], str]:
    """Simple HTTP search integration with no API-key assumptions.

    Expected JSON response shape is either:
    - {"results": [{"title": ..., "url": ..., "snippet": ...}]}
    - [{"title": ..., "url": ..., "snippet": ...}]
    """
    if not endpoint_url:
        return [], "web search not configured"

    target = f"{endpoint_url}?{urlencode({'q': query})}"
    request = Request(target, headers={"User-Agent": "napa-agent/0.1"})

    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    except Exception:
        return [], "web search endpoint unavailable"

    raw_items = payload.get("results", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        return [], "web search endpoint returned unsupported format"

    items: list[dict[str, str]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        if not title or not url:
            continue
        items.append(
            {
                "title": title,
                "url": url,
                "summary": str(item.get("snippet", "")).strip() or title,
            }
        )

    return items[:20], f"processed {len(items[:20])} web search results"
