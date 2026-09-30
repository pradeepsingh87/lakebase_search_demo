# Lakebase Hybrid Search demo — retailer support

A retailer support app that finds the right order **by code or by complaint**. Everything runs inside
Lakebase: live operational tables, a `lakebase_ann` vector index, a `lakebase_bm25` keyword index, and
hybrid Reciprocal Rank Fusion (RRF) in a single SQL query. It follows
[Lakebase Search → Combine results with hybrid search](https://docs.databricks.com/aws/en/oltp/projects/lakebase-search#combine-results-with-hybrid-search).

**Deployed:** https://lakebase-hybrid-search-7474654711730388.aws.databricksapps.com (workspace `free_edition`)

```
Exact code  "ORD-48213"      ─▶ Keyword  (BM25, lakebase_bm25) ─┐
                                                                 ├─▶ Hybrid RRF ─▶ roll up by order ─▶ the right order
Plain words "arrived damaged" ─▶ Vector  (ANN, lakebase_ann)   ─┘   filters: customer · date · refund status · source
                     ▲
        live Lakebase tables: orders · shipments · returns · conversations · service_notes
```

## What's where

| Path | Purpose |
|---|---|
| `sql/01_schema.sql` | Extensions, `retail` schema, the live tables, and `retail.support_docs` (`VECTOR(1024)` + `TSVECTOR`) |
| `sql/02_indexes.sql` | `lakebase_ann` and `lakebase_bm25` indexes. Build these **after** the data load. |
| `sql/03_grants.sql` | Grants for the app's service principal on the `retail` schema |
| `scripts/seed.py` | Creates synthetic data, embeds it with `databricks-gte-large-en`, loads it, builds the indexes, re-applies grants |
| `app/search.py` | The keyword, vector, hybrid and order-rollup SQL |
| `app/app.py` | FastAPI: `/api/search`, `/api/orders/{id}`, `POST /api/orders/{id}/notes` (live write), `/api/meta` |
| `app/static/` | Single-page UI with three columns side by side, plus a best-order card, SQL panels and an order drawer |

Lakebase: project `lakebase-search-demo`, branch `production`, database `databricks_postgres`, schema `retail`.

## Demo script (≈3 min)

1. **`ORD-48213`** (Exact code chip). Keyword finds all five docs for the order. Vector returns loosely related
   notes, because embeddings don't understand IDs. Hybrid and the best-order card resolve **ORD-48213, Maya Chen**.
2. **`arrived damaged`** (Plain words). Keyword only finds docs containing those literal words. Vector also finds
   "Cracked in transit", "Broken on delivery" and "Photos confirm transit damage". Hybrid keeps the best of both.
3. **`ORD-48213 arrived damaged`** (Both). Neither list alone puts the order first on every doc. The order rollup
   sums RRF across the chat, return, note, order and shipment docs, which picks ORD-48213 decisively.
4. **Filters.** Set Refund status = *Requested* and From = 2026-08-01, then rerun "arrived damaged". The filters are
   applied inside each ranked list, in the same query.
5. **Tracking code chip.** A carrier tracking number is a pure keyword match.
6. **Live rows.** Open any order, add a note such as *"steam leaks from the lid seal"*, then search
   *"steam escaping from top"*. The new row shows up immediately in both vector and keyword results.
7. Open the **SQL** panels to show that the hybrid query is the doc's RRF pattern: two ranked CTEs with a
   `LIMIT 40` each, fused with `1/(60+rank)`.

## Run locally

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r app/requirements.txt
cd app && DATABRICKS_CONFIG_PROFILE=free_edition ../.venv/bin/uvicorn app:app --port 8765
```

Re-seed (drops and recreates the `retail` tables; embeddings are cached in `scripts/.embedding_cache.json`):

```bash
cd scripts && ../.venv/bin/python seed.py
```

## Redeploy

```bash
cd app && databricks sync . /Workspace/Users/pradeep.singh87@outlook.com/lakebase-hybrid-search --full --profile free_edition
databricks apps deploy lakebase-hybrid-search \
  --source-code-path /Workspace/Users/pradeep.singh87@outlook.com/lakebase-hybrid-search --profile free_edition
```

App resources: `postgres` (branch + database, `CAN_CONNECT_AND_CREATE`) and `serving-endpoint`
(`databricks-gte-large-en`, `CAN_QUERY`). The app gets its Postgres host and role from the injected `PG*` env vars
and mints OAuth tokens with `w.postgres.generate_database_credential`. Tokens are refreshed every 40 minutes, and
pooled connections are recycled after 45 minutes.

## Notes and watch-outs

- **Embeddings are generated outside Lakebase.** Lakebase stores and indexes them. The seed uses
  `databricks-gte-large-en` (1024-d), and the app embeds each query with the same model.
- **Free Edition rate limit.** The pay-per-token embedding endpoint rejects batches larger than about 8 inputs.
  The seed throttles and caches embeddings for that reason.
- **BM25 statistics are computed when the index is built.** Rows inserted later are searchable right away, but for
  large loads you should rebuild the index (`REINDEX INDEX retail.support_docs_bm25`).
- **Filtering rows with no matching words.** `<@>` gives a score of 0 to docs that share no term with the query.
  The keyword list filters with `score < 0` so those rows don't pick up an RRF rank.
- **Hybrid ranks; it doesn't decide.** When the top two orders score within 20% of each other, the UI shows a
  "close call" warning.
