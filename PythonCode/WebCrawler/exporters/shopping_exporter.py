from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
import json
import re

import duckdb


def parse_month(month: str) -> tuple[date, date]:
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("month must be in YYYY-MM format.")

    year, month_number = [int(part) for part in month.split("-")]
    start_date = date(year, month_number, 1)

    if month_number == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month_number + 1, 1)

    return start_date, end_date


def parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def load_monthly_product_snapshots(
    db_path: Path,
    *,
    month: str,
    source_id: str | None = "naver_shopping",
    brand_id: str | None = None,
) -> list[dict[str, Any]]:
    start_date, end_date = parse_month(month)
    where_clauses = [
        "captured_date >= ?",
        "captured_date < ?",
    ]
    params: list[Any] = [
        start_date.isoformat(),
        end_date.isoformat(),
    ]

    if source_id:
        where_clauses.append("source_id = ?")
        params.append(source_id)

    if brand_id:
        where_clauses.append("brand_id = ?")
        params.append(brand_id)

    query = f"""
        SELECT
            snapshot_id,
            source_id,
            brand_id,
            brand_name,
            product_name,
            model_code,
            category,
            sales_type,
            purchase_price,
            rental_fee,
            original_rental_fee,
            promotion_text,
            rating,
            review_count,
            product_url,
            CAST(captured_date AS VARCHAR) AS captured_date,
            CAST(captured_at AS VARCHAR) AS captured_at,
            raw_path,
            content_hash,
            metadata_json
        FROM product_snapshots
        WHERE {" AND ".join(where_clauses)}
        ORDER BY captured_date DESC, captured_at DESC, brand_name, product_name
    """

    with duckdb.connect(str(db_path)) as connection:
        cursor = connection.execute(query, params)
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()

    return [dict(zip(columns, row)) for row in rows]


def product_identity(snapshot: dict[str, Any]) -> str:
    product_url = snapshot.get("product_url")
    if product_url:
        return f"url:{product_url}"

    brand_id = snapshot.get("brand_id") or ""
    product_name = normalize_space(str(snapshot.get("product_name") or "")).lower()
    model_code = normalize_space(str(snapshot.get("model_code") or "")).lower()
    return f"name:{brand_id}:{model_code}:{product_name}"


def is_rental_snapshot(snapshot: dict[str, Any]) -> bool:
    return snapshot.get("sales_type") == "rental"


def normalized_purchase_price(snapshot: dict[str, Any]) -> int | None:
    if is_rental_snapshot(snapshot):
        return None

    value = snapshot.get("purchase_price")
    if value is None:
        return None
    return int(value)


def normalized_rental_fee(snapshot: dict[str, Any]) -> int | None:
    if not is_rental_snapshot(snapshot):
        value = snapshot.get("rental_fee")
        return int(value) if value is not None else None

    value = snapshot.get("rental_fee")
    if value is None:
        # Backward compatibility for rows saved before rental_fee mapping existed.
        value = snapshot.get("purchase_price")
    if value is None:
        return None
    return int(value)


def price_type(snapshot: dict[str, Any]) -> str:
    return "rental_fee" if is_rental_snapshot(snapshot) else "purchase_price"


def price_value(snapshot: dict[str, Any]) -> int | None:
    if is_rental_snapshot(snapshot):
        return normalized_rental_fee(snapshot)

    purchase_price = normalized_purchase_price(snapshot)
    if purchase_price is not None:
        return purchase_price
    return normalized_rental_fee(snapshot)


def mean_int(values: list[int]) -> int | None:
    if not values:
        return None
    return round(sum(values) / len(values))


def amount_summary(values: list[int]) -> dict[str, Any]:
    return {
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "avg": mean_int(values),
        "count": len(values),
    }


