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
