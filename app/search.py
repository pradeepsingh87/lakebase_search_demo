"""Keyword (BM25), vector (ANN) and hybrid (RRF) search over retail.support_docs.

The SQL mirrors https://docs.databricks.com/aws/en/oltp/projects/lakebase-search
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache

from db import pool, w

EMBEDDING_ENDPOINT = os.getenv("EMBEDDING_ENDPOINT", "databricks-gte-large-en")
BM25_INDEX = "retail.support_docs_bm25"
CANDIDATES = 40  # per-list depth fed into RRF
RRF_K = 60
_executor = ThreadPoolExecutor(max_workers=8)


@lru_cache(maxsize=512)
def embed(text: str) -> str:
    resp = w.serving_endpoints.query(name=EMBEDDING_ENDPOINT, input=[text])
    return str(resp.data[0].embedding)


@dataclass
class Filters:
    customer_id: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    refund_status: str | None = None  # requested | approved | refunded | denied | none
    sources: list[str] | None = None

    def where(self) -> tuple[str, dict]:
        """Filter predicate applied inside each ranked list, before LIMIT."""
        parts, params = [], {}
        if self.customer_id:
            parts.append("customer_id = %(customer_id)s")
            params["customer_id"] = self.customer_id
        if self.date_from:
            parts.append("doc_date >= %(date_from)s")
            params["date_from"] = self.date_from
        if self.date_to:
            parts.append("doc_date <= %(date_to)s")
            params["date_to"] = self.date_to
        if self.refund_status == "none":
            parts.append("refund_status IS NULL")
        elif self.refund_status:
            parts.append("refund_status = %(refund_status)s")
            params["refund_status"] = self.refund_status
        if self.sources:
            parts.append("source = ANY(%(sources)s)")
            params["sources"] = self.sources
        return " AND ".join(parts), params


def _and(cond: str) -> str:
    return f"\n    WHERE {cond}" if cond else ""


def keyword_sql(cond: str) -> str:
    # <@> returns a negative BM25 score (lower = better); docs sharing no term with the query score 0.
    return f"""SELECT * FROM (
  SELECT doc_id, source, order_id, customer_id, doc_date, refund_status, title, body,
    body_tsv <@> to_bm25query(to_tsvector('english', %(q)s), '{BM25_INDEX}') AS score
  FROM retail.support_docs{_and(cond).replace(chr(10) + '    ', chr(10) + '  ')}
  ORDER BY score
  LIMIT %(limit)s
) k
WHERE score < 0"""


def vector_sql(cond: str) -> str:
    return f"""SELECT doc_id, source, order_id, customer_id, doc_date, refund_status, title, body,
  embedding <=> %(qvec)s::vector AS score
FROM retail.support_docs{_and(cond)}
ORDER BY score
LIMIT %(limit)s"""


def _fused_ctes(cond: str) -> str:
    return f"""WITH vector_ranked AS (
  SELECT doc_id, dist, RANK() OVER (ORDER BY dist) AS rank
  FROM (
    SELECT doc_id, embedding <=> %(qvec)s::vector AS dist
    FROM retail.support_docs{_and(cond)}
    ORDER BY dist
    LIMIT {CANDIDATES}
  ) v),
keyword_ranked AS (
  SELECT doc_id, score, RANK() OVER (ORDER BY score) AS rank
  FROM (
    SELECT doc_id, body_tsv <@> to_bm25query(to_tsvector('english', %(q)s), '{BM25_INDEX}') AS score
    FROM retail.support_docs{_and(cond)}
    ORDER BY score
    LIMIT {CANDIDATES}
  ) k
  WHERE score < 0),
fused AS (
  SELECT d.*, v.rank AS vector_rank, k.rank AS keyword_rank, v.dist, k.score AS bm25,
    COALESCE(1.0 / ({RRF_K} + v.rank), 0) + COALESCE(1.0 / ({RRF_K} + k.rank), 0) AS rrf_score
  FROM retail.support_docs d
  LEFT JOIN vector_ranked v ON d.doc_id = v.doc_id
  LEFT JOIN keyword_ranked k ON d.doc_id = k.doc_id
  WHERE v.doc_id IS NOT NULL OR k.doc_id IS NOT NULL)"""


def hybrid_sql(cond: str) -> str:
    return _fused_ctes(cond) + """
SELECT doc_id, source, order_id, customer_id, doc_date, refund_status, title, body,
  vector_rank, keyword_rank, dist, bm25, rrf_score
FROM fused
ORDER BY rrf_score DESC, doc_id
LIMIT %(limit)s"""


def orders_sql(cond: str) -> str:
    # Roll document scores up to the order and join live order rows: several matching
    # docs (chat + return + note) for one order reinforce each other.
    return _fused_ctes(cond) + """
SELECT f.order_id, c.name AS customer_name, o.items, o.status, max(f.refund_status) AS refund_status,
  count(*) AS docs, array_agg(DISTINCT f.source) AS sources,
  min(f.keyword_rank) AS best_keyword_rank, min(f.vector_rank) AS best_vector_rank,
  sum(f.rrf_score) AS order_score
FROM fused f
JOIN retail.orders o USING (order_id)
JOIN retail.customers c ON c.customer_id = o.customer_id
GROUP BY f.order_id, c.name, o.items, o.status
ORDER BY order_score DESC
LIMIT 5"""


def _run(sql: str, params: dict) -> tuple[list[dict], float]:
    t0 = time.perf_counter()
    with pool.connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return rows, (time.perf_counter() - t0) * 1000


def _clean(rows: list[dict]) -> list[dict]:
    for r in rows:
        if "doc_date" in r:
            r["doc_date"] = r["doc_date"].isoformat()
        for k in ("score", "dist", "bm25", "rrf_score", "order_score"):
            if r.get(k) is not None:
                r[k] = float(r[k])
    return rows


def search(q: str, filters: Filters, limit: int = 10) -> dict:
    cond, fparams = filters.where()
    t0 = time.perf_counter()
    qvec = embed(q)
    embed_ms = (time.perf_counter() - t0) * 1000
    params = {"q": q, "qvec": qvec, "limit": limit, **fparams}

    out = {"query": q, "embed_ms": round(embed_ms, 1), "params": {k: v for k, v in params.items() if k != "qvec"}}
    queries = {"keyword": keyword_sql(cond), "vector": vector_sql(cond),
               "hybrid": hybrid_sql(cond), "orders": orders_sql(cond)}
    futures = {name: _executor.submit(_run, sql, params) for name, sql in queries.items()}
    for name, fut in futures.items():
        rows, ms = fut.result()
        out[name] = {"rows": _clean(rows), "ms": round(ms, 1), "sql": queries[name]}
    return out
