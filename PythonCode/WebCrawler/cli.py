from datetime import datetime
from .config import DUCKDB_PATH, SCHEMA_PATH, WEB_CRAWL_DB_DIR, load_targets
from .storage.duckdb_store import (
    init_db,
    insert_raw_doc,
    is_doc_exists,
    make_hash,
    normalize_url,
)
from .storage.raw_store import save_raw_json, save_raw_text
from .query_builder import build_queries
from pathlib import Path
import argparse

DEFAULT_TARGETS_PATH = Path(__file__).resolve().parent / "targets.yaml"

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


if __name__ == "__main__":
    main()
