from __future__ import annotations

from typing import Any

import requests
import trafilatura

ARTICLE_USER_AGENT = "Mozilla/5.0 compatible; WebCrawler/0.1"


def fetch_article_html(url: str, timeout: int = 10) -> dict[str, Any]:
    response = requests.get(
        url,
        headers={
            "User-Agent": ARTICLE_USER_AGENT,
        },
        timeout=timeout,
    )

    return {
        "request_url": url,
        "final_url": response.url,
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type"),
        "html": response.text,
    }


def extract_article_text(html: str, url: str) -> str | None:
    return trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
    )
