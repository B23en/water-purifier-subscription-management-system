from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any
import json
import re

import duckdb


ISSUE_KEYWORDS = {
    "new_product": [
        "신제품",
        "출시",
        "공개",
        "론칭",
        "선보",
        "신규",
        "라인업",
    ],
    "price_promotion": [
        "가격",
        "렌탈료",
        "할인",
        "프로모션",
        "이벤트",
        "혜택",
        "캐시백",
        "페스티벌",
        "기획전",
        "특가",
        "쿠폰",
    ],
    "marketing_campaign": [
        "광고",
        "캠페인",
        "브랜드",
        "모델",
        "박람회",
        "전시",
        "팝업",
    ],
    "negative_issue": [
        "리콜",
        "품질",
        "누수",
        "불만",
        "고장",
        "위약금",
        "과징금",
        "소송",
        "논란",
        "피해",
    ],
    "consumer_reaction": [
        "후기",
        "추천",
        "비교",
        "AS",
        "A/S",
        "필터",
        "설치",
        "관리",
        "사용자",
        "소비자",
    ],
}

POSITIVE_KEYWORDS = [
    "성장",
    "확대",
    "증가",
    "인기",
    "호평",
    "기대",
    "강화",
    "수상",
    "1위",
]

NEGATIVE_KEYWORDS = [
    "감소",
    "하락",
    "부진",
    "논란",
    "불만",
    "리콜",
    "피해",
    "소송",
    "과징금",
    "누수",
]


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


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def parse_json_list(value: str | None) -> list[Any]:
    if not value:
        return []

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        items = parsed.get("items")
        return items if isinstance(items, list) else []
    return []


def read_text(text_path: str | None, max_chars: int) -> str:
    if not text_path:
        return ""

    path = Path(text_path)
    if not path.exists():
        return ""

    text = path.read_text(encoding="utf-8", errors="ignore")
    return text[:max_chars]


def extract_section(text: str, section_name: str) -> str:
    marker = f"{section_name}:"
    start = text.find(marker)
    if start < 0:
        return ""

    start += len(marker)
    next_section_match = re.search(r"\n[a-zA-Z_]+:\n", text[start:])
    end = start + next_section_match.start() if next_section_match else len(text)
    return text[start:end].strip()


def remove_export_labels(text: str) -> str:
    ignored_prefixes = (
        "published_at:",
        "url:",
        "blogger:",
        "description:",
        "article_text:",
        "blog_text:",
    )
    cleaned_lines = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith(ignored_prefixes):
            continue
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def source_body_sections(source_id: str | None) -> tuple[str, ...]:
    if source_id == "naver_blog":
        return ("blog_text", "article_text")
    if source_id == "naver_news":
        return ("article_text", "blog_text")
    return ("article_text", "blog_text")


def build_compact_source_text(text: str, source_id: str | None = None) -> str:
    for section_name in source_body_sections(source_id):
        section_text = extract_section(text, section_name)
        if section_text:
            return remove_export_labels(section_text)

    description = extract_section(text, "description")
    source_text = description or text
    return remove_export_labels(source_text)


def clip_text(text: str, max_chars: int) -> str:
    normalized = text.strip()
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "..."


def content_extract_status(metadata: dict[str, Any]) -> dict[str, Any]:
    extract_success = (
        metadata.get("article_extract_success")
        if metadata.get("article_extract_success") is not None
        else metadata.get("body_extract_success")
    )
    text_length = metadata.get("article_text_length")
    if text_length is None:
        text_length = metadata.get("body_text_length")

    return {
        "extract_success": extract_success,
        "text_length": text_length,
        "html_path": metadata.get("article_html_path") or metadata.get("body_html_path"),
    }


