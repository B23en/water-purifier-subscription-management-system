from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable
import json
import os
import re

import duckdb

from .exporters.issue_exporter import (
    build_compact_source_text,
    build_summary_candidate,
    classify_issue,
    infer_sentiment,
    load_monthly_documents,
    parse_json,
    read_text,
)
from .market_relevance import (
    filter_clean_water_purifier_items,
    has_other_product_signal,
    is_clean_water_purifier_text,
    is_water_purifier_market_text,
)
from .storage.duckdb_store import make_hash, upsert_document_summary


PROMPT_VERSION = "webcrawler_document_summary_v2"
DEFAULT_MODEL = "gpt-4o-mini"
ALLOWED_EVENT_TYPES = {
    "new_product",
    "price_promotion",
    "marketing_campaign",
    "negative_issue",
    "consumer_reaction",
    "corporate_strategy",
    "general_market_reaction",
}
ALLOWED_SENTIMENTS = {"positive", "neutral", "negative"}


def get_llm_client() -> tuple[Any | None, str | None, str | None]:
    openai_key = valid_secret(os.getenv("OPENAI_API_KEY"))
    if openai_key:
        try:
            from openai import OpenAI
        except ImportError:
            return None, None, None

        return (
            OpenAI(api_key=openai_key),
            os.getenv("WEBCRAWLER_SUMMARY_MODEL")
            or os.getenv("OPENAI_MODEL")
            or DEFAULT_MODEL,
            "openai",
        )

    endpoint = valid_secret(os.getenv("AZURE_OAI_ENDPOINT"))
    azure_key = valid_secret(os.getenv("AZURE_OAI_KEY"))
    deployment = valid_secret(os.getenv("AZURE_OAI_DEPLOYMENT"))
    if endpoint and azure_key and deployment:
        try:
            from openai import AzureOpenAI
        except ImportError:
            return None, None, None

        return (
            AzureOpenAI(
                api_key=azure_key,
                azure_endpoint=endpoint,
                api_version=os.getenv("AZURE_OAI_API_VERSION", "2024-02-15-preview"),
            ),
            deployment,
            "azure",
        )

    return None, None, None


