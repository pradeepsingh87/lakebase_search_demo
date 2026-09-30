-- Lakebase Search retail support demo
-- Follows https://docs.databricks.com/aws/en/oltp/projects/lakebase-search
-- Prereq: Lakebase Search enabled on the project (Settings -> Lakebase Search), Postgres 16+.

-- 1. Extensions (CASCADE installs pgvector)
CREATE EXTENSION IF NOT EXISTS lakebase_vector CASCADE;
CREATE EXTENSION IF NOT EXISTS lakebase_text;

CREATE SCHEMA IF NOT EXISTS retail;

-- 2. Live operational tables
DROP TABLE IF EXISTS retail.support_docs, retail.service_notes, retail.conversations,
  retail.returns, retail.shipments, retail.orders, retail.customers CASCADE;

CREATE TABLE retail.customers (
  customer_id  TEXT PRIMARY KEY,           -- CUS-1001
  name         TEXT NOT NULL,
  email        TEXT NOT NULL,
  tier         TEXT NOT NULL               -- standard | plus | vip
);

CREATE TABLE retail.orders (
  order_id     TEXT PRIMARY KEY,           -- ORD-48213
  customer_id  TEXT NOT NULL REFERENCES retail.customers,
  order_date   DATE NOT NULL,
  status       TEXT NOT NULL,              -- placed | shipped | delivered | cancelled
  items        TEXT NOT NULL,
  total        NUMERIC(10,2) NOT NULL
);

CREATE TABLE retail.shipments (
  shipment_id   TEXT PRIMARY KEY,
  order_id      TEXT NOT NULL REFERENCES retail.orders,
  carrier       TEXT NOT NULL,
  tracking_code TEXT NOT NULL,             -- 1Z84X2...
  status        TEXT NOT NULL,             -- in_transit | delivered | exception | lost
  shipped_at    DATE NOT NULL,
  delivered_at  DATE
);

CREATE TABLE retail.returns (
  return_id     TEXT PRIMARY KEY,          -- RMA-20931
  order_id      TEXT NOT NULL REFERENCES retail.orders,
  reason        TEXT NOT NULL,
  refund_status TEXT NOT NULL,             -- requested | approved | refunded | denied
  created_at    DATE NOT NULL
);

CREATE TABLE retail.conversations (
  conversation_id TEXT PRIMARY KEY,
  order_id        TEXT NOT NULL REFERENCES retail.orders,
  channel         TEXT NOT NULL,           -- chat | email | phone
  created_at      DATE NOT NULL,
  transcript      TEXT NOT NULL
);

CREATE TABLE retail.service_notes (
  note_id     TEXT PRIMARY KEY,
  order_id    TEXT NOT NULL REFERENCES retail.orders,
  author      TEXT NOT NULL,
  created_at  DATE NOT NULL,
  note        TEXT NOT NULL
);

-- 3. Search table: one row per text field where complaints actually appear.
--    Carries the filter columns (customer, date, refund status) so hybrid search
--    can filter and rank in a single query on live rows.
CREATE TABLE retail.support_docs (
  doc_id        TEXT PRIMARY KEY,          -- <source>:<source id>
  source        TEXT NOT NULL,             -- order | shipment | return | conversation | note
  order_id      TEXT NOT NULL REFERENCES retail.orders,
  customer_id   TEXT NOT NULL REFERENCES retail.customers,
  doc_date      DATE NOT NULL,
  refund_status TEXT,                      -- latest return refund status for the order (NULL = no return)
  title         TEXT NOT NULL,
  body          TEXT NOT NULL,
  embedding     VECTOR(1024),              -- databricks-gte-large-en
  body_tsv      TSVECTOR                   -- to_tsvector('english', title || body)
);

CREATE INDEX support_docs_customer_idx ON retail.support_docs (customer_id);
CREATE INDEX support_docs_date_idx     ON retail.support_docs (doc_date);
