"""Create the retail schema, load synthetic support data, embed it, and build the search indexes.

Usage:  ../.venv/bin/python seed.py            (from scripts/)
Env:    DATABRICKS_CONFIG_PROFILE (default free_edition), LAKEBASE_ENDPOINT, EMBEDDING_ENDPOINT
"""
import json
import os
import random
import time
from datetime import date, timedelta
from pathlib import Path

from databricks.sdk import WorkspaceClient

from pg import PROFILE, connect

EMBEDDING_ENDPOINT = os.getenv("EMBEDDING_ENDPOINT", "databricks-gte-large-en")
SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
CACHE = Path(__file__).resolve().parent / ".embedding_cache.json"
rng = random.Random(7)

FIRST = ["Maya", "Liam", "Sofia", "Noah", "Ava", "Ethan", "Priya", "Lucas", "Zoe", "Omar", "Hana", "Diego",
         "Grace", "Mateo", "Chloe", "Arjun", "Emma", "Kenji", "Isla", "Samuel", "Nina", "Leo", "Amara", "Ryan"]
LAST = ["Chen", "Patel", "Garcia", "Johnson", "Kim", "Nguyen", "Okafor", "Rossi", "Silva", "Müller",
        "Smith", "Haddad", "Tanaka", "Brown", "Lopez", "Walsh"]
PRODUCTS = [
    ("Stoneware dinner set (12 pc)", 129.00), ("Glass table lamp", 89.00), ("27in 4K monitor", 329.00),
    ("Merino crew sweater - green, M", 79.00), ("Espresso machine", 249.00), ("Oak picture frame 16x20", 45.00),
    ("Ceramic mug set (4)", 36.00), ("Wireless earbuds", 119.00), ("Running shoes - size 10", 140.00),
    ("Cast iron skillet 12in", 55.00), ("Bookshelf, 5 tier (flat pack)", 159.00), ("High-speed blender", 99.00),
    ("Linen duvet cover - queen", 110.00), ("Kids' bike helmet", 42.00), ("Robot vacuum", 299.00),
    ("Wool throw blanket", 68.00), ("Dining chairs (set of 2)", 210.00), ("Smartwatch band", 29.00),
]
CARRIERS = [("UPS", "1Z"), ("FedEx", "FX"), ("USPS", "94"), ("DHL", "JD")]
AGENTS = ["J. Alvarez", "K. Osei", "R. Patel", "M. Brooks", "T. Lin"]

