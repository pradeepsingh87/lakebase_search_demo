# Demo runbook

## Demo objective

Show one support workflow in which the user can either provide an exact identifier or describe a problem. The application uses the same searchable case data to demonstrate:

1. Exact-term retrieval for order IDs and product IDs.
2. Meaning-based retrieval for paraphrased complaints.
3. Hybrid ranking that combines both candidate lists.
4. Operational filtering by customer and current status.
5. The difference between local fallback mode and Lakebase mode.

## Demo script

### Local mode

Start the app:

```bash
python -m demo.app
```

Use these queries:

| Query | What it demonstrates |
|---|---|
| `ORDER-BRAVO` | Exact identifier retrieval |
| `shoes arrived damaged` | Meaning-based retrieval over support text |
| `tracking says delivered but nothing came` | Paraphrase matching |
| Select `customer-a` and search delivery issue | Structured operational filtering |

The page displays the top result, status, customer, date, support text, and a debug block showing the active backend and filters.

### Lakebase mode

Before starting the app, confirm that:

* Lakebase Search is enabled in project settings.
* `lakebase_vector` and `lakebase_text` are installed.
* `support_cases` exists and has rows.
* The `lakebase_ann` and `lakebase_bm25` indexes exist.
* `LAKEBASE_DSN` points to the target database.

Then run:

```bash
SEARCH_BACKEND=lakebase python -m demo.seed --backend lakebase
SEARCH_BACKEND=lakebase python -m demo.app
```

The app executes the hybrid query in `demo/search.py`. The SQL uses a filtered CTE, retrieves vector candidates with the cosine distance operator, retrieves BM25 candidates using `to_bm25query`, ranks both lists, and combines them with RRF.

## Validation checklist

Run the automated tests:

```bash
python -m unittest discover -s tests -v
```

Expected local checks:

* An exact order ID returns that order first.
* A delivery complaint returns the missing-delivery case.
* A damaged-shoe complaint returns the damaged-shoe case.
* Customer filtering prevents a similar case for another customer from appearing.

For Lakebase validation, run:

```sql
SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('lakebase_vector', 'lakebase_text')
ORDER BY extname;

SELECT indexrelid::regclass AS index_name, relam::regclass AS access_method
FROM pg_catalog.pg_stat_all_indexes
WHERE relname = 'support_cases';

SELECT case_id, order_id, status, customer_id
FROM support_cases
ORDER BY updated_at DESC;
```

## What to explain during the demo

* Keyword search protects exact IDs and codes.
* Vector search handles different wording for the same customer issue.
* Hybrid search is the retrieval technique.
* Lakebase is the serving architecture when search must sit beside live operational state and relational filters.
* The demo’s hash-based embedding is only a reproducible stand-in. Production should use an embedding model and a dimension that matches the model output.

## Known demo limitations

* The dataset is synthetic and intentionally small.
* The offline embedding is deterministic, not a general-purpose language model.
* The chat response is deterministic; it is not an LLM-generated answer.
* Lakebase Search must be enabled manually in project settings; the package cannot enable it through SQL.
* BM25 statistics are maintained by the Lakebase index and VACUUM behavior; test freshness and update patterns with production-like data before rollout.
