-- Build AFTER the data load: BM25 computes its word statistics at build time.

-- Vector (semantic) index: approximate nearest neighbour, cosine distance
CREATE INDEX IF NOT EXISTS support_docs_embedding_idx ON retail.support_docs
  USING lakebase_ann (embedding vector_cosine_ops);

-- Keyword (full-text) index: BM25 ranking over the tsvector
CREATE INDEX IF NOT EXISTS support_docs_bm25 ON retail.support_docs
  USING lakebase_bm25 (body_tsv);

ANALYZE retail.support_docs;
