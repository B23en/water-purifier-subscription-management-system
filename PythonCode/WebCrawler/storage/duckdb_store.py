from pathlib import Path
from typing import Any
import hashlib
import duckdb
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "n_media",
    "n_query",
    "n_rank",
}

def init_db(db_path: Path, schema_path: Path) -> Path:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    sql_schema = schema_path.read_text(encoding="utf-8")

    with duckdb.connect(str(db_path)) as connection:
        connection.execute(sql_schema)

    return db_path

def make_hash(value: str) -> str:
    normalized = " ".join(str(value).strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def normalize_url(url: str) -> str:
    parsed = urlsplit(str(url).strip())
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    query_params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(sorted(query_params), doseq=True)

    return urlunsplit((scheme, netloc, parsed.path, query, ""))

def is_doc_exists(db_path: Path, url_hash: str) -> bool:
    with duckdb.connect(str(db_path)) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM raw_documents
            WHERE url_hash = ?
            LIMIT 1
            """,
            [url_hash],
        ).fetchone()

    return row is not None


def update_raw_doc_content(
    db_path: Path,
    *,
    url_hash: str,
    raw_path: str,
    text_path: str,
    content_hash: str,
    crawled_at: str,
    metadata_json: dict[str, Any] | list[Any] | str | None,
) -> bool:
    if isinstance(metadata_json, (dict, list)):
        metadata_json = json.dumps(metadata_json, ensure_ascii=False)

    with duckdb.connect(str(db_path)) as connection:
        existing = connection.execute(
            """
            SELECT 1
            FROM raw_documents
            WHERE url_hash = ?
            LIMIT 1
            """,
            [url_hash],
        ).fetchone()

        if existing is None:
            return False

        connection.execute(
            """
            UPDATE raw_documents
            SET
                raw_path = ?,
                text_path = ?,
                content_hash = ?,
                crawled_at = ?,
                metadata_json = ?
            WHERE url_hash = ?
            """,
            [
                raw_path,
                text_path,
                content_hash,
                crawled_at,
                metadata_json,
                url_hash,
            ],
        )

    return True


def upsert_product_snapshot(db_path: Path, snapshot: dict[str, Any]) -> bool:
    snapshot_id = snapshot.get("snapshot_id")
    if not snapshot_id:
        raise ValueError("snapshot['snapshot_id'] is required")

    source_id = snapshot.get("source_id")
    if not source_id:
        raise ValueError("snapshot['source_id'] is required")

    brand_id = snapshot.get("brand_id")
    if not brand_id:
        raise ValueError("snapshot['brand_id'] is required")

    brand_name = snapshot.get("brand_name")
    if not brand_name:
        raise ValueError("snapshot['brand_name'] is required")

    product_name = snapshot.get("product_name")
    if not product_name:
        raise ValueError("snapshot['product_name'] is required")

    captured_date = snapshot.get("captured_date")
    if not captured_date:
        raise ValueError("snapshot['captured_date'] is required")

    captured_at = snapshot.get("captured_at")
    if not captured_at:
        raise ValueError("snapshot['captured_at'] is required")

    metadata_json = snapshot.get("metadata_json")
    if isinstance(metadata_json, (dict, list)):
        metadata_json = json.dumps(metadata_json, ensure_ascii=False)

    values = [
        snapshot_id,
        source_id,
        brand_id,
        brand_name,
        product_name,
        snapshot.get("model_code"),
        snapshot.get("category"),
        snapshot.get("sales_type"),
        snapshot.get("purchase_price"),
        snapshot.get("rental_fee"),
        snapshot.get("original_rental_fee"),
        snapshot.get("promotion_text"),
        snapshot.get("rating"),
        snapshot.get("review_count"),
        snapshot.get("product_url"),
        captured_date,
        captured_at,
        snapshot.get("raw_path"),
        snapshot.get("content_hash"),
        metadata_json,
    ]

    with duckdb.connect(str(db_path)) as connection:
        exists = connection.execute(
            """
            SELECT 1
            FROM product_snapshots
            WHERE snapshot_id = ?
            LIMIT 1
            """,
            [snapshot_id],
        ).fetchone()

        if exists:
            connection.execute(
                """
                UPDATE product_snapshots
                SET
                    source_id = ?,
                    brand_id = ?,
                    brand_name = ?,
                    product_name = ?,
                    model_code = ?,
                    category = ?,
                    sales_type = ?,
                    purchase_price = ?,
                    rental_fee = ?,
                    original_rental_fee = ?,
                    promotion_text = ?,
                    rating = ?,
                    review_count = ?,
                    product_url = ?,
                    captured_date = ?,
                    captured_at = ?,
                    raw_path = ?,
                    content_hash = ?,
                    metadata_json = ?
                WHERE snapshot_id = ?
                """,
                values[1:] + [snapshot_id],
            )
            return False

        connection.execute(
            """
            INSERT INTO product_snapshots (
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
                captured_date,
                captured_at,
                raw_path,
                content_hash,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )

    return True


def upsert_document_summary(db_path: Path, summary: dict[str, Any]) -> bool:
    summary_id = summary.get("summary_id")
    if not summary_id:
        raise ValueError("summary['summary_id'] is required")

    doc_id = summary.get("doc_id")
    if not doc_id:
        raise ValueError("summary['doc_id'] is required")

    content_hash = summary.get("content_hash")
    if not content_hash:
        raise ValueError("summary['content_hash'] is required")

    source_id = summary.get("source_id")
    if not source_id:
        raise ValueError("summary['source_id'] is required")

    model_name = summary.get("model_name")
    if not model_name:
        raise ValueError("summary['model_name'] is required")

    prompt_version = summary.get("prompt_version")
    if not prompt_version:
        raise ValueError("summary['prompt_version'] is required")

    created_at = summary.get("created_at")
    if not created_at:
        raise ValueError("summary['created_at'] is required")

    key_points_json = summary.get("key_points_json")
    if isinstance(key_points_json, (dict, list)):
        key_points_json = json.dumps(key_points_json, ensure_ascii=False)

    mentioned_products_json = summary.get("mentioned_products_json")
    if isinstance(mentioned_products_json, (dict, list)):
        mentioned_products_json = json.dumps(
            mentioned_products_json,
            ensure_ascii=False,
        )

    metadata_json = summary.get("metadata_json")
    if isinstance(metadata_json, (dict, list)):
        metadata_json = json.dumps(metadata_json, ensure_ascii=False)

    values = [
        summary_id,
        doc_id,
        content_hash,
        source_id,
        summary.get("brand_id"),
        summary.get("brand_name"),
        summary.get("title"),
        summary.get("source_url"),
        summary.get("published_at"),
        summary.get("is_relevant"),
        summary.get("summary"),
        key_points_json,
        summary.get("evidence_excerpt"),
        mentioned_products_json,
        summary.get("confidence"),
        model_name,
        prompt_version,
        created_at,
        metadata_json,
    ]

    with duckdb.connect(str(db_path)) as connection:
        exists = connection.execute(
            """
            SELECT 1
            FROM document_summaries
            WHERE
                doc_id = ?
                AND content_hash = ?
                AND model_name = ?
                AND prompt_version = ?
            LIMIT 1
            """,
            [doc_id, content_hash, model_name, prompt_version],
        ).fetchone()

        if exists:
            connection.execute(
                """
                UPDATE document_summaries
                SET
                    summary_id = ?,
                    source_id = ?,
                    brand_id = ?,
                    brand_name = ?,
                    title = ?,
                    source_url = ?,
                    published_at = ?,
                    is_relevant = ?,
                    summary = ?,
                    key_points_json = ?,
                    evidence_excerpt = ?,
                    mentioned_products_json = ?,
                    confidence = ?,
                    created_at = ?,
                    metadata_json = ?
                WHERE
                    doc_id = ?
                    AND content_hash = ?
                    AND model_name = ?
                    AND prompt_version = ?
                """,
                [
                    summary_id,
                    source_id,
                    summary.get("brand_id"),
                    summary.get("brand_name"),
                    summary.get("title"),
                    summary.get("source_url"),
                    summary.get("published_at"),
                    summary.get("is_relevant"),
                    summary.get("summary"),
                    key_points_json,
                    summary.get("evidence_excerpt"),
                    mentioned_products_json,
                    summary.get("confidence"),
                    created_at,
                    metadata_json,
                    doc_id,
                    content_hash,
                    model_name,
                    prompt_version,
                ],
            )
            return False

        connection.execute(
            """
            INSERT INTO document_summaries (
                summary_id,
                doc_id,
                content_hash,
                source_id,
                brand_id,
                brand_name,
                title,
                source_url,
                published_at,
                is_relevant,
                summary,
                key_points_json,
                evidence_excerpt,
                mentioned_products_json,
                confidence,
                model_name,
                prompt_version,
                created_at,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )

    return True


def insert_raw_doc(db_path: Path, document: dict[str, Any]) -> bool:
    doc_id = document.get("doc_id")
    if not doc_id:
        raise ValueError("document['doc_id'] is required")

    source_id = document.get("source_id")
    if not source_id:
        raise ValueError("document['source_id'] is required")

    url = document.get("url")
    if not url:
        raise ValueError("document['url'] is required")

    crawled_at = document.get("crawled_at")
    if not crawled_at:
        raise ValueError("document['crawled_at'] is required")

    normalized_url = normalize_url(url)
    url_hash = document.get("url_hash") or make_hash(normalized_url)
    if is_doc_exists(db_path, url_hash):
        return False

    metadata_json = document.get("metadata_json")
    if isinstance(metadata_json, (dict, list)):
        metadata_json = json.dumps(metadata_json, ensure_ascii=False)

    with duckdb.connect(str(db_path)) as connection:
        connection.execute(
            """
            INSERT INTO raw_documents (
                doc_id,
                run_id,
                source_id,
                source_type,
                query,
                brand_id,
                brand_name,
                title,
                url,
                published_at,
                crawled_at,
                raw_path,
                text_path,
                content_hash,
                url_hash,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                doc_id,
                document.get("run_id"),
                source_id,
                document.get("source_type"),
                document.get("query"),
                document.get("brand_id"),
                document.get("brand_name"),
                document.get("title"),
                normalized_url,
                document.get("published_at"),
                crawled_at,
                document.get("raw_path"),
                document.get("text_path"),
                document.get("content_hash"),
                url_hash,
                metadata_json,
            ],
        )

    return True
