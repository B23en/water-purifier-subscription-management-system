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
    load_targets,
)
from .crawler_service import (
    crawl_all,
    crawl_naver_blog,
    crawl_naver_news,
    crawl_naver_shopping,
)
from .query_builder import build_queries
from .storage.duckdb_store import init_db


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
    handle_command(args)


def handle_command(args: argparse.Namespace) -> None:
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
        handle_crawl_command(args)
    elif args.command == "crawl-all":
        handle_crawl_all_command(args)
    elif args.command == "export-issues":
        handle_export_issues_command(args)
    elif args.command == "export-shopping":
        handle_export_shopping_command(args)
    elif args.command == "summarize-documents":
        handle_summarize_documents_command(args)
    elif args.command == "export-report-context":
        handle_export_report_context_command(args)


def handle_crawl_command(args: argparse.Namespace) -> None:
    load_env_files()
    targets = load_targets(Path(args.targets))
    brand_ids = set(args.brand_id) if args.brand_id else None

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
            brand_ids=brand_ids,
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
            brand_ids=brand_ids,
            max_products=args.max_products,
            display=args.display,
            sort=args.sort,
            timeout=args.timeout,
        )


def handle_crawl_all_command(args: argparse.Namespace) -> None:
    load_env_files()
    targets = load_targets(Path(args.targets))
    crawl_all(
        targets,
        brand_ids=set(args.brand_id) if args.brand_id else None,
        timeout=args.timeout or 10,
        news_limit_queries=args.news_limit_queries,
        news_display=args.news_display,
        fetch_article=args.fetch_article,
        article_limit_per_query=args.article_limit_per_query,
        blog_limit_queries=args.blog_limit_queries,
        blog_display=args.blog_display,
        fetch_blog_body=args.fetch_blog_body,
        blog_body_limit_per_query=args.blog_body_limit_per_query,
        shopping_display=args.shopping_display,
        max_products=args.max_products,
        skip_news=args.skip_news,
        skip_blog=args.skip_blog,
        skip_shopping=args.skip_shopping,
    )


def handle_export_issues_command(args: argparse.Namespace) -> None:
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
    write_json(output_path, package)

    stats = package["stats"]
    exported_count = (
        stats.get("issue_count")
        or stats.get("exported_count")
        or stats.get("document_count")
        or 0
    )
    source_count = stats.get("document_count") or stats.get("summary_count") or 0
    print(
        f"Exported {exported_count} items "
        f"from {source_count} source rows: {output_path}"
    )


def handle_export_shopping_command(args: argparse.Namespace) -> None:
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
        Path(args.output) if args.output else EXPORT_DIR / f"shopping_{args.month}.json"
    )
    write_json(output_path, package)

    stats = package["stats"]
    print(
        f"Exported shopping snapshots={stats.get('snapshot_count', 0)} "
        f"products={stats.get('product_candidate_count', 0)} "
        f"brands={stats.get('brand_count', 0)}: {output_path}"
    )


def handle_summarize_documents_command(args: argparse.Namespace) -> None:
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


def handle_export_report_context_command(args: argparse.Namespace) -> None:
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
    write_json(output_path, package)

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


def write_json(output_path: Path, package: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(package, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
