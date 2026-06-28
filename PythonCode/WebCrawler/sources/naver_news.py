from __future__ import annotations

import html
import os
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import requests

NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"
HTML_TAG_RE = re.compile(r"<[^>]+>")


class NaverNewsApiError(RuntimeError):
    pass


def clean_html(value: str | None) -> str:
    if not value:
        return ""

    text = HTML_TAG_RE.sub("", value)
    return html.unescape(text).strip()


def parse_pub_date(value: str | None) -> str | None:
    if not value:
        return None

    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return None


def get_naver_credentials(
    client_id: str | None = None,
    client_secret: str | None = None,
) -> tuple[str, str]:
    resolved_client_id = (
        client_id
        or os.getenv("NAVER_CLIENT_ID")
        or os.getenv("NAVER_API_CLIENT_ID")
    )
    resolved_client_secret = (
        client_secret
        or os.getenv("NAVER_CLIENT_SECRET")
        or os.getenv("NAVER_API_CLIENT_SECRET")
    )

    if not resolved_client_id or not resolved_client_secret:
        raise NaverNewsApiError(
            "NAVER_CLIENT_ID/NAVER_API_CLIENT_ID and "
            "NAVER_CLIENT_SECRET/NAVER_API_CLIENT_SECRET must be set."
        )

    return resolved_client_id, resolved_client_secret


def search_news(
    query: str,
    *,
    display: int = 10,
    start: int = 1,
    sort: str = "date",
    client_id: str | None = None,
    client_secret: str | None = None,
    timeout: int = 10,
) -> dict[str, Any]:
    if not query.strip():
        raise ValueError("query must not be empty.")

    if not 1 <= display <= 100:
        raise ValueError("display must be between 1 and 100.")

    if not 1 <= start <= 1000:
        raise ValueError("start must be between 1 and 1000.")

    if sort not in {"sim", "date"}:
        raise ValueError("sort must be 'sim' or 'date'.")

    resolved_client_id, resolved_client_secret = get_naver_credentials(
        client_id,
        client_secret,
    )

    response = requests.get(
        NAVER_NEWS_API_URL,
        headers={
            "X-Naver-Client-Id": resolved_client_id,
            "X-Naver-Client-Secret": resolved_client_secret,
        },
        params={
            "query": query,
            "display": display,
            "start": start,
            "sort": sort,
        },
        timeout=timeout,
    )

    if response.status_code != 200:
        raise NaverNewsApiError(
            f"Naver News API failed: status={response.status_code}, body={response.text}"
        )

    return response.json()


def normalize_news_item(
    item: dict[str, Any],
    *,
    query: str,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    fetched_at = fetched_at or datetime.now()
    original_url = item.get("originallink") or ""
    naver_url = item.get("link") or ""
    url = original_url or naver_url

    return {
        "source_id": "naver_news",
        "source_type": "api",
        "query": query,
        "title": clean_html(item.get("title")),
        "description": clean_html(item.get("description")),
        "url": url,
        "original_url": original_url,
        "naver_url": naver_url,
        "published_at": parse_pub_date(item.get("pubDate")),
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
        "raw": item,
    }


def fetch_news_items(
    query: str,
    *,
    display: int = 10,
    start: int = 1,
    sort: str = "date",
    client_id: str | None = None,
    client_secret: str | None = None,
    timeout: int = 10,
) -> list[dict[str, Any]]:
    fetched_at = datetime.now()
    payload = search_news(
        query,
        display=display,
        start=start,
        sort=sort,
        client_id=client_id,
        client_secret=client_secret,
        timeout=timeout,
    )

    return [
        normalize_news_item(item, query=query, fetched_at=fetched_at)
        for item in payload.get("items", [])
    ]
