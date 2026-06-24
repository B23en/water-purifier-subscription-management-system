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
    upsert_product_snapshot,
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


def compact_log_text(value: Any, max_chars: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def print_summary_progress(event: dict[str, Any]) -> None:
    phase = event.get("phase")
    stats = event.get("stats") or {}

    if phase == "start":
        print(
            "summarize start: "
            f"month={event.get('month')} "
            f"source={event.get('source_id') or 'all'} "
            f"brand={event.get('brand_id') or 'all'} "
            f"documents={event.get('total', 0)} "
            f"provider={event.get('provider')} "
            f"model={event.get('model')}",
            flush=True,
        )
        return

    if phase == "process":
        print(
            f"[{event.get('index')}/{event.get('total')}] "
            f"summarizing source={event.get('source_id')} "
            f"brand={event.get('brand_name') or '-'} "
            f"chars={event.get('input_chars', 0)} "
            f"title={compact_log_text(event.get('title'))}",
            flush=True,
        )
        return

    if phase == "done":
        action = "inserted" if event.get("inserted") else "updated"
        print(
            "  done: "
            f"{action} "
            f"summarized={stats.get('summarized_count', 0)} "
            f"inserted={stats.get('inserted_count', 0)} "
            f"updated={stats.get('updated_count', 0)} "
            f"errors={stats.get('error_count', 0)}",
            flush=True,
        )
        return

    if phase == "skip":
        print(
            f"[{event.get('index')}/{event.get('total')}] "
            f"skip reason={event.get('reason')} "
            f"source={event.get('source_id')} "
            f"brand={event.get('brand_name') or '-'} "
            f"title={compact_log_text(event.get('title'))}",
            flush=True,
        )
        return

    if phase == "error":
        print(
            "  error: "
            f"doc_id={event.get('doc_id')} "
            f"{event.get('error')}",
            flush=True,
        )


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


def build_blog_text(item: dict[str, Any], blog_text: str | None) -> str:
    lines = [
        item.get("title") or "",
        "",
        f"published_at: {item.get('published_at') or ''}",
        f"url: {item.get('url') or ''}",
        f"blogger: {item.get('blogger_name') or ''}",
        "",
        "description:",
        item.get("description") or "",
    ]

    if blog_text:
        lines.extend(["", "blog_text:", blog_text])

    return "\n".join(lines).strip() + "\n"


def crawl_naver_news(
    targets: dict,
    *,
    limit_queries: int,
    display: int,
    sort: str,
    fetch_article: bool,
    article_limit_per_query: int,
    timeout: int | None,
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


def crawl_naver_blog(
    targets: dict,
    *,
    brand_ids: set[str] | None,
    limit_queries: int,
    display: int | None,
    sort: str | None,
    fetch_blog_body: bool | None,
    blog_body_limit_per_query: int | None,
    timeout: int | None,
) -> None:
    from .sources.naver_blog import (
        build_blog_queries,
        canonicalize_blog_url,
        fetch_blog_items,
        is_relevant_blog_item,
        is_relevant_blog_text,
    )

    init_db(DUCKDB_PATH, SCHEMA_PATH)

    source_settings = targets.get("sources", {}).get("naver_blog", {})
    display_count = display or source_settings.get("display") or 10
    sort_method = sort or source_settings.get("sort") or "date"
    should_fetch_body = (
        fetch_blog_body
        if fetch_blog_body is not None
        else bool(source_settings.get("fetch_body", True))
    )
    blog_fetcher = None
    if should_fetch_body:
        from .sources import naver_blog_fetcher as loaded_blog_fetcher

        blog_fetcher = loaded_blog_fetcher

    body_limit = (
        blog_body_limit_per_query
        or source_settings.get("body_limit_per_query")
        or 5
    )

    queries = build_blog_queries(targets)
    if brand_ids:
        queries = [
            item for item in queries if item.get("brand_id") in brand_ids
        ]
    if limit_queries > 0:
        queries = queries[:limit_queries]

    run_id = f"naver_blog-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    crawl_date = datetime.now().strftime("%Y-%m-%d")
    save_dir = WEB_CRAWL_DB_DIR / "raw" / "naver_blog" / crawl_date

    fetched_count = 0
    saved_count = 0
    updated_count = 0
    duplicate_count = 0
    filtered_count = 0
    error_count = 0
    seen_url_hashes: set[str] = set()

    print(
        f"crawl start: source=naver_blog, queries={len(queries)}, "
        f"display={display_count}, fetch_body={should_fetch_body}"
    )

    for query_index, query_item in enumerate(queries, start=1):
        query = query_item["query"]
        print(f"[{query_index}/{len(queries)}] query={query}")

        try:
            items = fetch_blog_items(
                query,
                display=display_count,
                sort=sort_method,
                timeout=timeout or 10,
            )
        except Exception as exc:
            error_count += 1
            print(f"  error: {type(exc).__name__}: {exc}")
            continue

        fetched_count += len(items)
        filtered_items = [
            item for item in items if is_relevant_blog_item(item)
        ]
        filtered_count += len(items) - len(filtered_items)
        print(
            f"  fetched={len(items)}, filtered={len(items) - len(filtered_items)}, "
            f"candidates={len(filtered_items)}"
        )

        for item_index, item in enumerate(filtered_items, start=1):
            url = item.get("url")
            if not url:
                error_count += 1
                print("  skip: missing url")
                continue

            canonical_url = canonicalize_blog_url(url)
            normalized_url = normalize_url(canonical_url)
            url_hash = make_hash(normalized_url)
            if url_hash in seen_url_hashes:
                duplicate_count += 1
                continue
            seen_url_hashes.add(url_hash)

            should_fetch_this_body = (
                should_fetch_body
                and blog_fetcher is not None
                and item_index <= int(body_limit)
            )
            doc_exists = is_doc_exists(DUCKDB_PATH, url_hash)
            if doc_exists and not should_fetch_this_body:
                duplicate_count += 1
                continue

            blog_response = None
            blog_text = None
            blog_error = None
            if should_fetch_this_body:
                try:
                    blog_response = blog_fetcher.fetch_blog_post(
                        canonical_url,
                        timeout=timeout or 10,
                    )
                    if blog_response.get("status_code") == 200:
                        blog_text = blog_fetcher.extract_blog_text(
                            blog_response.get("html") or "",
                            url=blog_response.get("final_url") or url,
                        )
                        if blog_text and not is_relevant_blog_text(blog_text):
                            filtered_count += 1
                            print(f"  filtered body: {item.get('title')}")
                            continue
                except Exception as exc:
                    blog_error = f"{type(exc).__name__}: {exc}"

            text = build_blog_text(item, blog_text)
            doc_id = f"naver_blog_{url_hash[:16]}"
            text_file_path = save_dir / f"{doc_id}.txt"
            blog_html_path = None
            blog_payload = None
            if blog_response is not None:
                html = blog_response.get("html") or ""
                if html:
                    blog_html_path = save_raw_text(
                        save_dir / f"{doc_id}.html.txt",
                        html,
                    )
                blog_payload = {
                    "request_url": blog_response.get("request_url"),
                    "normalized_url": blog_response.get("normalized_url"),
                    "final_url": blog_response.get("final_url"),
                    "status_code": blog_response.get("status_code"),
                    "content_type": blog_response.get("content_type"),
                    "html_path": blog_html_path,
                    "html_length": len(html),
                }

            metadata = {
                "normalized_url": normalized_url,
                "canonical_url": canonical_url,
                "blogger_name": item.get("blogger_name"),
                "blogger_link": item.get("blogger_link"),
                "description": item.get("description"),
                "body_requested": should_fetch_this_body,
                "body_status_code": (blog_response or {}).get("status_code"),
                "body_content_type": (blog_response or {}).get("content_type"),
                "body_final_url": (blog_response or {}).get("final_url"),
                "body_html_path": blog_html_path,
                "body_extract_success": bool(blog_text),
                "body_text_length": len(blog_text or ""),
                "body_error": blog_error,
            }
            raw_path = save_raw_json(
                save_dir / f"{doc_id}.json",
                {
                    "source_id": "naver_blog",
                    "source_type": "api",
                    "run_id": run_id,
                    "query": query,
                    "brand_id": query_item.get("brand_id"),
                    "brand_name": query_item.get("brand_name"),
                    "fetched_at": item.get("fetched_at"),
                    "canonical_url": canonical_url,
                    "search_item": item,
                    "blog": blog_payload,
                    "blog_text_path": str(text_file_path),
                    "blog_text_length": len(blog_text or ""),
                    "body_extract_success": bool(blog_text),
                    "body_error": blog_error,
                },
            )
            text_path = save_raw_text(text_file_path, text)
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
                    "source_id": "naver_blog",
                    "source_type": "api",
                    "query": query,
                    "brand_id": query_item.get("brand_id"),
                    "brand_name": query_item.get("brand_name"),
                    "title": item.get("title"),
                    "url": canonical_url,
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
        f"duplicates={duplicate_count}, filtered={filtered_count}, errors={error_count}"
    )


def crawl_naver_shopping(
    targets: dict,
    *,
    brand_ids: set[str] | None,
    max_products: int | None,
    display: int | None,
    sort: str | None,
    timeout: int | None,
) -> None:
    from .sources.naver_shopping import (
        build_brand_queries,
        fetch_shopping_items,
        is_relevant_item,
    )

    init_db(DUCKDB_PATH, SCHEMA_PATH)

    source_settings = targets.get("sources", {}).get("naver_shopping", {})
    display_count = display or source_settings.get("display") or 50
    sort_method = sort or source_settings.get("sort") or "sim"

    query_items = build_brand_queries(targets)
    if brand_ids:
        query_items = [
            item for item in query_items if item.get("brand_id") in brand_ids
        ]

    crawl_date = datetime.now().strftime("%Y-%m-%d")
    save_dir = WEB_CRAWL_DB_DIR / "raw" / "naver_shopping" / crawl_date

    fetched_count = 0
    inserted_count = 0
    updated_count = 0
    error_count = 0

    print(
        f"crawl start: source=naver_shopping, "
        f"brands={len(query_items)}, display={display_count}, sort={sort_method}"
    )

    for query_item in query_items:
        brand_id = query_item["brand_id"]
        brand_name = query_item["brand_name"]
        aliases = query_item.get("aliases") or []
        query = query_item["query"]
        captured_at = datetime.now().isoformat(sep=" ", timespec="seconds")
        captured_date = captured_at[:10]

        try:
            items = fetch_shopping_items(
                query,
                display=display_count,
                sort=sort_method,
                timeout=timeout or 10,
            )
        except Exception as exc:
            error_count += 1
            print(f"  error: brand={brand_name}, {type(exc).__name__}: {exc}")
            continue

        products = [
            item
            for item in items
            if is_relevant_item(
                item,
                brand_name=brand_name,
                aliases=aliases,
            )
        ]
        if max_products is not None:
            products = products[:max_products]

        raw_path = save_raw_json(
            save_dir / f"{brand_id}_{captured_date}.json",
            {
                "source_id": "naver_shopping",
                "brand_id": brand_id,
                "brand_name": brand_name,
                "query": query,
                "captured_at": captured_at,
                "fetched_count": len(items),
                "filtered_count": len(products),
                "items": items,
            },
        )

        print(
            f"  brand={brand_name}, query={query}, "
            f"fetched={len(items)}, products={len(products)}"
        )
        fetched_count += len(items)

        for product in products:
            sales_type = product.get("sales_type")
            lowest_price = product.get("lowest_price")
            purchase_price = lowest_price if sales_type != "rental" else None
            rental_fee = lowest_price if sales_type == "rental" else None
            product_hash = make_hash(
                json.dumps(product, ensure_ascii=False, sort_keys=True)
            )
            snapshot_key = "|".join(
                [
                    brand_id,
                    product.get("product_id") or "",
                    product.get("url") or "",
                    captured_date,
                ]
            )
            snapshot_id = f"product_{make_hash(snapshot_key)[:16]}"
            inserted = upsert_product_snapshot(
                DUCKDB_PATH,
                {
                    "snapshot_id": snapshot_id,
                    "source_id": "naver_shopping",
                    "brand_id": brand_id,
                    "brand_name": brand_name,
                    "product_name": product.get("title"),
                    "model_code": None,
                    "category": " > ".join(product.get("category") or []),
                    "sales_type": sales_type,
                    "purchase_price": purchase_price,
                    "rental_fee": rental_fee,
                    "original_rental_fee": None,
                    "promotion_text": None,
                    "rating": None,
                    "review_count": None,
                    "product_url": product.get("url"),
                    "captured_date": captured_date,
                    "captured_at": captured_at,
                    "raw_path": raw_path,
                    "content_hash": product_hash,
                    "metadata_json": {
                        "query": query,
                        "naver_product_id": product.get("product_id"),
                        "naver_product_type": product.get("product_type"),
                        "mall_name": product.get("mall_name"),
                        "brand": product.get("brand"),
                        "maker": product.get("maker"),
                        "image_url": product.get("image_url"),
                        "highest_price": product.get("highest_price"),
                        "price_source": (
                            "naver_lprice_as_rental_fee"
                            if sales_type == "rental"
                            else "naver_lprice_as_purchase_price"
                        ),
                        "raw": product.get("raw"),
                    },
                },
            )

            if inserted:
                inserted_count += 1
            else:
                updated_count += 1

    print(
        "crawl finished: "
        f"fetched={fetched_count}, inserted={inserted_count}, "
        f"updated={updated_count}, errors={error_count}"
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
    crawl_parser.add_argument(
        "--source",
        required=True,
        choices=["naver_news", "naver_blog", "naver_shopping"],
    )
    crawl_parser.add_argument("--limit-queries", type=int, default=1)
    crawl_parser.add_argument("--display", type=int, default=None)
    crawl_parser.add_argument(
        "--sort",
        choices=["sim", "date", "asc", "dsc"],
        default=None,
    )
    crawl_parser.add_argument("--fetch-article", action="store_true")
    crawl_parser.add_argument("--article-limit-per-query", type=int, default=3)
    crawl_parser.add_argument(
        "--fetch-blog-body",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Fetch full blog body for naver_blog. Uses targets.yaml default if omitted.",
    )
    crawl_parser.add_argument(
        "--blog-body-limit-per-query",
        type=int,
        default=None,
        help="Maximum blog bodies to fetch per query.",
    )
    crawl_parser.add_argument("--timeout", type=int, default=None)
    crawl_parser.add_argument(
        "--brand-id",
        action="append",
        default=None,
        help="Brand id filter for naver_shopping. Can be repeated.",
    )
    crawl_parser.add_argument(
        "--max-products",
        type=int,
        default=None,
        help="Maximum products per brand for naver_shopping.",
    )

    crawl_all_parser = subparsers.add_parser("crawl-all")
    crawl_all_parser.add_argument("--brand-id", action="append", default=None)
    crawl_all_parser.add_argument("--timeout", type=int, default=None)
    crawl_all_parser.add_argument("--news-limit-queries", type=int, default=5)
    crawl_all_parser.add_argument("--news-display", type=int, default=10)
    crawl_all_parser.add_argument("--fetch-article", action="store_true")
    crawl_all_parser.add_argument("--article-limit-per-query", type=int, default=3)
    crawl_all_parser.add_argument("--blog-limit-queries", type=int, default=4)
    crawl_all_parser.add_argument("--blog-display", type=int, default=10)
    crawl_all_parser.add_argument(
        "--fetch-blog-body",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    crawl_all_parser.add_argument("--blog-body-limit-per-query", type=int, default=5)
    crawl_all_parser.add_argument("--shopping-display", type=int, default=50)
    crawl_all_parser.add_argument("--max-products", type=int, default=20)
    crawl_all_parser.add_argument(
        "--skip-news",
        action="store_true",
        help="Skip naver_news in crawl-all.",
    )
    crawl_all_parser.add_argument(
        "--skip-blog",
        action="store_true",
        help="Skip naver_blog in crawl-all.",
    )
    crawl_all_parser.add_argument(
        "--skip-shopping",
        action="store_true",
        help="Skip naver_shopping in crawl-all.",
    )

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

    shopping_export_parser = subparsers.add_parser("export-shopping")
    shopping_export_parser.add_argument("--month", required=True, help="YYYY-MM")
    shopping_export_parser.add_argument("--source", default="naver_shopping")
    shopping_export_parser.add_argument("--brand-id", default=None)
    shopping_export_parser.add_argument(
        "--change-limit",
        type=int,
        default=20,
        help="Maximum price changes/new/disappeared products per brand.",
    )
    shopping_export_parser.add_argument("--output", default=None)

    summarize_parser = subparsers.add_parser("summarize-documents")
    summarize_parser.add_argument("--month", required=True, help="YYYY-MM")
    summarize_parser.add_argument(
        "--source",
        choices=["naver_news", "naver_blog"],
        default=None,
    )
    summarize_parser.add_argument("--brand-id", default=None)
    summarize_parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum documents to summarize. 0 means no limit.",
    )
    summarize_parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate summaries even when the cache key already exists.",
    )
    summarize_parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="Store low-confidence heuristic summaries when no LLM key exists.",
    )
    summarize_parser.add_argument("--max-input-chars", type=int, default=6000)
    summarize_parser.add_argument("--model", default=None)
    summarize_parser.add_argument("--prompt-version", default=None)

    report_context_parser = subparsers.add_parser("export-report-context")
    report_context_parser.add_argument("--month", required=True, help="YYYY-MM")
    report_context_parser.add_argument("--brand-id", default=None)
    report_context_parser.add_argument("--news-limit", type=int, default=20)
    report_context_parser.add_argument("--blog-limit", type=int, default=20)
    report_context_parser.add_argument(
        "--shopping-change-limit",
        type=int,
        default=20,
    )
    report_context_parser.add_argument(
        "--min-summary-confidence",
        type=float,
        default=0.6,
    )
    report_context_parser.add_argument("--output", default=None)

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
                display=args.display or 10,
                sort=args.sort or "date",
                fetch_article=args.fetch_article,
                article_limit_per_query=args.article_limit_per_query,
                timeout=args.timeout or 10,
            )
        elif args.source == "naver_blog":
            crawl_naver_blog(
                targets,
                brand_ids=set(args.brand_id) if args.brand_id else None,
                limit_queries=args.limit_queries,
                display=args.display,
                sort=args.sort,
                fetch_blog_body=args.fetch_blog_body,
                blog_body_limit_per_query=args.blog_body_limit_per_query,
                timeout=args.timeout,
            )
        elif args.source == "naver_shopping":
            crawl_naver_shopping(
                targets,
                brand_ids=set(args.brand_id) if args.brand_id else None,
                max_products=args.max_products,
                display=args.display,
                sort=args.sort,
                timeout=args.timeout,
            )
    elif args.command == "crawl-all":
        load_env_files()
        targets = load_targets(Path(args.targets))
        brand_ids = set(args.brand_id) if args.brand_id else None
        timeout = args.timeout or 10

        print("crawl-all start")
        if not args.skip_news:
            print("crawl-all step: naver_news")
            crawl_naver_news(
                targets,
                limit_queries=args.news_limit_queries,
                display=args.news_display,
                sort="date",
                fetch_article=args.fetch_article,
                article_limit_per_query=args.article_limit_per_query,
                timeout=timeout,
            )

        if not args.skip_blog:
            print("crawl-all step: naver_blog")
            crawl_naver_blog(
                targets,
                brand_ids=brand_ids,
                limit_queries=args.blog_limit_queries,
                display=args.blog_display,
                sort="date",
                fetch_blog_body=args.fetch_blog_body,
                blog_body_limit_per_query=args.blog_body_limit_per_query,
                timeout=timeout,
            )

        if not args.skip_shopping:
            print("crawl-all step: naver_shopping")
            crawl_naver_shopping(
                targets,
                brand_ids=brand_ids,
                max_products=args.max_products,
                display=args.shopping_display,
                sort="sim",
                timeout=timeout,
            )

        print("crawl-all finished")
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
    elif args.command == "export-shopping":
        from .exporters.shopping_exporter import export_monthly_shopping

        init_db(DUCKDB_PATH, SCHEMA_PATH)
        package = export_monthly_shopping(
            DUCKDB_PATH,
            month=args.month,
            source_id=args.source,
            brand_id=args.brand_id,
            change_limit=args.change_limit,
        )
        output_path = (
            Path(args.output)
            if args.output
            else EXPORT_DIR / f"shopping_{args.month}.json"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(package, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        stats = package["stats"]
        print(
            f"Exported shopping snapshots={stats.get('snapshot_count', 0)} "
            f"products={stats.get('product_candidate_count', 0)} "
            f"brands={stats.get('brand_count', 0)}: {output_path}"
        )
    elif args.command == "summarize-documents":
        from .summarizer import PROMPT_VERSION, summarize_documents

        load_env_files()
        init_db(DUCKDB_PATH, SCHEMA_PATH)
        stats = summarize_documents(
            DUCKDB_PATH,
            month=args.month,
            source_id=args.source,
            brand_id=args.brand_id,
            limit=args.limit,
            force=args.force,
            allow_fallback=args.allow_fallback,
            max_input_chars=args.max_input_chars,
            model_name=args.model,
            prompt_version=args.prompt_version or PROMPT_VERSION,
            progress_callback=print_summary_progress,
        )
        print(
            "Summarized documents "
            f"documents={stats.get('document_count', 0)} "
            f"summarized={stats.get('summarized_count', 0)} "
            f"inserted={stats.get('inserted_count', 0)} "
            f"updated={stats.get('updated_count', 0)} "
            f"cached={stats.get('skipped_cached_count', 0)} "
            f"empty={stats.get('skipped_empty_count', 0)} "
            f"errors={stats.get('error_count', 0)} "
            f"provider={stats.get('provider')} "
            f"model={stats.get('model')}"
        )
    elif args.command == "export-report-context":
        from .exporters.report_context_exporter import export_report_context

        init_db(DUCKDB_PATH, SCHEMA_PATH)
        package = export_report_context(
            DUCKDB_PATH,
            month=args.month,
            brand_id=args.brand_id,
            news_limit=args.news_limit,
            blog_limit=args.blog_limit,
            shopping_change_limit=args.shopping_change_limit,
            min_summary_confidence=args.min_summary_confidence,
        )
        brand_suffix = args.brand_id or "all"
        output_path = (
            Path(args.output)
            if args.output
            else EXPORT_DIR / f"report_context_{args.month}_{brand_suffix}.json"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(package, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        stats = package["stats"]
        print(
            "Exported report context "
            f"news_summaries={stats.get('news_summary_count', 0)} "
            f"blog_summaries={stats.get('blog_summary_count', 0)} "
            f"news_events={stats.get('news_event_count', 0)} "
            f"blog_events={stats.get('blog_event_count', 0)} "
            f"shopping_events={stats.get('shopping_event_count', 0)} "
            f"market_events={stats.get('market_event_count', 0)} "
            f"shopping_products={stats.get('shopping_product_candidate_count', 0)}: "
            f"{output_path}"
        )


if __name__ == "__main__":
    main()
