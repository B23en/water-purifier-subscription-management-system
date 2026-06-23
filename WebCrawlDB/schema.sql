CREATE TABLE IF NOT EXISTS crawl_runs (
    run_id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status VARCHAR NOT NULL,
    query_count INTEGER DEFAULT 0,
    fetched_count INTEGER DEFAULT 0,
    saved_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    message VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_documents (
    doc_id VARCHAR PRIMARY KEY,
    run_id VARCHAR,
    source_id VARCHAR NOT NULL,
    source_type VARCHAR,
    query VARCHAR,
    brand_id VARCHAR,
    brand_name VARCHAR,
    title VARCHAR,
    url VARCHAR NOT NULL,
    published_at TIMESTAMP,
    crawled_at TIMESTAMP NOT NULL,
    raw_path VARCHAR,
    text_path VARCHAR,
    content_hash VARCHAR,
    url_hash VARCHAR,
    metadata_json VARCHAR
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_documents_url_hash
ON raw_documents(url_hash);

CREATE TABLE IF NOT EXISTS crawl_errors (
    error_id VARCHAR PRIMARY KEY,
    run_id VARCHAR,
    source_id VARCHAR NOT NULL,
    query VARCHAR,
    url VARCHAR,
    error_type VARCHAR NOT NULL,
    status_code INTEGER,
    occurred_at TIMESTAMP NOT NULL,
    message VARCHAR
);

CREATE TABLE IF NOT EXISTS market_events (
    event_id VARCHAR PRIMARY KEY,
    doc_id VARCHAR,
    source_id VARCHAR,
    event_date DATE,
    brand_id VARCHAR,
    brand_name VARCHAR,
    product_name VARCHAR,
    event_type VARCHAR,
    sentiment VARCHAR,
    summary VARCHAR,
    confidence DOUBLE,
    source_url VARCHAR,
    created_at TIMESTAMP NOT NULL,
    model_name VARCHAR
);