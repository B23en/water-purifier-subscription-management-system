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

CREATE TABLE IF NOT EXISTS product_snapshots (
    snapshot_id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    brand_id VARCHAR NOT NULL,
    brand_name VARCHAR NOT NULL,
    product_name VARCHAR NOT NULL,
    model_code VARCHAR,
    category VARCHAR,
    sales_type VARCHAR,
    purchase_price INTEGER,
    rental_fee INTEGER,
    original_rental_fee INTEGER,
    promotion_text VARCHAR,
    rating DOUBLE,
    review_count INTEGER,
    product_url VARCHAR,
    captured_date DATE NOT NULL,
    captured_at TIMESTAMP NOT NULL,
    raw_path VARCHAR,
    content_hash VARCHAR,
    metadata_json VARCHAR
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_product_snapshots_daily
ON product_snapshots(brand_id, product_url, model_code, captured_date);

CREATE TABLE IF NOT EXISTS document_summaries (
    summary_id VARCHAR PRIMARY KEY,
    doc_id VARCHAR NOT NULL,
    content_hash VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    brand_id VARCHAR,
    brand_name VARCHAR,
    title VARCHAR,
    source_url VARCHAR,
    published_at TIMESTAMP,
    is_relevant BOOLEAN,
    summary VARCHAR,
    key_points_json VARCHAR,
    evidence_excerpt VARCHAR,
    mentioned_products_json VARCHAR,
    confidence DOUBLE,
    model_name VARCHAR,
    prompt_version VARCHAR,
    created_at TIMESTAMP NOT NULL,
    metadata_json VARCHAR
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_document_summaries_cache
ON document_summaries(doc_id, content_hash, model_name, prompt_version);