# Complaint types: many phrasings, few shared keywords -> keyword search misses what vector search finds.
ISSUES = {
    "damaged": {
        "customer": [
            "The {p} showed up cracked and the outer box looked like it had been dropped.",
            "Opened the package and the {p} was shattered, pieces everywhere.",
            "Arrived damaged. The corner is dented and there's a deep scratch across the front.",
            "Box was crushed on one side and the {p} inside is broken.",
            "Just unboxed the {p} - it's in two pieces. Packaging was soaking wet.",
            "There's a crack running right through the {p}. It was like that out of the box.",
        ],
        "return": ["Broken on delivery", "Cracked in transit", "Item damaged in shipping", "Shattered on arrival"],
        "note": [
            "Customer sent photos confirming transit damage. Filed carrier claim, offered replacement.",
            "Visible crush damage on carton per photos. Replacement queued, no need to return broken unit.",
            "Carrier mishandling suspected - packaging torn. Approved refund pending claim.",
        ],
    },
    "lost": {
        "customer": [
            "Tracking says delivered but there is nothing at my door or with neighbours.",
            "My package never showed up. It has been stuck at the same scan for eight days.",
            "Where is my order? The {p} was supposed to be here last week.",
            "Carrier marked it delivered to a mailbox I don't have. I never received anything.",
        ],
        "return": [],
        "note": [
            "Opened trace with carrier. Package shows delivered to wrong address - reshipping.",
            "No scans for 7 days, declared lost in transit. Sent replacement at no charge.",
        ],
    },
    "wrong_item": {
        "customer": [
            "I ordered the {p} but received something completely different.",
            "Got a blue one instead of the green I picked. Also the size is wrong.",
            "This isn't what I bought - looks like someone else's order ended up in my box.",
        ],
        "return": ["Wrong item received", "Incorrect size or color shipped", "Received another customer's item"],
        "note": [
            "Warehouse pick error confirmed. Prepaid label sent, correct item shipping today.",
            "Mis-ship: SKU mismatch at packing. Exchange approved.",
        ],
    },
    "missing_parts": {
        "customer": [
            "The {p} is missing the hardware bag - no screws or brackets in the box.",
            "Only one of the two pieces was in the shipment.",
            "Instructions mention a power cable but there isn't one included.",
        ],
        "return": ["Incomplete - parts missing"],
        "note": ["Sent missing hardware kit via expedited shipping.", "Second box of split shipment never left warehouse, releasing now."],
    },
    "defective": {
        "customer": [
            "The {p} stopped working after two days. It won't power on at all.",
            "Makes a loud grinding noise and then shuts itself off.",
            "Left side is dead - only one side works.",
        ],
        "return": ["Defective - stopped working", "Faulty unit", "Does not power on"],
        "note": ["Troubleshooting failed, unit is DOA. RMA issued.", "Known batch issue with this model, swap for new unit."],
    },
    "billing": {
        "customer": [
            "I was charged twice for the same order. Please fix this.",
            "My card shows two payments for the {p}.",
            "The price at checkout was higher than what was listed on the product page.",
        ],
        "return": [],
        "note": ["Duplicate authorization confirmed, voided second charge.", "Price-match adjustment issued as partial refund."],
    },
    "late": {
        "customer": [
            "Promised Tuesday delivery, it came the following Monday. I needed it for an event.",
            "Shipping took three weeks. Way longer than the estimate.",
        ],
        "return": ["Arrived too late - no longer needed"],
        "note": ["Carrier delay at regional hub. Refunded shipping fee as goodwill."],
    },
    "refund_delay": {
        "customer": [
            "I sent the {p} back a month ago and I still don't have my money.",
            "Your site says my return was received, but the refund hasn't hit my account.",
        ],
        "return": ["Changed my mind"],
        "note": ["Return received at DC but not processed - escalated to returns team.", "Refund stuck in payment gateway, manually released."],
    },
}
BENIGN_CHATS = [
    "Can I change the delivery address on my order?",
    "Do you offer gift wrapping for this?",
    "Is the {p} dishwasher safe?",
    "Can you combine this with my other open order to save shipping?",
    "What is your warranty on the {p}?",
]
AGENT_REPLIES = {
    "damaged": "So sorry about that! Could you send a couple of photos of the item and the box? We'll make it right.",
    "lost": "I'm sorry - I've opened a trace with the carrier and will update you within 24 hours.",
    "wrong_item": "Apologies for the mix-up. I'm emailing a prepaid return label and sending the correct item.",
    "missing_parts": "Sorry about that - I'll ship the missing parts right away.",
    "defective": "That's not right. Let's try a quick reset; if it still fails we'll replace it.",
    "billing": "Thanks for flagging. I can see the duplicate and I'm reversing it now.",
    "late": "I apologise for the delay. I've refunded your shipping cost.",
    "refund_delay": "Let me check with our returns team and escalate this for you.",
    None: "Happy to help! I've updated that for you.",
}
REFUND_BY_ISSUE = {"damaged": ["requested", "approved", "refunded"], "wrong_item": ["approved", "refunded"],
                   "missing_parts": ["requested", "approved"], "defective": ["requested", "approved", "refunded", "denied"],
                   "late": ["requested", "denied", "refunded"], "refund_delay": ["approved", "requested"]}


