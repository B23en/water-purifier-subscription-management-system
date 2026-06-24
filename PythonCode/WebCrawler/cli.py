from datetime import datetime
from pathlib import Path
from typing import Any
import argparse
import json
import os

from .config import (
    DUCKDB_PATH,
    EXPORT_DIR,
    PROJECT_ROOT,
    SCHEMA_PATH,
    WEB_CRAWL_DB_DIR,
    load_targets,
)
from .storage.duckdb_store import (
    init_db,
    insert_raw_doc,
    is_doc_exists,
    make_hash,
    normalize_url,
    update_raw_doc_content,
)
from .storage.raw_store import save_raw_json, save_raw_text
from .query_builder import build_queries

DEFAULT_TARGETS_PATH = Path(__file__).resolve().parent / "targets.yaml"


def load_env_files() -> None:
    env_paths = [
        PROJECT_ROOT / ".env",
        PROJECT_ROOT / "PythonCode" / ".env",
    ]

    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None

    for env_path in env_paths:
        if not env_path.exists():
            continue

        if load_dotenv:
            load_dotenv(env_path, override=False)
        else:
            load_env_file_without_dotenv(env_path)


def load_env_file_without_dotenv(env_path: Path) -> None:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def list_sources(targets: dict) -> None:
    for source_id, source in targets.get("sources", {}).items():
        print(
            f"{source_id}\t"
            f"enabled={source.get('enabled', False)}\t"
            f"type={source.get('type')}\t"
            f"cadence={source.get('cadence')}"
        )

def list_queries(targets: dict, source_id: str, limit: int | None) -> None:
    queries = build_queries(targets, source_id)

    print(f"source={source_id}")
    print(f"query_count={len(queries)}")

    rows = queries[:limit] if limit else queries
    for idx, item in enumerate(rows, start=1):
        brand = item.get("brand_name") or "-"
        query = item.get("query")
        print(f"{idx:03d}\t[{brand}]\t{query}")


def format_timestamp_for_duckdb(value: str | None) -> str | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value

    return parsed.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def build_news_text(item: dict[str, Any], article_text: str | None) -> str:
    lines = [
        item.get("title") or "",
        "",
        f"published_at: {item.get('published_at') or ''}",
        f"url: {item.get('url') or ''}",
        "",
        "description:",
        item.get("description") or "",
    ]

    if article_text:
        lines.extend(["", "article_text:", article_text])

    return "\n".join(lines).strip() + "\n"


