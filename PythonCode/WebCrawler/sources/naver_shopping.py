from __future__ import annotations

from datetime import datetime
from typing import Any
import re

import requests

from .naver_news import clean_html, get_naver_credentials


NAVER_SHOPPING_API_URL = "https://openapi.naver.com/v1/search/shop.json"

WATER_PURIFIER_TERMS = ("정수기",)
EXCLUDE_TERMS = (
    "필터",
    "필터세트",
    "필터 세트",
    "카트리지",
    "부품",
    "호스",
    "코크",
    "커버",
    "중고",
    "해외직구",
    "공기청정기",
    "비데",
    "밥솥",
)


class NaverShoppingApiError(RuntimeError):
    pass


def fetch_shopping_items(
    query: str,
    *,
    display: int = 50,
    start: int = 1,
    sort: str = "sim",
    timeout: int = 10,
) -> list[dict[str, Any]]:
    payload = search_shopping(
        query,
        display=display,
        start=start,
        sort=sort,
        timeout=timeout,
    )
    fetched_at = datetime.now()

    return [
        normalize_shopping_item(item, query=query, fetched_at=fetched_at)
        for item in payload.get("items", [])
    ]


def search_shopping(
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

    if sort not in {"sim", "date", "asc", "dsc"}:
        raise ValueError("sort must be one of sim, date, asc, dsc.")

    client_id, client_secret = get_naver_credentials()
    response = requests.get(
        NAVER_SHOPPING_API_URL,
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
        raise NaverShoppingApiError(
            "Naver Shopping API failed: "
            f"status={response.status_code}, body={response.text}"
        )

    return response.json()


def normalize_shopping_item(
    item: dict[str, Any],
    *,
    query: str,
    fetched_at: datetime,
) -> dict[str, Any]:
    title = clean_html(item.get("title"))
    lprice = parse_int(item.get("lprice"))
    hprice = parse_int(item.get("hprice"))
    category = [
        clean_html(item.get("category1")),
        clean_html(item.get("category2")),
        clean_html(item.get("category3")),
        clean_html(item.get("category4")),
    ]
    category = [part for part in category if part]

    return {
        "source_id": "naver_shopping",
        "source_type": "api",
        "query": query,
        "title": title,
        "url": item.get("link") or "",
        "image_url": item.get("image") or "",
        "lowest_price": lprice,
        "highest_price": hprice,
        "mall_name": clean_html(item.get("mallName")),
        "product_id": str(item.get("productId") or ""),
        "product_type": parse_int(item.get("productType")),
        "maker": clean_html(item.get("maker")),
        "brand": clean_html(item.get("brand")),
        "category": category,
        "sales_type": infer_sales_type(title, clean_html(item.get("mallName"))),
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
        "raw": item,
    }


def is_relevant_item(
    item: dict[str, Any],
    *,
    brand_name: str,
    aliases: list[str],
) -> bool:
    searchable_text = " ".join(
        [
            item.get("title") or "",
            item.get("mall_name") or "",
            item.get("brand") or "",
            item.get("maker") or "",
            " ".join(item.get("category") or []),
        ]
    )
    normalized_text = normalize_text(searchable_text)

    if not any(term in normalized_text for term in WATER_PURIFIER_TERMS):
        return False

    if any(term in normalized_text for term in EXCLUDE_TERMS):
        return False

    brand_terms = [brand_name, *aliases]
    normalized_brand_terms = [
        normalize_text(term)
        for term in brand_terms
        if term
    ]
    return any(term in normalized_text for term in normalized_brand_terms)


def build_brand_queries(targets: dict[str, Any]) -> list[dict[str, Any]]:
    source_settings = targets.get("sources", {}).get("naver_shopping", {})
    query_template = source_settings.get("query_template") or "{brand} 정수기"

    return [
        {
            "brand_id": brand.get("id"),
            "brand_name": brand.get("name"),
            "aliases": brand.get("aliases") or [],
            "query": query_template.format(brand=brand.get("name")),
        }
        for brand in targets.get("brands", [])
    ]


def infer_sales_type(*values: str) -> str:
    text = normalize_text(" ".join(value for value in values if value))
    if any(term in text for term in ("렌탈", "렌트", "구독", "월")):
        return "rental"
    if any(term in text for term in ("일시불", "구매", "판매")):
        return "purchase"
    return "unknown"


def parse_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    digits = re.sub(r"[^0-9]", "", str(value))
    if not digits:
        return None
    return int(digits)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()
