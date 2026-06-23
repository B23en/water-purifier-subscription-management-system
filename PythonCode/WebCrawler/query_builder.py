from __future__ import annotations
from itertools import product
from typing import Any
import re



_PLACEHOLDER_RE = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)}")


def build_queries(targets: dict, source_id: str) -> list[dict]:
    if not isinstance(targets, dict):
        raise TypeError("targets must be a dictionary loaded from targets.yaml")

    source = _get_source(targets, source_id)
    if not source or not source.get("enabled", False):
        return []

    if "keywords" in source:
        return _build_keyword_queries(source_id, source)

    template_group_names = source.get("use_template_groups", [])
    template_groups = targets.get("query_strategy", {}).get("template_groups", {})
    max_per_brand = int(
        source.get(
            "max_queries_per_brand",
            targets.get("query_strategy", {}).get("max_queries_per_brand_per_source", 0),
        )
        or 0
    )

    queries: list[dict] = []
    seen: set[tuple[str, str | None]] = set()
    brands = _iter_enabled_brands(targets, source)

    for group_name in template_group_names:
        templates = template_groups.get(group_name, [])
        if not templates:
            continue

        for template in templates:
            placeholders = set(_PLACEHOLDER_RE.findall(template))
            if "brand" in placeholders:
                for brand in brands:
                    brand_count = _count_brand_queries(queries, brand.get("id"))
                    for record in _expand_template(
                        targets=targets,
                        source_id=source_id,
                        source=source,
                        group_name=group_name,
                        template=template,
                        brand=brand,
                    ):
                        if max_per_brand and brand_count >= max_per_brand:
                            break
                        dedupe_key = (record["query"], record.get("brand_id"))
                        if dedupe_key in seen:
                            continue
                        seen.add(dedupe_key)
                        queries.append(record)
                        brand_count += 1
            else:
                for record in _expand_template(
                    targets=targets,
                    source_id=source_id,
                    source=source,
                    group_name=group_name,
                    template=template,
                    brand=None,
                ):
                    dedupe_key = (record["query"], None)
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    queries.append(record)

    return queries


def _get_source(targets: dict, source_id: str) -> dict[str, Any]:
    sources = targets.get("sources", {})
    if not isinstance(sources, dict):
        return {}
    return sources.get(source_id, {}) or {}


def _build_keyword_queries(source_id: str, source: dict[str, Any]) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()

    for keyword in source.get("keywords", []) or []:
        query = _normalize_query(str(keyword))
        if not query or query in seen:
            continue
        seen.add(query)
        results.append(
            {
                "source_id": source_id,
                "source_type": source.get("type"),
                "cadence": source.get("cadence"),
                "query": query,
                "keyword": query,
                "brand_id": None,
                "brand_name": None,
                "brand_priority": None,
                "template_group": None,
                "template": None,
                "terms": {},
                "max_results": source.get("max_results_per_query"),
            }
        )

    return results


def _iter_enabled_brands(targets: dict, source: dict[str, Any]) -> list[dict[str, Any]]:
    allowed_priorities = source.get("priorities")
    allowed_roles = source.get("roles", ["competitor"])
    include_pending = source.get("include_pending_review", True)

    brands: list[dict[str, Any]] = []
    for brand in targets.get("brands", []) or []:
        if brand.get("enabled", True) is False:
            continue
        if not include_pending and brand.get("status") == "pending_review":
            continue

        role = brand.get("role", "competitor")
        if allowed_roles and role not in allowed_roles:
            continue

        priority = brand.get("priority")
        if allowed_priorities and priority not in allowed_priorities:
            continue

        brands.append(brand)

    return brands


def _expand_template(
    *,
    targets: dict,
    source_id: str,
    source: dict[str, Any],
    group_name: str,
    template: str,
    brand: dict[str, Any] | None,
) -> list[dict]:
    placeholders = list(dict.fromkeys(_PLACEHOLDER_RE.findall(template)))
    term_names = [name for name in placeholders if name != "brand"]
    term_values = [_terms_for_placeholder(targets, name) for name in term_names]

    if any(not values for values in term_values):
        return []

    records: list[dict] = []
    combinations = product(*term_values) if term_values else [()]

    for combo in combinations:
        terms = dict(zip(term_names, combo))
        values = dict(terms)
        if brand is not None:
            values["brand"] = brand.get("name", "")

        query = _normalize_query(template.format(**values))
        if not query:
            continue

        records.append(
            {
                "source_id": source_id,
                "source_type": source.get("type"),
                "cadence": source.get("cadence"),
                "query": query,
                "brand_id": brand.get("id") if brand else None,
                "brand_name": brand.get("name") if brand else None,
                "brand_priority": brand.get("priority") if brand else None,
                "template_group": group_name,
                "template": template,
                "terms": terms,
                "max_results": source.get("max_results_per_query"),
            }
        )

    return records


def _terms_for_placeholder(targets: dict, placeholder: str) -> list[str]:
    market_terms = targets.get("market_terms", {}) or {}
    if placeholder in market_terms:
        return _as_text_list(market_terms.get(placeholder))

    if placeholder == "reaction":
        return _as_text_list(targets.get("reaction_terms"))

    category_terms = targets.get("category_terms", {}) or {}
    if placeholder == "product_type":
        return _as_text_list(category_terms.get("product_types"))
    if placeholder == "sales":
        return _as_text_list(category_terms.get("sales_terms"))
    if placeholder == "core":
        return _as_text_list(category_terms.get("core"))

    return []


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []

    results: list[str] = []
    for item in value:
        text = _normalize_query(str(item))
        if text:
            results.append(text)
    return results


def _normalize_query(query: str) -> str:
    return " ".join(query.split())


def _count_brand_queries(queries: list[dict], brand_id: str | None) -> int:
    return sum(1 for query in queries if query.get("brand_id") == brand_id)
