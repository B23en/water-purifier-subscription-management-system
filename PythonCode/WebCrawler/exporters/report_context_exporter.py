from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from ..market_relevance import (
    filter_clean_water_purifier_items,
    has_other_product_signal,
    is_clean_water_purifier_text,
)
from .issue_exporter import export_monthly_issues
from .shopping_exporter import export_monthly_shopping, parse_month


def export_report_context(
    db_path: Path,
    *,
    month: str,
    brand_id: str | None = None,
    news_limit: int = 20,
    blog_limit: int = 20,
    shopping_change_limit: int = 20,
    min_summary_confidence: float = 0.6,
) -> dict[str, Any]:
    start_date, end_date = parse_month(month)

    news_summary_package = export_monthly_issues(
        db_path,
        month=month,
        mode="summary",
        source_id="naver_news",
        brand_id=brand_id,
        limit=news_limit,
    )
    blog_summary_package = export_monthly_issues(
        db_path,
        month=month,
        mode="summary",
        source_id="naver_blog",
        brand_id=brand_id,
        limit=blog_limit,
    )
    shopping_package = export_monthly_shopping(
        db_path,
        month=month,
        source_id="naver_shopping",
        brand_id=brand_id,
        change_limit=shopping_change_limit,
    )

    news_summary_count = len(news_summary_package.get("documents", []))
    blog_summary_count = len(blog_summary_package.get("documents", []))
    news_events = build_summary_events(
        news_summary_package,
        material_source="naver_news",
        min_confidence=min_summary_confidence,
    )
    blog_events = build_summary_events(
        blog_summary_package,
        material_source="naver_blog",
        min_confidence=min_summary_confidence,
    )

    shopping_context = build_shopping_context(shopping_package)
    shopping_events = shopping_context.get("events", [])
    market_events = news_events + blog_events + shopping_events
    shopping_brands = shopping_package.get("brands", [])
    event_counts = count_events(market_events)
    limitations = build_limitations(
        shopping_package,
        missing_summary_sources=missing_summary_sources(
            news_summary_count,
            blog_summary_count,
        ),
    )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "period": {
            "month": month,
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
        },
        "source": "web_crawler",
        "dataset": "market_observation_material",
        "filters": {
            "brand_id": brand_id,
            "news_limit": news_limit,
            "blog_limit": blog_limit,
            "shopping_change_limit": shopping_change_limit,
            "min_summary_confidence": min_summary_confidence,
        },
        "stats": {
            "news_summary_count": news_summary_count,
            "blog_summary_count": blog_summary_count,
            "news_event_count": len(news_events),
            "blog_event_count": len(blog_events),
            "shopping_event_count": len(shopping_events),
            "market_event_count": len(market_events),
            "shopping_brand_count": len(shopping_brands),
            "shopping_snapshot_count": shopping_package.get("stats", {}).get(
                "snapshot_count",
                0,
            ),
            "shopping_product_candidate_count": shopping_package.get(
                "stats",
                {},
            ).get("product_candidate_count", 0),
        },
        "context": {
            "market_summary": {
                "event_counts": event_counts,
                "event_brand_counts": count_by_key(market_events, "brand_id"),
                "event_source_counts": count_by_key(
                    market_events,
                    "material_source",
                ),
                "limitations": limitations,
                "shopping": {
                    "snapshot_count": shopping_package.get("stats", {}).get(
                        "snapshot_count",
                        0,
                    ),
                    "product_candidate_count": shopping_package.get(
                        "stats",
                        {},
                    ).get("product_candidate_count", 0),
                    "brand_count": shopping_package.get("stats", {}).get(
                        "brand_count",
                        0,
                    ),
                    "captured_dates": shopping_package.get("stats", {}).get(
                        "captured_dates",
                        [],
                    ),
                    "price_summary": shopping_package.get("price_summary", {}),
                },
            },
            "events": market_events,
            "shopping": {
                key: value
                for key, value in shopping_context.items()
                if key != "events"
            },
            "source_refs": {
                "news": "document_summaries",
                "blogs": "document_summaries",
                "shopping": "product_snapshots",
            },
        },
    }


