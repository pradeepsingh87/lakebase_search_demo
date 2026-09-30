-- Run after lakebase_setup.sql and after loading support_cases rows.
CREATE INDEX IF NOT EXISTS support_cases_embedding_ann
    ON support_cases USING lakebase_ann (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS support_cases_search_bm25
    ON support_cases USING lakebase_bm25 (search_tsv);
