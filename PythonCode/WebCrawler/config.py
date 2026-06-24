from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_CRAWL_DB_DIR = PROJECT_ROOT / "WebCrawlDB"
SCHEMA_PATH = WEB_CRAWL_DB_DIR / "schema.sql"
WAREHOUSE_DIR = WEB_CRAWL_DB_DIR / "warehouse"
DUCKDB_PATH = WAREHOUSE_DIR / "market.duckdb"
EXPORT_DIR = WEB_CRAWL_DB_DIR / "exports"

def load_targets(path: Path):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)