def split_sentences(text: str) -> list[str]:
    normalized = normalize_space(text)
    if not normalized:
        return []

    sentences = re.split(r"(?<=[.!?。！？]|[다요음함됨임])\s+", normalized)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def context_keywords() -> list[str]:
    keywords = {
        "정수기",
        "렌탈",
        "구독",
        "구매",
        "가격",
        "렌탈료",
        "할인",
        "프로모션",
        "이벤트",
        "신제품",
        "출시",
        "리콜",
        "품질",
        "필터",
        "설치",
        "관리",
    }
    for values in ISSUE_KEYWORDS.values():
        keywords.update(values)

    return sorted(keywords, key=len, reverse=True)


def build_relevant_excerpt(text: str, max_chars: int) -> str:
    normalized = normalize_space(text)
    if not normalized:
        return ""

    keywords = context_keywords()
    selected = []
    for sentence in split_sentences(normalized):
        if any(keyword.lower() in sentence.lower() for keyword in keywords):
            selected.append(sentence)

        candidate = normalize_space(" ".join(selected))
        if len(candidate) >= max_chars:
            return candidate[:max_chars].rstrip() + "..."

    if selected:
        return build_summary_candidate(" ".join(selected), max_chars)

    return build_summary_candidate(normalized, max_chars)


def find_keywords(text: str, keywords: list[str]) -> list[str]:
    lowered = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in lowered]


def classify_issue(text: str) -> tuple[str, list[str], int]:
    matches_by_type = {
        issue_type: find_keywords(text, keywords)
        for issue_type, keywords in ISSUE_KEYWORDS.items()
    }
    issue_type, matched_keywords = max(
        matches_by_type.items(),
        key=lambda item: len(item[1]),
    )

    score = sum(len(matches) for matches in matches_by_type.values())
    if not matched_keywords:
        issue_type = "general_market_reaction"

    all_keywords = sorted(
        {
            keyword
            for matches in matches_by_type.values()
            for keyword in matches
        }
    )
    return issue_type, all_keywords, score


def infer_sentiment(text: str) -> str:
    positive_count = len(find_keywords(text, POSITIVE_KEYWORDS))
    negative_count = len(find_keywords(text, NEGATIVE_KEYWORDS))

    if positive_count > negative_count:
        return "positive"
    if negative_count > positive_count:
        return "negative"
    return "neutral"


def build_summary_candidate(text: str, max_chars: int = 500) -> str:
    normalized = normalize_space(text)
    if len(normalized) <= max_chars:
        return normalized

    return normalized[:max_chars].rstrip() + "..."


def load_monthly_documents(
    db_path: Path,
    *,
    month: str,
    source_id: str | None = None,
    brand_id: str | None = None,
) -> list[dict[str, Any]]:
    start_date, end_date = parse_month(month)
    where_clauses = [
        "COALESCE(published_at, crawled_at) >= ?",
        "COALESCE(published_at, crawled_at) < ?",
    ]
    params: list[Any] = [
        f"{start_date.isoformat()} 00:00:00",
        f"{end_date.isoformat()} 00:00:00",
    ]

    if source_id:
        where_clauses.append("source_id = ?")
        params.append(source_id)

    if brand_id:
        where_clauses.append("brand_id = ?")
        params.append(brand_id)

    query = f"""
        SELECT
            doc_id,
            source_id,
            source_type,
            query,
            brand_id,
            brand_name,
            title,
            url,
            CAST(published_at AS VARCHAR) AS published_at,
            CAST(crawled_at AS VARCHAR) AS crawled_at,
            raw_path,
            text_path,
            content_hash,
            url_hash,
            metadata_json
        FROM raw_documents
        WHERE {" AND ".join(where_clauses)}
        ORDER BY COALESCE(published_at, crawled_at) DESC
    """

    with duckdb.connect(str(db_path)) as connection:
        cursor = connection.execute(query, params)
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()

    return [dict(zip(columns, row)) for row in rows]