def count_events(events: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(event.get("event_type") or "unknown" for event in events)
    return dict(sorted(counter.items()))


def count_by_key(events: list[dict[str, Any]], key: str) -> dict[str, int]:
    counter = Counter(event.get(key) or "unknown" for event in events)
    return dict(sorted(counter.items()))


def build_limitations(
    shopping_package: dict[str, Any],
    *,
    missing_summary_sources: list[str],
) -> list[str]:
    limitations = []
    captured_date_count = shopping_package.get("stats", {}).get(
        "captured_date_count",
        0,
    )
    if captured_date_count < 2:
        limitations.append(
            "shopping has fewer than two captured dates; price-change, "
            "new-product, and disappeared-product shopping events are limited"
        )

    if missing_summary_sources:
        limitations.append(
            "document summaries are missing for "
            + ", ".join(sorted(missing_summary_sources))
            + "; run summarize-documents before exporting report context"
        )

    return limitations


def missing_summary_sources(
    news_summary_count: int,
    blog_summary_count: int,
) -> list[str]:
    sources = []
    if news_summary_count == 0:
        sources.append("naver_news")
    if blog_summary_count == 0:
        sources.append("naver_blog")
    return sources


def build_summary_events(
    summary_package: dict[str, Any],
    *,
    material_source: str,
    min_confidence: float,
) -> list[dict[str, Any]]:
    events = []

    for document in summary_package.get("documents", []):
        confidence = document.get("confidence")
        if confidence is not None and confidence < min_confidence:
            continue

        facts = filter_clean_water_purifier_items(
            compact_facts(document.get("key_points", []))
        )
        evidence_excerpt = document.get("evidence_excerpt")
        if evidence_excerpt and is_clean_water_purifier_text(evidence_excerpt):
            facts.append(evidence_excerpt)

        mentioned_products = filter_clean_water_purifier_items(
            document.get("mentioned_products", [])
        )
        summary_is_other_product = has_other_product_signal(document.get("summary"))
        if summary_is_other_product and not is_clean_water_purifier_text(
            document.get("summary")
        ):
            continue
        if not (
            is_clean_water_purifier_text(document.get("summary"))
            or is_clean_water_purifier_text(document.get("title"))
            or facts
            or mentioned_products
        ):
            continue

        event = {
            "event_id": document.get("summary_id"),
            "event_date": document.get("date"),
            "event_type": document.get("event_type")
            or "general_market_reaction",
            "material_source": material_source,
            "brand_id": document.get("brand_id"),
            "brand_name": document.get("brand"),
            "title": document.get("title"),
            "summary": document.get("summary"),
            "url": document.get("url"),
            "facts": facts,
            "mentioned_products": mentioned_products,
            "sentiment": document.get("sentiment"),
            "confidence": confidence,
            "source_ref": {
                "doc_id": document.get("doc_id"),
                "summary_id": document.get("summary_id"),
                "source_id": document.get("source"),
                "summary_model": document.get("summary_model"),
                "prompt_version": document.get("prompt_version"),
            },
        }
        events.append(drop_empty(event))

    return events


def build_shopping_context(shopping_package: dict[str, Any]) -> dict[str, Any]:
    brands = shopping_package.get("brands", [])
    brand_contexts = []
    events = []

    for brand in brands:
        brand_events = build_shopping_events_for_brand(brand)
        events.extend(brand_events)
        brand_contexts.append(
            {
                "brand_id": brand.get("brand_id"),
                "brand_name": brand.get("brand_name"),
                "stats": compact_brand_stats(brand.get("stats", {})),
                "price_summary": brand.get("price_summary", {}),
                "event_counts": count_events(brand_events),
            }
        )

    return {
        "stats": shopping_package.get("stats", {}),
        "price_summary": shopping_package.get("price_summary", {}),
        "brands": brand_contexts,
        "events": events,
    }


def compact_brand_stats(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_count": stats.get("snapshot_count", 0),
        "product_candidate_count": stats.get("product_candidate_count", 0),
        "captured_dates": stats.get("captured_dates", []),
    }


def build_shopping_events_for_brand(brand: dict[str, Any]) -> list[dict[str, Any]]:
    events = []

    for change in brand.get("price_changes", []):
        events.append(build_price_change_event(change))

    for product in brand.get("new_products", []):
        events.append(build_product_appearance_event(product, "new_product"))

    for product in brand.get("disappeared_products", []):
        events.append(build_product_appearance_event(product, "disappeared_product"))

    return [drop_empty(event) for event in events]


def build_price_change_event(change: dict[str, Any]) -> dict[str, Any]:
    change_amount = change.get("change_amount")
    event_type = "price_change"
    if isinstance(change_amount, (int, float)):
        event_type = "price_drop" if change_amount < 0 else "price_increase"

    previous_price = change.get("previous_price")
    current_price = change.get("current_price")

    return {
        "event_date": change.get("current_date"),
        "event_type": event_type,
        "material_source": "naver_shopping",
        "brand_id": change.get("brand_id"),
        "brand_name": change.get("brand_name"),
        "product_name": change.get("product_name"),
        "title": build_price_change_title(change.get("product_name"), event_type),
        "facts": compact_facts(
            [
                format_price_fact(
                    previous_price,
                    current_price,
                    change.get("price_type"),
                ),
                format_change_fact(
                    change_amount,
                    change.get("change_rate"),
                ),
                format_observed_dates_fact(
                    change.get("previous_date"),
                    change.get("current_date"),
                ),
            ]
        ),
    }


def build_product_appearance_event(
    product: dict[str, Any],
    event_type: str,
) -> dict[str, Any]:
    price = product.get("display_price")
    price_kind = product.get("price_type")

    return {
        "event_date": product.get("captured_date"),
        "event_type": event_type,
        "material_source": "naver_shopping",
        "brand_id": product.get("brand_id"),
        "brand_name": product.get("brand_name"),
        "product_name": product.get("product_name"),
        "title": build_product_appearance_title(
            product.get("product_name"),
            event_type,
        ),
        "facts": compact_facts(
            [
                product.get("category"),
                product.get("sales_type"),
                format_single_price_fact(price, price_kind),
            ]
        ),
    }


def build_price_change_title(
    product_name: str | None,
    event_type: str,
) -> str:
    label = {
        "price_drop": "price drop",
        "price_increase": "price increase",
    }.get(event_type, "price change")
    return f"{product_name} {label}" if product_name else label


def build_product_appearance_title(
    product_name: str | None,
    event_type: str,
) -> str:
    label = {
        "new_product": "newly observed",
        "disappeared_product": "no longer observed",
    }.get(event_type, event_type)
    return f"{product_name} {label}" if product_name else label


def format_price_fact(
    previous_price: Any,
    current_price: Any,
    price_kind: str | None,
) -> str | None:
    if previous_price is None or current_price is None:
        return None
    label = price_label(price_kind)
    return f"{label}: {previous_price:,} -> {current_price:,}"


def format_change_fact(
    change_amount: Any,
    change_rate: Any,
) -> str | None:
    if change_amount is None and change_rate is None:
        return None
    parts = []
    if isinstance(change_amount, (int, float)):
        parts.append(f"change amount {change_amount:,}")
    if isinstance(change_rate, (int, float)):
        parts.append(f"change rate {change_rate}%")
    return ", ".join(parts)


def format_observed_dates_fact(
    previous_date: str | None,
    current_date: str | None,
) -> str | None:
    if not previous_date or not current_date:
        return None
    return f"observed dates: {previous_date} -> {current_date}"


def format_single_price_fact(
    price: Any,
    price_kind: str | None,
) -> str | None:
    if price is None:
        return None
    return f"{price_label(price_kind)}: {price:,}"


def price_label(price_kind: str | None) -> str:
    if price_kind == "rental_fee":
        return "rental fee"
    if price_kind == "purchase_price":
        return "purchase price"
    return "price"


def compact_facts(values: list[Any]) -> list[str]:
    facts = []
    for value in values:
        if value is None:
            continue

        text = str(value).strip()
        if text:
            facts.append(text)

    return facts


def drop_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if item is not None and item != "" and item != [] and item != {}
    }