def valid_secret(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip().strip('"').strip("'")
    if not cleaned or cleaned in {"=", "-", "changeme", "CHANGE_ME"}:
        return None

    return cleaned


def existing_summary_ids(
    db_path: Path,
    *,
    model_name: str,
    prompt_version: str,
) -> set[tuple[str, str]]:
    with duckdb.connect(str(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT doc_id, content_hash
            FROM document_summaries
            WHERE model_name = ? AND prompt_version = ?
            """,
            [model_name, prompt_version],
        ).fetchall()

    return {(str(doc_id), str(content_hash)) for doc_id, content_hash in rows}


def summarize_documents(
    db_path: Path,
    *,
    month: str,
    source_id: str | None = None,
    brand_id: str | None = None,
    limit: int = 0,
    force: bool = False,
    allow_fallback: bool = False,
    max_input_chars: int = 6000,
    model_name: str | None = None,
    prompt_version: str = PROMPT_VERSION,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    client, detected_model, provider = get_llm_client()
    model = model_name or detected_model
    if client is None and not allow_fallback:
        raise RuntimeError(
            "No LLM credentials found. Set OPENAI_API_KEY or AZURE_OAI_*; "
            "use --allow-fallback only for local pipeline testing."
        )

    model = model or "fallback"
    provider = provider or "fallback"
    documents = load_monthly_documents(
        db_path,
        month=month,
        source_id=source_id,
        brand_id=brand_id,
    )
    if limit > 0:
        documents = documents[:limit]

    cached = set()
    if not force:
        cached = existing_summary_ids(
            db_path,
            model_name=model,
            prompt_version=prompt_version,
        )

    stats = {
        "document_count": len(documents),
        "summarized_count": 0,
        "inserted_count": 0,
        "updated_count": 0,
        "skipped_cached_count": 0,
        "skipped_empty_count": 0,
        "error_count": 0,
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
    }

    emit_progress(
        progress_callback,
        {
            "phase": "start",
            "month": month,
            "source_id": source_id,
            "brand_id": brand_id,
            "total": len(documents),
            "provider": provider,
            "model": model,
        },
    )

    for index, document in enumerate(documents, start=1):
        cache_key = (str(document.get("doc_id")), str(document.get("content_hash")))
        if cache_key in cached:
            stats["skipped_cached_count"] += 1
            emit_document_progress(
                progress_callback,
                "skip",
                index,
                len(documents),
                document,
                stats,
                reason="cached",
            )
            continue

        source_text = document_source_text(document, max_input_chars=max_input_chars)
        if not source_text:
            stats["skipped_empty_count"] += 1
            emit_document_progress(
                progress_callback,
                "skip",
                index,
                len(documents),
                document,
                stats,
                reason="empty",
            )
            continue

        emit_progress(
            progress_callback,
            {
                "phase": "process",
                "index": index,
                "total": len(documents),
                "doc_id": document.get("doc_id"),
                "source_id": document.get("source_id"),
                "brand_name": document.get("brand_name"),
                "title": document.get("title"),
                "input_chars": len(source_text),
            },
        )

        try:
            if client is None:
                summary = fallback_summary(document, source_text)
            else:
                summary = summarize_document_with_llm(
                    client,
                    model=model,
                    document=document,
                    source_text=source_text,
                )

            normalized = normalize_summary(summary, document, source_text)
            inserted = upsert_document_summary(
                db_path,
                build_summary_row(
                    document,
                    normalized,
                    model_name=model,
                    prompt_version=prompt_version,
                    provider=provider,
                    source_text=source_text,
                    fallback_used=client is None,
                ),
            )
            stats["summarized_count"] += 1
            if inserted:
                stats["inserted_count"] += 1
            else:
                stats["updated_count"] += 1
            emit_document_progress(
                progress_callback,
                "done",
                index,
                len(documents),
                document,
                stats,
                inserted=inserted,
            )
        except Exception as exc:
            stats["error_count"] += 1
            if is_authentication_error(exc):
                raise RuntimeError(
                    "LLM authentication failed. Check OPENAI_API_KEY or "
                    "AZURE_OAI_* in the environment/.env."
                ) from exc

            print(
                "summarize failed: "
                f"doc_id={document.get('doc_id')} "
                f"{type(exc).__name__}: {exc}"
            )
            emit_document_progress(
                progress_callback,
                "error",
                index,
                len(documents),
                document,
                stats,
                error=f"{type(exc).__name__}: {exc}",
            )

    return stats


def emit_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    event: dict[str, Any],
) -> None:
    if progress_callback:
        progress_callback(event)


def emit_document_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    phase: str,
    index: int,
    total: int,
    document: dict[str, Any],
    stats: dict[str, Any],
    **extra: Any,
) -> None:
    emit_progress(
        progress_callback,
        {
            "phase": phase,
            "index": index,
            "total": total,
            "doc_id": document.get("doc_id"),
            "source_id": document.get("source_id"),
            "brand_name": document.get("brand_name"),
            "title": document.get("title"),
            "stats": stats.copy(),
            **extra,
        },
    )


def is_authentication_error(exc: Exception) -> bool:
    if exc.__class__.__name__ == "AuthenticationError":
        return True
    status_code = getattr(exc, "status_code", None)
    return status_code == 401


def document_source_text(
    document: dict[str, Any],
    *,
    max_input_chars: int,
) -> str:
    text = read_text(document.get("text_path"), max(max_input_chars * 2, 10000))
    compact = build_compact_source_text(text, source_id=document.get("source_id"))
    if not compact:
        compact = "\n".join(
            part
            for part in [
                str(document.get("title") or ""),
                str(document.get("query") or ""),
            ]
            if part
        )
    return compact[:max_input_chars].strip()


def summarize_document_with_llm(
    client: Any,
    *,
    model: str,
    document: dict[str, Any],
    source_text: str,
) -> dict[str, Any]:
    prompt = build_prompt(document, source_text)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You extract market-observation facts for Korean water "
                    "purifier subscription reports. Return JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    content = response.choices[0].message.content or ""
    return parse_json_response(content)


def build_prompt(document: dict[str, Any], source_text: str) -> str:
    source_id = document.get("source_id")
    source_guidance = (
        "For news, focus on product launches, price or rental promotions, "
        "campaigns, negative issues, and company strategy changes."
        if source_id == "naver_news"
        else "For blogs, focus on consumer reactions, comparison criteria, "
        "pros and cons, and rental or purchase experiences."
    )

    return f"""
Extract structured market-observation material for a Korean water purifier
subscription report.
{source_guidance}

Relevance gate:
- Return is_relevant=false when the document's main topic is not the water
  purifier market.
- Brand name or search query alone is not evidence. The title, description, or
  body must contain a real water-purifier signal.
- Exclude documents mainly about other products such as food waste disposers
  (\uc74c\uc2dd\ubb3c\ucc98\ub9ac\uae30/\uc74c\ucc98\uae30), bidets
  (\ube44\ub370), air purifiers (\uacf5\uae30\uccad\uc815\uae30),
  induction ranges, refrigerators, air conditioners, mattresses, massage
  chairs, or robots.
- If a water purifier is mentioned only as background but the actual event is
  another product category, return is_relevant=false.
- Do not infer aggressively from the title alone. Use only facts confirmed in
  the body or description.

Output rules:
- Write summary, key_points, and evidence_excerpt in Korean.
- Use exactly one event_type from this list:
  new_product, price_promotion, marketing_campaign, negative_issue,
  consumer_reaction, corporate_strategy, general_market_reaction
- key_points should contain 1 to 5 concrete facts useful for report writing.
- evidence_excerpt should be a short supporting phrase from the source text.
- mentioned_products should include only product names explicitly confirmed in
  the document.
- If relevance is uncertain, set is_relevant=false or confidence below 0.6.
- Return JSON only. No markdown code fences.

JSON schema:
{{
  "is_relevant": true,
  "event_type": "consumer_reaction",
  "summary": "one Korean sentence",
  "key_points": ["Korean evidence fact"],
  "evidence_excerpt": "short Korean evidence",
  "mentioned_products": [],
  "sentiment": "neutral",
  "confidence": 0.75
}}

Document metadata:
- source_id: {document.get("source_id")}
- brand_name: {document.get("brand_name")}
- query: {document.get("query")}
- title: {document.get("title")}
- published_at: {document.get("published_at")}

Document content:
{source_text}
""".strip()


def parse_json_response(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group())

    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object.")
    return parsed


def normalize_summary(
    summary: dict[str, Any],
    document: dict[str, Any],
    source_text: str,
) -> dict[str, Any]:
    event_type = str(summary.get("event_type") or "").strip()
    if event_type not in ALLOWED_EVENT_TYPES:
        event_type = fallback_event_type(document, source_text)

    sentiment = str(summary.get("sentiment") or "").strip()
    if sentiment not in ALLOWED_SENTIMENTS:
        sentiment = infer_sentiment(source_text)

    confidence = to_float(summary.get("confidence"), default=0.5)
    confidence = min(max(confidence, 0.0), 1.0)

    key_points = filter_clean_water_purifier_items(
        normalize_string_list(summary.get("key_points"))[:5]
    )[:5]
    mentioned_products = filter_clean_water_purifier_items(
        normalize_string_list(summary.get("mentioned_products"))[:10]
    )[:10]
    summary_text = str(summary.get("summary") or "").strip()
    if not summary_text:
        summary_text = build_summary_candidate(source_text, 500)

    evidence_excerpt = str(summary.get("evidence_excerpt") or "").strip()
    if evidence_excerpt and not is_clean_water_purifier_text(evidence_excerpt):
        evidence_excerpt = ""

    llm_relevant = to_bool(summary.get("is_relevant"), default=True)
    market_relevant = is_market_relevant_summary(
        document=document,
        source_text=source_text,
        summary_text=summary_text,
        key_points=key_points,
        evidence_excerpt=evidence_excerpt,
        mentioned_products=mentioned_products,
    )
    if not market_relevant:
        confidence = min(confidence, 0.4)

    return {
        "is_relevant": llm_relevant and market_relevant,
        "market_relevant": market_relevant,
        "event_type": event_type,
        "summary": summary_text,
        "key_points": key_points,
        "evidence_excerpt": evidence_excerpt,
        "mentioned_products": mentioned_products,
        "sentiment": sentiment,
        "confidence": confidence,
    }


def is_market_relevant_summary(
    *,
    document: dict[str, Any],
    source_text: str,
    summary_text: str,
    key_points: list[str],
    evidence_excerpt: str,
    mentioned_products: list[str],
) -> bool:
    summary_is_other_product = has_other_product_signal(summary_text)
    if summary_is_other_product and not is_clean_water_purifier_text(summary_text):
        return False

    return (
        is_clean_water_purifier_text(summary_text)
        or is_clean_water_purifier_text(document.get("title"))
        or bool(key_points)
        or bool(evidence_excerpt)
        or bool(mentioned_products)
        or (not summary_is_other_product and is_water_purifier_market_text(source_text))
    )


def fallback_summary(
    document: dict[str, Any],
    source_text: str,
) -> dict[str, Any]:
    event_type = fallback_event_type(document, source_text)
    summary_text = build_summary_candidate(
        source_text or str(document.get("title") or ""),
        500,
    )
    key_points = filter_clean_water_purifier_items(
        [build_summary_candidate(source_text, 180)] if source_text else []
    )
    market_relevant = is_market_relevant_summary(
        document=document,
        source_text=source_text,
        summary_text=summary_text,
        key_points=key_points,
        evidence_excerpt="",
        mentioned_products=[],
    )
    return {
        "is_relevant": market_relevant,
        "market_relevant": market_relevant,
        "event_type": event_type,
        "summary": summary_text,
        "key_points": key_points,
        "evidence_excerpt": "",
        "mentioned_products": [],
        "sentiment": infer_sentiment(source_text),
        "confidence": 0.35 if market_relevant else 0.1,
    }


def fallback_event_type(document: dict[str, Any], source_text: str) -> str:
    combined = "\n".join(
        [
            str(document.get("title") or ""),
            str(document.get("query") or ""),
            source_text,
        ]
    )
    issue_type, _, _ = classify_issue(combined)
    return issue_type if issue_type in ALLOWED_EVENT_TYPES else "general_market_reaction"


def build_summary_row(
    document: dict[str, Any],
    summary: dict[str, Any],
    *,
    model_name: str,
    prompt_version: str,
    provider: str,
    source_text: str,
    fallback_used: bool,
) -> dict[str, Any]:
    summary_key = "|".join(
        [
            str(document.get("doc_id") or ""),
            str(document.get("content_hash") or ""),
            model_name,
            prompt_version,
        ]
    )
    metadata = parse_json(document.get("metadata_json"))
    metadata.update(
        {
            "event_type": summary["event_type"],
            "sentiment": summary["sentiment"],
            "market_relevant": summary.get("market_relevant"),
            "provider": provider,
            "fallback_used": fallback_used,
            "source_text_chars": len(source_text),
        }
    )

    return {
        "summary_id": f"summary_{make_hash(summary_key)[:16]}",
        "doc_id": document.get("doc_id"),
        "content_hash": document.get("content_hash"),
        "source_id": document.get("source_id"),
        "brand_id": document.get("brand_id"),
        "brand_name": document.get("brand_name"),
        "title": document.get("title"),
        "source_url": document.get("url"),
        "published_at": document.get("published_at"),
        "is_relevant": summary["is_relevant"],
        "summary": summary["summary"],
        "key_points_json": summary["key_points"],
        "evidence_excerpt": summary["evidence_excerpt"],
        "mentioned_products_json": summary["mentioned_products"],
        "confidence": summary["confidence"],
        "model_name": model_name,
        "prompt_version": prompt_version,
        "created_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "metadata_json": metadata,
    }


def normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []

    result = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def to_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "1"}:
            return True
        if normalized in {"false", "no", "n", "0"}:
            return False
    return default