def load_monthly_summaries(
    db_path: Path,
    *,
    month: str,
    source_id: str | None = None,
    brand_id: str | None = None,
) -> list[dict[str, Any]]:
    start_date, end_date = parse_month(month)
    where_clauses = [
        "COALESCE(published_at, created_at) >= ?",
        "COALESCE(published_at, created_at) < ?",
    ]
    params: list[Any] = [
        f"{start_date.isoformat()} 00:00:00",
        f"{end_date.isoformat()} 00:00:00",
    ]

    if source_id:
        where_clauses.append("source_id = ?")
        params.append(source_id)

    if brand_id:
        where_clauses.append("brand_id = ?")
        params.append(brand_id)

    query = f"""
        SELECT
            summary_id,
            doc_id,
            content_hash,
            source_id,
            brand_id,
            brand_name,
            title,
            source_url,
            CAST(published_at AS VARCHAR) AS published_at,
            is_relevant,
            summary,
            key_points_json,
            evidence_excerpt,
            mentioned_products_json,
            confidence,
            model_name,
            prompt_version,
            CAST(created_at AS VARCHAR) AS created_at,
            metadata_json
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY doc_id, content_hash
                    ORDER BY created_at DESC, prompt_version DESC
                ) AS summary_rank
            FROM document_summaries
            WHERE {" AND ".join(where_clauses)}
        ) ranked_summaries
        WHERE summary_rank = 1
          AND COALESCE(is_relevant, TRUE) = TRUE
        ORDER BY COALESCE(published_at, created_at) DESC
    """

    with duckdb.connect(str(db_path)) as connection:
        cursor = connection.execute(query, params)
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()

    return [dict(zip(columns, row)) for row in rows]


def build_issue(
    document: dict[str, Any],
    *,
    evidence_text: str,
    max_summary_chars: int,
) -> dict[str, Any]:
    metadata = parse_json(document.get("metadata_json"))
    extract_status = content_extract_status(metadata)
    combined_text = "\n".join(
        [
            str(document.get("title") or ""),
            str(document.get("query") or ""),
            evidence_text,
        ]
    )
    issue_type, matched_keywords, score = classify_issue(combined_text)
    event_timestamp = document.get("published_at") or document.get("crawled_at")
    event_date = str(event_timestamp or "")[:10] or None

    return {
        "issue_id": f"issue_{document.get('url_hash', '')[:16]}",
        "event_date": event_date,
        "brand_id": document.get("brand_id"),
        "brand_name": document.get("brand_name"),
        "issue_type": issue_type,
        "sentiment": infer_sentiment(combined_text),
        "relevance_score": score,
        "matched_keywords": matched_keywords,
        "title": document.get("title"),
        "summary_candidate": build_summary_candidate(
            evidence_text or str(document.get("title") or ""),
            max_summary_chars,
        ),
        "evidence": {
            "source_id": document.get("source_id"),
            "source_type": document.get("source_type"),
            "query": document.get("query"),
            "published_at": document.get("published_at"),
            "crawled_at": document.get("crawled_at"),
            "url": document.get("url"),
            "raw_path": document.get("raw_path"),
            "text_path": document.get("text_path"),
            "extract_success": extract_status["extract_success"],
            "extract_text_length": extract_status["text_length"],
            "extract_html_path": extract_status["html_path"],
            "article_extract_success": metadata.get("article_extract_success"),
            "article_text_length": metadata.get("article_text_length"),
            "blog_extract_success": metadata.get("body_extract_success"),
            "blog_text_length": metadata.get("body_text_length"),
        },
        "evidence_text": evidence_text,
    }


def build_compact_document(
    document: dict[str, Any],
    *,
    excerpt_chars: int,
) -> dict[str, Any]:
    text = read_text(document.get("text_path"), max(excerpt_chars * 20, 10000))
    source_text = build_compact_source_text(
        text,
        source_id=document.get("source_id"),
    )
    metadata = parse_json(document.get("metadata_json"))
    extract_status = content_extract_status(metadata)
    event_timestamp = document.get("published_at") or document.get("crawled_at")

    return {
        "date": str(event_timestamp or "")[:10] or None,
        "brand": document.get("brand_name"),
        "title": document.get("title"),
        "excerpt": build_relevant_excerpt(source_text, excerpt_chars),
        "url": document.get("url"),
        "source": document.get("source_id"),
        "extract_success": extract_status["extract_success"],
        "extract_text_length": extract_status["text_length"],
        "article_extract_success": metadata.get("article_extract_success"),
        "blog_extract_success": metadata.get("body_extract_success"),
    }


