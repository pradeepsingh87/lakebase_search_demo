-- Run after enabling Lakebase Search in the Lakebase project settings.
-- Enabling the feature is a project-level action and restarts project computes.

CREATE EXTENSION IF NOT EXISTS lakebase_vector CASCADE;
CREATE EXTENSION IF NOT EXISTS lakebase_text;

CREATE TABLE IF NOT EXISTS support_cases (
    case_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    product_name TEXT NOT NULL,
    status TEXT NOT NULL,
    order_date DATE NOT NULL,
    customer_message TEXT NOT NULL,
    support_notes TEXT NOT NULL,
    searchable_text TEXT NOT NULL,
    embedding VECTOR(32),
    search_tsv TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', searchable_text)
    ) STORED,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS support_cases_customer_idx
    ON support_cases(customer_id, order_date);

-- Build the search indexes after the seed data is loaded:
-- CREATE INDEX support_cases_embedding_ann
--     ON support_cases USING lakebase_ann (embedding vector_cosine_ops);
-- CREATE INDEX support_cases_search_bm25
--     ON support_cases USING lakebase_bm25 (search_tsv);
