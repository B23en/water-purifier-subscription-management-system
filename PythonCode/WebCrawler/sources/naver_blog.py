from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit
import re

import requests

from .naver_news import clean_html, get_naver_credentials


NAVER_BLOG_API_URL = "https://openapi.naver.com/v1/search/blog.json"
DEFAULT_QUERY_TEMPLATES = [
    "{brand} 정수기 후기",
    "{brand} 정수기 리뷰",
    "{brand} 정수기 단점",
    "{brand} 정수기 추천",
    "{brand} 신제품 정수기 후기",
]

REVIEW_INTENT_TERMS = ("후기", "리뷰", "사용기", "사용후기", "장점", "단점", "추천")
WATER_PURIFIER_TERMS = ("정수기",)
NOISE_TERMS = (
    "피부관리",
    "에스테틱",
    "카페",
    "식당",
    "맛집",
    "숙소",
    "호텔",
    "병원",
    "미용실",
    "사무실",
    "대기 공간",
    "대기공간",
    "커피머신",
    "네스프레소",
)
PART_PRODUCT_TERMS = (
    "정수기필터",
    "필터호환",
    "필터세트",
    "필터전체세트",
    "호환필터",
    "호환용",
    "전체세트",
    "교체필터",
    "카트리지",
    "신형브라켓",
    "개조형",
    "단방향",
)
COMMERCE_ROUNDUP_TERMS = (
    "별점",
    "최저가",
    "구매하기",
    "판매처",
    "무료배송",
    "쿠팡",
    "파트너스",
)


class NaverBlogApiError(RuntimeError):
    pass


def fetch_blog_items(
    query: str,
    *,
    display: int = 10,
    start: int = 1,
    sort: str = "date",
    timeout: int = 10,
) -> list[dict[str, Any]]:
    payload = search_blog(
        query,
        display=display,
        start=start,
        sort=sort,
        timeout=timeout,
    )
    fetched_at = datetime.now()

    return [
        normalize_blog_item(item, query=query, fetched_at=fetched_at)
        for item in payload.get("items", [])
    ]


def search_blog(
    query: str,
    *,
    display: int,
    start: int,
    sort: str,
    timeout: int,
) -> dict[str, Any]:
    if not query.strip():
        raise ValueError("query must not be empty.")

    if not 1 <= display <= 100:
        raise ValueError("display must be between 1 and 100.")

    if not 1 <= start <= 1000:
        raise ValueError("start must be between 1 and 1000.")

    if sort not in {"sim", "date"}:
        raise ValueError("sort must be 'sim' or 'date'.")

    client_id, client_secret = get_naver_credentials()
    response = requests.get(
        NAVER_BLOG_API_URL,
        headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
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
        raise NaverBlogApiError(
            f"Naver Blog API failed: status={response.status_code}, body={response.text}"
        )

    return response.json()


def normalize_blog_item(
    item: dict[str, Any],
    *,
    query: str,
    fetched_at: datetime,
) -> dict[str, Any]:
    raw_url = item.get("link") or ""
    return {
        "source_id": "naver_blog",
        "source_type": "api",
        "query": query,
        "title": clean_html(item.get("title")),
        "description": clean_html(item.get("description")),
        "url": canonicalize_blog_url(raw_url),
        "raw_url": raw_url,
        "blogger_name": clean_html(item.get("bloggername")),
        "blogger_link": item.get("bloggerlink") or "",
        "published_at": parse_post_date(item.get("postdate")),
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
    }


def build_blog_queries(targets: dict[str, Any]) -> list[dict[str, Any]]:
    source = targets.get("sources", {}).get("naver_blog", {})
    templates = source.get("query_templates") or DEFAULT_QUERY_TEMPLATES

    queries: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for brand in targets.get("brands", []):
        if brand.get("enabled", True) is False:
            continue

        for template in templates:
            query = " ".join(
                template.format(brand=brand.get("name", "")).split()
            )
            dedupe_key = (query, brand.get("id"))
            if not query or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            queries.append(
                {
                    "source_id": "naver_blog",
                    "source_type": source.get("type"),
                    "cadence": source.get("cadence"),
                    "query": query,
                    "brand_id": brand.get("id"),
                    "brand_name": brand.get("name"),
                    "brand_priority": brand.get("priority"),
                    "template": template,
                    "max_results": source.get("display"),
                }
            )

    return queries


def is_relevant_blog_item(item: dict[str, Any]) -> bool:
    title = item.get("title") or ""
    description = item.get("description") or ""
    combined = normalize_text(f"{title} {description}")
    title_text = normalize_text(title)

    if any(term in combined for term in NOISE_TERMS):
        return False
    if is_part_product_post(title_text, combined):
        return False

    has_review_intent = any(term in combined for term in REVIEW_INTENT_TERMS)
    has_water_purifier = any(term in combined for term in WATER_PURIFIER_TERMS)
    title_has_water_or_review = any(
        term in title_text for term in (*WATER_PURIFIER_TERMS, *REVIEW_INTENT_TERMS)
    )

    return has_review_intent and has_water_purifier and title_has_water_or_review


def is_relevant_blog_text(text: str | None) -> bool:
    if not text:
        return False

    normalized = normalize_text(text[:3000])
    if any(term in normalized for term in NOISE_TERMS):
        return False
    if is_part_product_post(normalized[:500], normalized):
        return False
    if is_commerce_roundup_text(text):
        return False

    water_count = sum(normalized.count(term) for term in WATER_PURIFIER_TERMS)
    has_review_intent = any(term in normalized for term in REVIEW_INTENT_TERMS)

    return water_count >= 2 and has_review_intent


def is_part_product_post(title_text: str, combined_text: str) -> bool:
    has_part_term = any(term in combined_text for term in PART_PRODUCT_TERMS)
    title_is_filter_focused = "필터" in title_text and (
        "호환" in title_text or "세트" in title_text or "카트리지" in title_text
    )
    return has_part_term or title_is_filter_focused


def is_commerce_roundup_text(text: str) -> bool:
    normalized = normalize_text(text[:3000])
    commerce_hits = sum(1 for term in COMMERCE_ROUNDUP_TERMS if term in normalized)
    price_like_count = text.count("￦") + text.count("₩") + text.count("원")
    repeated_rating_count = text.count("별점") + text.count("⭐⭐")

    return commerce_hits >= 2 or price_like_count >= 5 or repeated_rating_count >= 3


def parse_post_date(value: str | None) -> str | None:
    if not value or len(value) != 8:
        return None

    return f"{value[:4]}-{value[4:6]}-{value[6:8]}T00:00:00"


def canonicalize_blog_url(url: str) -> str:
    url = str(url or "").strip()
    if not url:
        return ""

    parsed = urlsplit(url)
    hostname = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if hostname in {"blog.naver.com", "m.blog.naver.com"}:
        if len(path_parts) >= 2 and path_parts[0].lower() != "postview.naver":
            return f"https://blog.naver.com/{path_parts[0]}/{path_parts[1]}"

        query = parse_qs(parsed.query)
        blog_id = first_query_value(query, "blogId", "blogid")
        log_no = first_query_value(query, "logNo", "logno")
        if blog_id and log_no:
            return f"https://blog.naver.com/{blog_id}/{log_no}"

    return url


def first_query_value(query: dict[str, list[str]], *keys: str) -> str | None:
    for key in keys:
        values = query.get(key)
        if values:
            return values[0]
    return None


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()
