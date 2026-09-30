"""Local and Lakebase-backed hybrid search implementations.

The local implementation keeps the demo runnable without a Lakebase project.
The Lakebase implementation uses lakebase_vector + lakebase_text and the same
hybrid RRF pattern described in the official Lakebase Search documentation.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .data import DEMO_CASES, searchable_text

EMBEDDING_DIM = 32
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]+")

# Lightweight semantic bridges make the offline demo understandable without an
# external embedding model. Production code should replace demo_embed with a
# real embedding model and keep the same VECTOR column/index contract.
SEMANTIC_ALIASES = {
    "delivered": {"delivered", "delivery", "arrived", "received", "missing", "parcel", "package"},
    "missing": {"missing", "nothing", "never", "non-receipt", "not", "received", "door"},
    "damaged": {"damaged", "broken", "defect", "cracked", "faulty"},
    "shoes": {"shoes", "shoe", "sneakers", "running"},
    "wrong": {"wrong", "incorrect", "different", "mistake"},
    "sound": {"sound", "audio", "noise", "silent", "headphones"},
    "refund": {"refund", "return", "money", "replacement"},
}


def tokens(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "")]


def expanded_tokens(text: str) -> list[str]:
    raw = tokens(text)
    expanded = list(raw)
    for token in raw:
        for canonical, aliases in SEMANTIC_ALIASES.items():
            if token in aliases:
                expanded.append(canonical)
    return expanded


def demo_embed(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Create a deterministic demo vector; not a production embedding model."""
    vector = [0.0] * dim
    for token in expanded_tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [round(x / norm, 8) for x in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / (
        (math.sqrt(sum(x * x for x in a)) or 1.0)
        * (math.sqrt(sum(y * y for y in b)) or 1.0)
    )


def row_for(case: dict[str, Any]) -> dict[str, Any]:
    return {
        **case,
        "searchable_text": searchable_text(case),
        "embedding": demo_embed(searchable_text(case)),
    }


def exact_match(query: str, case: dict[str, Any]) -> bool:
    q = query.strip().lower()
    return any(q == str(case.get(field, "")).lower() for field in ("case_id", "order_id", "product_id"))


@dataclass
class SearchResult:
    case_id: str
    customer_id: str
    order_id: str
    product_id: str
    product_name: str
    status: str
    order_date: str
    customer_message: str
    support_notes: str
    score: float
    match_type: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class LocalDemoStore:
    """SQLite-backed fallback with deterministic lexical + semantic scoring."""

    def __init__(self, db_path: str = ":memory:"):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS support_cases (
                case_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                status TEXT NOT NULL,
                order_date TEXT NOT NULL,
                customer_message TEXT NOT NULL,
                support_notes TEXT NOT NULL,
                searchable_text TEXT NOT NULL
            );
            """
        )
        self.db.commit()

    def seed(self, cases: Iterable[dict[str, Any]] = DEMO_CASES) -> None:
        self.db.execute("DELETE FROM support_cases")
        self.db.executemany(
            """
            INSERT INTO support_cases
            (case_id, customer_id, order_id, product_id, product_name, status,
             order_date, customer_message, support_notes, searchable_text)
            VALUES (:case_id, :customer_id, :order_id, :product_id, :product_name,
                    :status, :order_date, :customer_message, :support_notes, :searchable_text)
            """,
            [{**c, "searchable_text": searchable_text(c)} for c in cases],
        )
        self.db.commit()

    def search(self, query: str, customer_id: str | None = None, include_resolved: bool = False, limit: int = 5) -> list[SearchResult]:
        clauses = []
        params: list[Any] = []
        if customer_id:
            clauses.append("customer_id = ?")
            params.append(customer_id)
        if not include_resolved:
            clauses.append("status <> 'resolved'")
        where = " AND ".join(clauses) or "1=1"
        rows = self.db.execute(f"SELECT * FROM support_cases WHERE {where}", params).fetchall()

        q_tokens = set(expanded_tokens(query))
        results = []
        for row in rows:
            item = dict(row)
            text_tokens = set(expanded_tokens(item["searchable_text"]))
            lexical = len(q_tokens.intersection(text_tokens)) / max(len(q_tokens), 1)
            semantic = cosine_similarity(demo_embed(query), demo_embed(item["searchable_text"]))
            exact_bonus = 2.0 if exact_match(query, item) else 0.0
            score = (0.55 * max(semantic, 0.0)) + (0.45 * lexical) + exact_bonus
            match_type = "exact + hybrid" if exact_bonus else "hybrid"
            results.append(SearchResult(score=round(score, 5), match_type=match_type, **{k: item[k] for k in SearchResult.__annotations__ if k not in {"score", "match_type"}}))
        return sorted(results, key=lambda r: (-r.score, r.case_id))[:limit]

    def close(self) -> None:
        self.db.close()


class LakebaseSearchStore:
    """Lakebase implementation using psycopg and Lakebase Search SQL."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ.get("LAKEBASE_DSN")
        if not self.dsn:
            raise ValueError("LAKEBASE_DSN is required for Lakebase mode")
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install psycopg[binary] to use Lakebase mode") from exc
        self.psycopg = psycopg
        self.dict_row = dict_row

    def _connect(self):
        return self.psycopg.connect(self.dsn, row_factory=self.dict_row)

    def seed(self, cases: Iterable[dict[str, Any]] = DEMO_CASES) -> None:
        rows = [{**c, "searchable_text": searchable_text(c), "embedding": demo_embed(searchable_text(c))} for c in cases]
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS lakebase_vector CASCADE")
                cur.execute("CREATE EXTENSION IF NOT EXISTS lakebase_text")
                cur.execute("""
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
                        search_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', searchable_text)) STORED,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS support_cases_customer_idx ON support_cases(customer_id, order_date)")
                # Rebuild search indexes after loading rows. BM25 computes corpus statistics at build time.
                cur.execute("DROP INDEX IF EXISTS support_cases_embedding_ann")
                cur.execute("DROP INDEX IF EXISTS support_cases_search_bm25")
                cur.execute("DELETE FROM support_cases")
                for row in rows:
                    cur.execute(
                        """
                        INSERT INTO support_cases
                        (case_id, customer_id, order_id, product_id, product_name, status,
                         order_date, customer_message, support_notes, searchable_text, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                        """,
                        (row["case_id"], row["customer_id"], row["order_id"], row["product_id"], row["product_name"], row["status"], row["order_date"], row["customer_message"], row["support_notes"], row["searchable_text"], str(row["embedding"])),
                    )
                cur.execute("CREATE INDEX support_cases_embedding_ann ON support_cases USING lakebase_ann (embedding vector_cosine_ops)")
                cur.execute("CREATE INDEX support_cases_search_bm25 ON support_cases USING lakebase_bm25 (search_tsv)")
            conn.commit()

    def search(self, query: str, customer_id: str | None = None, include_resolved: bool = False, limit: int = 5) -> list[SearchResult]:
        where_parts = []
        filter_params: list[Any] = []
        if customer_id:
            where_parts.append("customer_id = %s")
            filter_params.append(customer_id)
        if not include_resolved:
            where_parts.append("status <> 'resolved'")
        where = " AND ".join(where_parts) or "TRUE"
        embedding = str(demo_embed(query))
        sql = f"""
            WITH filtered AS (
                SELECT * FROM support_cases WHERE {where}
            ),
            vector_candidates AS (
                SELECT case_id, embedding <=> %s::vector AS distance
                FROM filtered
                ORDER BY distance
                LIMIT 40
            ),
            vector_ranked AS (
                SELECT case_id, RANK() OVER (ORDER BY distance) AS rank
                FROM vector_candidates
            ),
            keyword_candidates AS (
                SELECT case_id,
                       search_tsv <@> to_bm25query(to_tsvector('english', %s), 'support_cases_search_bm25') AS score
                FROM filtered
                ORDER BY score
                LIMIT 40
            ),
            keyword_ranked AS (
                SELECT case_id, RANK() OVER (ORDER BY score) AS rank
                FROM keyword_candidates
            )
            SELECT f.case_id, f.customer_id, f.order_id, f.product_id, f.product_name,
                   f.status, f.order_date::text AS order_date, f.customer_message, f.support_notes,
                   COALESCE(1.0 / (60 + v.rank), 0) + COALESCE(1.0 / (60 + k.rank), 0) AS score,
                   CASE WHEN v.case_id IS NOT NULL AND k.case_id IS NOT NULL THEN 'hybrid'
                        WHEN k.case_id IS NOT NULL THEN 'keyword'
                        ELSE 'vector' END AS match_type
            FROM filtered f
            LEFT JOIN vector_ranked v ON f.case_id = v.case_id
            LEFT JOIN keyword_ranked k ON f.case_id = k.case_id
            WHERE v.case_id IS NOT NULL OR k.case_id IS NOT NULL
            ORDER BY score DESC, f.case_id
            LIMIT %s
        """
        params = filter_params + [embedding, query, limit]
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [SearchResult(**row) for row in rows]

    def close(self) -> None:
        pass


def make_store(backend: str | None = None):
    backend = (backend or os.environ.get("SEARCH_BACKEND", "local")).lower()
    if backend == "lakebase":
        return LakebaseSearchStore()
    store = LocalDemoStore(os.environ.get("LOCAL_DB_PATH", ":memory:"))
    store.seed()
    return store