def build_summary_document(summary: dict[str, Any]) -> dict[str, Any]:
    event_timestamp = summary.get("published_at") or summary.get("created_at")
    metadata = parse_json(summary.get("metadata_json"))

    return {
        "summary_id": summary.get("summary_id"),
        "doc_id": summary.get("doc_id"),
        "date": str(event_timestamp or "")[:10] or None,
        "brand_id": summary.get("brand_id"),
        "brand": summary.get("brand_name"),
        "title": summary.get("title"),
        "event_type": metadata.get("event_type"),
        "summary": summary.get("summary"),
        "key_points": parse_json_list(summary.get("key_points_json")),
        "evidence_excerpt": summary.get("evidence_excerpt"),
        "mentioned_products": parse_json_list(
            summary.get("mentioned_products_json")
        ),
        "sentiment": metadata.get("sentiment"),
        "confidence": summary.get("confidence"),
        "url": summary.get("source_url"),
        "source": summary.get("source_id"),
        "summary_model": summary.get("model_name"),
        "prompt_version": summary.get("prompt_version"),
    }


def export_monthly_issues(
    db_path: Path,
    *,
    month: str,
    mode: str = "compact",
    source_id: str | None = None,
    brand_id: str | None = None,
    limit: int = 30,
    min_score: int = 1,
    max_evidence_chars: int = 1200,
    max_summary_chars: int = 500,
    excerpt_chars: int = 400,
) -> dict[str, Any]:
    if mode not in {"full", "compact", "summary"}:
        raise ValueError("mode must be one of: full, compact, summary.")

    start_date, end_date = parse_month(month)
    common = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "period": {
            "month": month,
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
        },
        "mode": mode,
        "source": "web_crawler",
        "filters": {
            "source_id": source_id,
            "brand_id": brand_id,
            "limit": limit,
            "min_score": min_score,
        },
    }

    if mode == "summary":
        summaries = load_monthly_summaries(
            db_path,
            month=month,
            source_id=source_id,
            brand_id=brand_id,
        )
        documents = [build_summary_document(summary) for summary in summaries]
        if limit > 0:
            documents = documents[:limit]

        return {
            **common,
            "stats": {
                "summary_count": len(summaries),
                "document_count": len(documents),
            },
            "documents": documents,
        }

    raw_documents = load_monthly_documents(
        db_path,
        month=month,
        source_id=source_id,
        brand_id=brand_id,
    )

    if mode == "compact":
        documents = [
            build_compact_document(document, excerpt_chars=excerpt_chars)
            for document in raw_documents
        ]
        if limit > 0:
            documents = documents[:limit]

        return {
            **common,
            "filters": {
                **common["filters"],
                "excerpt_chars": excerpt_chars,
            },
            "stats": {
                "document_count": len(raw_documents),
                "exported_count": len(documents),
            },
            "documents": documents,
        }

    issues = []
    for document in raw_documents:
        document_text = read_text(
            document.get("text_path"),
            max(max_evidence_chars * 20, 10000),
        )
        evidence_text = clip_text(
            build_compact_source_text(
                document_text,
                source_id=document.get("source_id"),
            ),
            max_evidence_chars,
        )
        issue = build_issue(
            document,
            evidence_text=evidence_text,
            max_summary_chars=max_summary_chars,
        )
        if issue["relevance_score"] < min_score:
            continue
        issues.append(issue)

    issues.sort(
        key=lambda issue: (
            issue["relevance_score"],
            issue["event_date"] or "",
        ),
        reverse=True,
    )

    if limit > 0:
        issues = issues[:limit]

    return {
        **common,
        "filters": {
            **common["filters"],
            "max_evidence_chars": max_evidence_chars,
        },
        "stats": {
            "document_count": len(raw_documents),
            "issue_count": len(issues),
        },
        "issues": issues,
    }