def build_data():
    customers, orders, shipments, returns, convs, notes = [], [], [], [], [], []
    names = set()
    while len(names) < 40:
        names.add(f"{rng.choice(FIRST)} {rng.choice(LAST)}")
    names = sorted(names)
    names.remove("Maya Chen") if "Maya Chen" in names else names.pop()
    names.insert(0, "Maya Chen")  # featured customer -> CUS-1001
    for i, n in enumerate(names):
        email = n.lower().replace(" ", ".").replace("ü", "u") + "@example.com"
        customers.append((f"CUS-{1001 + i}", n, email, rng.choice(["standard"] * 5 + ["plus"] * 3 + ["vip"])))

    start = date(2026, 6, 1)
    used_ids = {48213, 48231, 48123}
    order_nums = [48213, 48231, 48123] + rng.sample([n for n in range(40000, 49999) if n not in used_ids], 297)
    for k, num in enumerate(order_nums):
        oid = f"ORD-{num}"
        if k == 0:  # featured story from the GIF
            cust, (prod, price), odate, issue = "CUS-1001", PRODUCTS[0], date(2026, 9, 2), "damaged"
        else:
            cust = rng.choice(customers)[0]
            prod, price = rng.choice(PRODUCTS)
            odate = start + timedelta(days=rng.randint(0, 110))
            issue = rng.choice(list(ISSUES)) if rng.random() < 0.38 else None
        qty = 1 if price > 100 else rng.choice([1, 1, 2])
        items = f"{qty}x {prod}"
        carrier, prefix = rng.choice(CARRIERS)
        tracking = prefix + "".join(rng.choice("0123456789ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(14))
        shipped = odate + timedelta(days=rng.randint(1, 3))
        ship_status, delivered = "delivered", shipped + timedelta(days=rng.randint(2, 6))
        if issue == "lost":
            ship_status, delivered = rng.choice(["lost", "exception", "delivered"]), None
        if issue == "late":
            delivered = shipped + timedelta(days=rng.randint(12, 20))
        if odate > date(2026, 9, 20) and issue is None:
            ship_status, delivered = "in_transit", None
        o_status = "delivered" if delivered else "shipped"
        orders.append((oid, cust, odate, o_status, items, round(price * qty, 2)))
        shipments.append((f"SHP-{num}", oid, carrier, tracking, ship_status, shipped, delivered))
        after = delivered or shipped + timedelta(days=5)

        if k == 0:
            convs.append((f"CNV-{num}-1", oid, "chat", date(2026, 9, 6),
                          "Customer: Hi, my dinner set came today and three of the plates are cracked. The outer box "
                          "looked like it had been dropped.\nAgent: So sorry about that! Could you send a couple of "
                          "photos of the plates and the box? We'll make it right."))
            returns.append(("RMA-20931", oid, "Broken on delivery - 3 plates cracked", "requested", date(2026, 9, 6)))
            notes.append((f"NTE-{num}-1", oid, "K. Osei", date(2026, 9, 7),
                          "Photos confirm transit damage on 3 plates, carton crushed. Carrier claim filed. "
                          "Approve refund or replacement once customer picks."))
            continue

        if issue:
            spec = ISSUES[issue]
            p_short = prod.split(" (")[0].split(" - ")[0].lower()
            text = rng.choice(spec["customer"]).format(p=p_short)
            if rng.random() < 0.85:
                ch = rng.choice(["chat", "email", "phone"])
                convs.append((f"CNV-{num}-1", oid, ch, after + timedelta(days=rng.randint(0, 3)),
                              f"Customer: {text}\nAgent: {AGENT_REPLIES[issue]}"))
            if spec["return"] and rng.random() < 0.75:
                returns.append((f"RMA-{rng.randint(10000, 29999)}", oid, rng.choice(spec["return"]),
                                rng.choice(REFUND_BY_ISSUE[issue]), after + timedelta(days=rng.randint(1, 5))))
            if rng.random() < 0.65:
                notes.append((f"NTE-{num}-1", oid, rng.choice(AGENTS), after + timedelta(days=rng.randint(1, 6)),
                              rng.choice(spec["note"])))
        elif rng.random() < 0.15:
            p_short = prod.split(" (")[0].split(" - ")[0].lower()
            convs.append((f"CNV-{num}-1", oid, "chat", odate + timedelta(days=1),
                          f"Customer: {rng.choice(BENIGN_CHATS).format(p=p_short)}\nAgent: {AGENT_REPLIES[None]}"))
    return customers, orders, shipments, returns, convs, notes


def build_docs(customers, orders, shipments, returns, convs, notes):
    cust_name = {c[0]: c[1] for c in customers}
    order = {o[0]: o for o in orders}
    refund = {r[1]: r[3] for r in sorted(returns, key=lambda r: r[4])}
    docs = []

    def add(src, sid, oid, d, title, body):
        o = order[oid]
        docs.append((f"{src}:{sid}", src, oid, o[1], d, refund.get(oid), title, body))

    for oid, cust, odate, status, items, total in orders:
        add("order", oid, oid, odate, f"Order {oid} - {cust_name[cust]}",
            f"Order {oid} for {cust_name[cust]} ({cust}): {items}. Total ${total}. Status {status}.")
    for sid, oid, carrier, trk, st, shipped, deliv in shipments:
        add("shipment", sid, oid, deliv or shipped, f"{carrier} shipment {trk}",
            f"{carrier} tracking {trk} for order {oid}. Shipped {shipped}, status {st}"
            + (f", delivered {deliv}." if deliv else "."))
    for rid, oid, reason, rs, d in returns:
        add("return", rid, oid, d, f"Return {rid} for {oid}", f"Return {rid}: {reason}. Refund {rs}.")
    for cid, oid, ch, d, tr in convs:
        add("conversation", cid, oid, d, f"{ch.title()} about {oid}", tr)
    for nid, oid, author, d, note in notes:
        add("note", nid, oid, d, f"Service note on {oid} by {author}", note)
    return docs


def embed(w: WorkspaceClient, texts: list[str], batch: int = 8) -> list[list[float]]:
    """Embed with a local cache and throttling (pay-per-token endpoints have a low workspace QPS limit)."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [t for t in dict.fromkeys(texts) if t not in cache]
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        resp = w.serving_endpoints.query(name=EMBEDDING_ENDPOINT, input=chunk)
        for d in resp.data:
            cache[chunk[d.index]] = d.embedding
        CACHE.write_text(json.dumps(cache))
        print(f"  embedded {min(i + batch, len(todo))}/{len(todo)} new")
        time.sleep(1)
    return [cache[t] for t in texts]


def main():
    w = WorkspaceClient(profile=PROFILE)
    data = build_data()
    docs = build_docs(*data)
    print({n: len(t) for n, t in zip(["customers", "orders", "shipments", "returns", "conversations", "notes"], data)},
          "docs:", len(docs))

    vectors = embed(w, [f"{d[6]}\n{d[7]}" for d in docs])

    with connect() as conn:
        conn.execute((SQL_DIR / "01_schema.sql").read_text())
        with conn.cursor() as cur:
            customers, orders, shipments, returns, convs, notes = data
            cur.executemany("INSERT INTO retail.customers VALUES (%s,%s,%s,%s)", customers)
            cur.executemany("INSERT INTO retail.orders VALUES (%s,%s,%s,%s,%s,%s)", orders)
            cur.executemany("INSERT INTO retail.shipments VALUES (%s,%s,%s,%s,%s,%s,%s)", shipments)
            cur.executemany("INSERT INTO retail.returns VALUES (%s,%s,%s,%s,%s)", returns)
            cur.executemany("INSERT INTO retail.conversations VALUES (%s,%s,%s,%s,%s)", convs)
            cur.executemany("INSERT INTO retail.service_notes VALUES (%s,%s,%s,%s,%s)", notes)
            cur.executemany(
                """INSERT INTO retail.support_docs
                   (doc_id, source, order_id, customer_id, doc_date, refund_status, title, body, embedding, body_tsv)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector, to_tsvector('english', %s || ' ' || %s))""",
                [(*d, str(v), d[6], d[7]) for d, v in zip(docs, vectors)],
            )
        print("rows loaded; building indexes")
        conn.execute((SQL_DIR / "02_indexes.sql").read_text())
        grants = SQL_DIR / "03_grants.sql"
        if grants.exists():  # tables were recreated, so re-grant the app's service principal
            conn.execute(grants.read_text())
            print("re-applied app grants")
        print(conn.execute("SELECT source, count(*) FROM retail.support_docs GROUP BY 1 ORDER BY 1").fetchall())


if __name__ == "__main__":
    main()