def crawl_naver_news(
    targets: dict,
    *,
    limit_queries: int,
    display: int,
    sort: str,
    fetch_article: bool,
    article_limit_per_query: int,
    timeout: int,
) -> None:
    from .sources.naver_news import fetch_news_items

    article_fetcher = None
    if fetch_article:
        from .sources import article_fetcher as loaded_article_fetcher

        article_fetcher = loaded_article_fetcher

    init_db(DUCKDB_PATH, SCHEMA_PATH)

    queries = build_queries(targets, "naver_news")
    if limit_queries > 0:
        queries = queries[:limit_queries]

    run_id = f"naver_news-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    crawl_date = datetime.now().strftime("%Y-%m-%d")
    save_dir = WEB_CRAWL_DB_DIR / "raw" / "naver_news" / crawl_date

    fetched_count = 0
    saved_count = 0
    updated_count = 0
    duplicate_count = 0
    error_count = 0

    print(
        f"crawl start: source=naver_news, queries={len(queries)}, "
        f"display={display}, fetch_article={fetch_article}"
    )

    for query_index, query_item in enumerate(queries, start=1):
        query = query_item["query"]
        print(f"[{query_index}/{len(queries)}] query={query}")

        try:
            items = fetch_news_items(
                query,
                display=display,
                sort=sort,
                timeout=timeout,
            )
        except Exception as exc:
            error_count += 1
            print(f"  error: {type(exc).__name__}: {exc}")
            continue

        fetched_count += len(items)

        for item_index, item in enumerate(items, start=1):
            url = item.get("url")
            if not url:
                error_count += 1
                print("  skip: missing url")
                continue

            normalized_url = normalize_url(url)
            url_hash = make_hash(normalized_url)
            should_fetch_article = (
                fetch_article
                and article_fetcher is not None
                and item_index <= article_limit_per_query
            )
            doc_exists = is_doc_exists(DUCKDB_PATH, url_hash)
            if doc_exists and not should_fetch_article:
                duplicate_count += 1
                continue

            article_response = None
            article_text = None
            article_error = None

            if should_fetch_article:
                try:
                    article_response = article_fetcher.fetch_article_html(
                        url,
                        timeout=timeout,
                    )
                    if article_response.get("status_code") == 200:
                        article_text = article_fetcher.extract_article_text(
                            article_response.get("html") or "",
                            article_response.get("final_url") or url,
                        )
                except Exception as exc:
                    article_error = f"{type(exc).__name__}: {exc}"

            text = build_news_text(item, article_text)
            doc_id = f"naver_news_{url_hash[:16]}"
            metadata = {
                "normalized_url": normalized_url,
                "original_url": item.get("original_url"),
                "naver_url": item.get("naver_url"),
                "article_requested": should_fetch_article,
                "article_status_code": (
                    article_response or {}
                ).get("status_code"),
                "article_content_type": (
                    article_response or {}
                ).get("content_type"),
                "article_final_url": (
                    article_response or {}
                ).get("final_url"),
                "article_extract_success": bool(article_text),
                "article_text_length": len(article_text or ""),
                "article_error": article_error,
            }
            raw_path = save_raw_json(
                save_dir / f"{doc_id}.json",
                {
                    "source_id": "naver_news",
                    "source_type": "api",
                    "run_id": run_id,
                    "query": query,
                    "brand_id": query_item.get("brand_id"),
                    "brand_name": query_item.get("brand_name"),
                    "fetched_at": item.get("fetched_at"),
                    "search_item": item,
                    "article": article_response,
                    "article_text": article_text,
                    "article_extract_success": bool(article_text),
                    "article_error": article_error,
                },
            )
            text_path = save_raw_text(save_dir / f"{doc_id}.txt", text)
            content_hash = make_hash(text)
            crawled_at = datetime.now().isoformat(
                sep=" ",
                timespec="seconds",
            )

            if doc_exists:
                updated = update_raw_doc_content(
                    DUCKDB_PATH,
                    url_hash=url_hash,
                    raw_path=raw_path,
                    text_path=text_path,
                    content_hash=content_hash,
                    crawled_at=crawled_at,
                    metadata_json=metadata,
                )
                if updated:
                    updated_count += 1
                    print(f"  updated: {item.get('title')}")
                else:
                    error_count += 1
                    print(f"  update failed: {item.get('title')}")
                continue

            inserted = insert_raw_doc(
                DUCKDB_PATH,
                {
                    "doc_id": doc_id,
                    "run_id": run_id,
                    "source_id": "naver_news",
                    "source_type": "api",
                    "query": query,
                    "brand_id": query_item.get("brand_id"),
                    "brand_name": query_item.get("brand_name"),
                    "title": item.get("title"),
                    "url": url,
                    "published_at": format_timestamp_for_duckdb(
                        item.get("published_at")
                    ),
                    "crawled_at": crawled_at,
                    "raw_path": raw_path,
                    "text_path": text_path,
                    "content_hash": content_hash,
                    "url_hash": url_hash,
                    "metadata_json": metadata,
                },
            )

            if inserted:
                saved_count += 1
                print(f"  saved: {item.get('title')}")
            else:
                duplicate_count += 1

    print(
        "crawl finished: "
        f"fetched={fetched_count}, saved={saved_count}, updated={updated_count}, "
        f"duplicates={duplicate_count}, errors={error_count}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Web crawler CLI")
    parser.add_argument(
        "--targets",
        default=str(DEFAULT_TARGETS_PATH),
        help="Path to targets.yaml",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-sources")

    list_queries_parser = subparsers.add_parser("list-queries")
    list_queries_parser.add_argument("--source", required=True)
    list_queries_parser.add_argument("--limit", type=int, default=None)

    subparsers.add_parser("init-db")

    crawl_parser = subparsers.add_parser("crawl")
    crawl_parser.add_argument("--source", required=True, choices=["naver_news"])
    crawl_parser.add_argument("--limit-queries", type=int, default=1)
    crawl_parser.add_argument("--display", type=int, default=10)
    crawl_parser.add_argument("--sort", choices=["sim", "date"], default="date")
    crawl_parser.add_argument("--fetch-article", action="store_true")
    crawl_parser.add_argument("--article-limit-per-query", type=int, default=3)
    crawl_parser.add_argument("--timeout", type=int, default=10)

    export_parser = subparsers.add_parser("export-issues")
    export_parser.add_argument("--month", required=True, help="YYYY-MM")
    export_parser.add_argument(
        "--mode",
        choices=["compact", "full", "summary"],
        default="compact",
    )
    export_parser.add_argument("--source", default=None)
    export_parser.add_argument("--brand-id", default=None)
    export_parser.add_argument("--limit", type=int, default=30)
    export_parser.add_argument("--min-score", type=int, default=1)
    export_parser.add_argument("--max-evidence-chars", type=int, default=1200)
    export_parser.add_argument("--excerpt-chars", type=int, default=400)
    export_parser.add_argument("--output", default=None)

    args = parser.parse_args()

    if args.command == "list-sources":
        targets = load_targets(Path(args.targets))
        list_sources(targets)
    elif args.command == "list-queries":
        targets = load_targets(Path(args.targets))
        list_queries(targets, args.source, args.limit)
    elif args.command == "init-db":
        db_path = init_db(DUCKDB_PATH, SCHEMA_PATH)
        print(f"DuckDB initialized: {db_path}")
    elif args.command == "crawl":
        load_env_files()
        targets = load_targets(Path(args.targets))
        if args.source == "naver_news":
            crawl_naver_news(
                targets,
                limit_queries=args.limit_queries,
                display=args.display,
                sort=args.sort,
                fetch_article=args.fetch_article,
                article_limit_per_query=args.article_limit_per_query,
                timeout=args.timeout,
            )
    elif args.command == "export-issues":
        from .exporters.issue_exporter import export_monthly_issues

        init_db(DUCKDB_PATH, SCHEMA_PATH)
        package = export_monthly_issues(
            DUCKDB_PATH,
            month=args.month,
            mode=args.mode,
            source_id=args.source,
            brand_id=args.brand_id,
            limit=args.limit,
            min_score=args.min_score,
            max_evidence_chars=args.max_evidence_chars,
            excerpt_chars=args.excerpt_chars,
        )
        output_path = (
            Path(args.output)
            if args.output
            else EXPORT_DIR / f"issues_{args.month}_{args.mode}.json"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(package, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        stats = package["stats"]
        exported_count = (
            stats.get("issue_count")
            or stats.get("exported_count")
            or stats.get("document_count")
            or 0
        )
        source_count = (
            stats.get("document_count")
            or stats.get("summary_count")
            or 0
        )
        print(
            f"Exported {exported_count} items "
            f"from {source_count} source rows: {output_path}"
        )


if __name__ == "__main__":
    main()