def price_summary(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    display_prices = [
        price for price in (price_value(row) for row in snapshots) if price is not None
    ]
    purchase_prices = [
        price
        for price in (normalized_purchase_price(row) for row in snapshots)
        if price is not None
    ]
    rental_fees = [
        fee
        for fee in (normalized_rental_fee(row) for row in snapshots)
        if fee is not None
    ]

    return {
        "min_price": min(display_prices) if display_prices else None,
        "max_price": max(display_prices) if display_prices else None,
        "avg_price": mean_int(display_prices),
        "priced_snapshot_count": len(display_prices),
        "purchase_price": amount_summary(purchase_prices),
        "rental_fee": amount_summary(rental_fees),
    }


def compact_product(snapshot: dict[str, Any]) -> dict[str, Any]:
    normalized_purchase = normalized_purchase_price(snapshot)
    normalized_rental = normalized_rental_fee(snapshot)
    display_price = price_value(snapshot)

    return {
        "captured_date": snapshot.get("captured_date"),
        "brand_id": snapshot.get("brand_id"),
        "brand_name": snapshot.get("brand_name"),
        "product_name": snapshot.get("product_name"),
        "category": snapshot.get("category"),
        "sales_type": snapshot.get("sales_type"),
        "price_type": price_type(snapshot),
        "display_price": display_price,
        "purchase_price": normalized_purchase,
        "rental_fee": normalized_rental,
    }


def choose_representative(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    priced = [snapshot for snapshot in snapshots if price_value(snapshot) is not None]
    if priced:
        return min(priced, key=lambda snapshot: price_value(snapshot) or 0)
    return snapshots[0]


def snapshots_by_product_and_date(
    snapshots: list[dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in snapshots:
        grouped[product_identity(row)][str(row.get("captured_date") or "")].append(row)

    result: dict[str, dict[str, dict[str, Any]]] = {}
    for product_key, rows_by_date in grouped.items():
        result[product_key] = {
            captured_date: choose_representative(rows)
            for captured_date, rows in rows_by_date.items()
            if rows
        }

    return result


def price_changes(
    snapshots: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    rows_by_product = snapshots_by_product_and_date(snapshots)
    changes = []

    for rows_by_date in rows_by_product.values():
        dates = sorted(date for date in rows_by_date if date)
        if len(dates) < 2:
            continue

        previous = rows_by_date[dates[-2]]
        current = rows_by_date[dates[-1]]
        previous_price = price_value(previous)
        current_price = price_value(current)
        if previous_price is None or current_price is None:
            continue
        if previous_price == current_price:
            continue

        change_amount = current_price - previous_price
        change_rate = round(change_amount / previous_price * 100, 2)
        changes.append(
            {
                "brand_id": current.get("brand_id"),
                "brand_name": current.get("brand_name"),
                "product_name": current.get("product_name"),
                "previous_date": previous.get("captured_date"),
                "current_date": current.get("captured_date"),
                "previous_price": previous_price,
                "current_price": current_price,
                "price_type": price_type(current),
                "change_amount": change_amount,
                "change_rate": change_rate,
            }
        )

    changes.sort(
        key=lambda change: (
            abs(change.get("change_rate") or 0),
            abs(change.get("change_amount") or 0),
        ),
        reverse=True,
    )
    return changes[:limit] if limit > 0 else changes


def product_appearances(
    snapshots: list[dict[str, Any]],
    *,
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    if not snapshots:
        return {"new_products": [], "disappeared_products": []}

    dates = sorted({str(row.get("captured_date") or "") for row in snapshots if row.get("captured_date")})
    if len(dates) < 2:
        return {"new_products": [], "disappeared_products": []}

    previous_date, current_date = dates[-2], dates[-1]
    rows_by_product = snapshots_by_product_and_date(snapshots)

    new_products = []
    disappeared_products = []
    for rows_by_date in rows_by_product.values():
        has_previous = previous_date in rows_by_date
        has_current = current_date in rows_by_date

        if has_current and not has_previous:
            new_products.append(compact_product(rows_by_date[current_date]))
        elif has_previous and not has_current:
            disappeared_products.append(compact_product(rows_by_date[previous_date]))

    new_products.sort(key=lambda product: product.get("product_name") or "")
    disappeared_products.sort(key=lambda product: product.get("product_name") or "")

    return {
        "new_products": new_products[:limit] if limit > 0 else new_products,
        "disappeared_products": (
            disappeared_products[:limit] if limit > 0 else disappeared_products
        ),
    }


def build_brand_package(
    brand_id: str,
    snapshots: list[dict[str, Any]],
    *,
    change_limit: int,
) -> dict[str, Any]:
    captured_dates = sorted(
        {str(row.get("captured_date") or "") for row in snapshots if row.get("captured_date")}
    )
    product_keys = {product_identity(row) for row in snapshots}
    mall_names = {
        parse_json(row.get("metadata_json")).get("mall_name")
        for row in snapshots
        if parse_json(row.get("metadata_json")).get("mall_name")
    }

    brand_name = snapshots[0].get("brand_name") if snapshots else None
    appearances = product_appearances(snapshots, limit=change_limit)

    return {
        "brand_id": brand_id,
        "brand_name": brand_name,
        "stats": {
            "snapshot_count": len(snapshots),
            "product_candidate_count": len(product_keys),
            "mall_count": len(mall_names),
            "captured_date_count": len(captured_dates),
            "captured_dates": captured_dates,
        },
        "price_summary": price_summary(snapshots),
        "price_changes": price_changes(snapshots, limit=change_limit),
        **appearances,
    }


def export_monthly_shopping(
    db_path: Path,
    *,
    month: str,
    source_id: str | None = "naver_shopping",
    brand_id: str | None = None,
    change_limit: int = 20,
) -> dict[str, Any]:
    start_date, end_date = parse_month(month)
    snapshots = load_monthly_product_snapshots(
        db_path,
        month=month,
        source_id=source_id,
        brand_id=brand_id,
    )

    brand_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in snapshots:
        brand_groups[str(snapshot.get("brand_id") or "")].append(snapshot)

    brands = [
        build_brand_package(
            current_brand_id,
            brand_snapshots,
            change_limit=change_limit,
        )
        for current_brand_id, brand_snapshots in sorted(brand_groups.items())
    ]

    product_keys = {product_identity(row) for row in snapshots}
    mall_names = {
        parse_json(row.get("metadata_json")).get("mall_name")
        for row in snapshots
        if parse_json(row.get("metadata_json")).get("mall_name")
    }
    captured_dates = sorted(
        {str(row.get("captured_date") or "") for row in snapshots if row.get("captured_date")}
    )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "period": {
            "month": month,
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
        },
        "source": "web_crawler",
        "dataset": "shopping_price_snapshots",
        "filters": {
            "source_id": source_id,
            "brand_id": brand_id,
            "change_limit": change_limit,
        },
        "stats": {
            "snapshot_count": len(snapshots),
            "brand_count": len(brand_groups),
            "product_candidate_count": len(product_keys),
            "mall_count": len(mall_names),
            "captured_date_count": len(captured_dates),
            "captured_dates": captured_dates,
        },
        "price_summary": price_summary(snapshots),
        "brands": brands,
    }
