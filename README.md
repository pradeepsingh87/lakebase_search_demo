# Lakebase Search customer-support demo

This package is a small, reproducible demo of a customer-support application that searches orders in two ways:

* Exact identifiers such as order IDs, tracking codes, and product IDs
* Natural-language issue descriptions such as “the tracking says delivered, but nothing came”

The demo shows why hybrid search is useful and when serving it from Lakebase is valuable: the search can be combined with customer/status filters and the result can feed an operational workflow.

## What is included

* `notebooks/lakebase_search_demo.ipynb` — guided notebook covering the data model, local validation, Lakebase setup, and hybrid query.
* `demo/app.py` — dependency-light chat interface.
* `demo/search.py` — local fallback plus Lakebase-backed hybrid search.
* `demo/data.py` — synthetic support cases.
* `lakebase_setup.sql` — extensions and table definition.
* `build_search_indexes.sql` — ANN and BM25 index creation.
* `tests/test_local_search.py` — repeatable local validation.
* `docs/RUNBOOK.md` — run and demo instructions.

## Fastest path: run the local demo

The local mode requires Python 3.10+ and does not require a Lakebase connection.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m demo.app
```

Open `http://127.0.0.1:8000` and try:

* `ORDER-BRAVO` — exact identifier lookup
* `shoes arrived damaged` — semantic issue search
* `tracking says delivered but nothing came` — semantic delivery issue
* Select `customer-a` to see the operational customer filter

## Lakebase mode

1. Create or open a Lakebase project running PostgreSQL 16 or later.
2. Enable Lakebase Search in the project settings. This is a project-level action that restarts project computes and cannot be turned off.
3. Run `lakebase_setup.sql` against the target database.
4. Install dependencies with `python -m pip install -r requirements.txt`.
5. Set `LAKEBASE_DSN` and `SEARCH_BACKEND=lakebase`.
6. Run `python -m demo.seed --backend lakebase` to load the synthetic cases and build the search indexes.
7. Run `python -m demo.app` and open the local URL.

Example:

```bash
export LAKEBASE_DSN='postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require'
export SEARCH_BACKEND=lakebase
python -m demo.seed --backend lakebase
python -m demo.app
```

The Lakebase implementation uses `lakebase_vector` for ANN vector search, `lakebase_text` for BM25 keyword search, and Reciprocal Rank Fusion to combine their ranked candidates. The demo embedding is deterministic and intentionally lightweight; replace `demo_embed` with a production embedding model for a real application.

## Sources

* [Lakebase Search](https://docs.databricks.com/aws/en/oltp/projects/lakebase-search)
* [lakebase_vector](https://docs.databricks.com/aws/en/oltp/projects/lakebase-vector)
* [lakebase_text](https://docs.databricks.com/aws/en/oltp/projects/lakebase-text)
* [Postgres extensions](https://docs.databricks.com/aws/en/oltp/projects/extensions)
