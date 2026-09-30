"""Lakebase Search retail support demo — FastAPI backend."""
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from db import pool
from search import BM25_INDEX, Filters, embed, search

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Lakebase Hybrid Search Demo")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def q(sql: str, params: dict | tuple | None = None) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta():
    counts = q("""SELECT (SELECT count(*) FROM retail.orders) AS orders,
                         (SELECT count(*) FROM retail.shipments) AS shipments,
                         (SELECT count(*) FROM retail.returns) AS returns,
                         (SELECT count(*) FROM retail.conversations) AS conversations,
                         (SELECT count(*) FROM retail.service_notes) AS notes,
                         (SELECT count(*) FROM retail.support_docs) AS docs""")[0]
    customers = q("SELECT customer_id, name FROM retail.customers ORDER BY name")
    pg = q("SELECT current_setting('server_version') AS v")[0]["v"]
    trk = q("SELECT tracking_code FROM retail.shipments WHERE status = 'lost' ORDER BY shipment_id LIMIT 1")
    return {"counts": counts, "customers": customers, "pg_version": pg,
            "sample_tracking": trk[0]["tracking_code"] if trk else None}


@app.get("/api/search")
def api_search(
    q_: str = Query(..., alias="q", min_length=1, max_length=300),
    customer_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    refund_status: str | None = None,
    sources: str | None = None,
    limit: int = Query(10, ge=1, le=25),
):
    f = Filters(
        customer_id=customer_id or None,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        refund_status=refund_status or None,
        sources=[s for s in (sources or "").split(",") if s] or None,
    )
    return search(q_.strip(), f, limit)


@app.get("/api/orders/{order_id}")
def order_detail(order_id: str):
    order = q("""SELECT o.*, c.name AS customer_name, c.email, c.tier
                 FROM retail.orders o JOIN retail.customers c USING (customer_id)
                 WHERE o.order_id = %s""", (order_id,))
    if not order:
        raise HTTPException(404, "order not found")
    return {
        "order": order[0],
        "shipments": q("SELECT * FROM retail.shipments WHERE order_id = %s", (order_id,)),
        "returns": q("SELECT * FROM retail.returns WHERE order_id = %s ORDER BY created_at", (order_id,)),
        "conversations": q("SELECT * FROM retail.conversations WHERE order_id = %s ORDER BY created_at", (order_id,)),
        "notes": q("SELECT * FROM retail.service_notes WHERE order_id = %s ORDER BY created_at, note_id", (order_id,)),
    }


class NoteIn(BaseModel):
    author: str = Field("Demo agent", max_length=60)
    note: str = Field(..., min_length=3, max_length=2000)


@app.post("/api/orders/{order_id}/notes")
def add_note(order_id: str, body: NoteIn):
    """Write a live row: the note is searchable (vector + BM25) as soon as the transaction commits."""
    order = q("SELECT customer_id FROM retail.orders WHERE order_id = %s", (order_id,))
    if not order:
        raise HTTPException(404, "order not found")
    title = f"Service note on {order_id} by {body.author}"
    vec = embed(f"{title}\n{body.note}")
    with pool.connection() as conn, conn.transaction():
        note_id = conn.execute(
            "SELECT 'NTE-' || %s || '-' || (count(*) + 1) AS id FROM retail.service_notes WHERE order_id = %s",
            (order_id.removeprefix("ORD-"), order_id)).fetchone()["id"]
        conn.execute("INSERT INTO retail.service_notes VALUES (%s, %s, %s, current_date, %s)",
                     (note_id, order_id, body.author, body.note))
        conn.execute(
            """INSERT INTO retail.support_docs
               (doc_id, source, order_id, customer_id, doc_date, refund_status, title, body, embedding, body_tsv)
               SELECT %(doc_id)s, 'note', %(oid)s, %(cid)s, current_date,
                      (SELECT refund_status FROM retail.returns WHERE order_id = %(oid)s ORDER BY created_at DESC LIMIT 1),
                      %(title)s, %(note)s, %(vec)s::vector, to_tsvector('english', %(title)s || ' ' || %(note)s)""",
            {"doc_id": f"note:{note_id}", "oid": order_id, "cid": order[0]["customer_id"],
             "title": title, "note": body.note, "vec": vec})
    return {"note_id": note_id}


@app.get("/api/health")
def health():
    return {"ok": q("SELECT 1 AS ok")[0]["ok"] == 1, "bm25_index": BM25_INDEX}
