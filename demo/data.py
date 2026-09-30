"""Small, synthetic customer-support dataset for the demo."""

DEMO_CASES = [
    {
        "case_id": "CASE-001",
        "customer_id": "customer-a",
        "order_id": "ORDER-ALPHA",
        "product_id": "SHOE-BLUE-RUN",
        "product_name": "Blue running shoes",
        "status": "investigating",
        "order_date": "2026-09-20",
        "customer_message": "The tracking says delivered, but nothing came. The package is missing.",
        "support_notes": "Carrier scan says delivered. Customer reports non-receipt; open delivery investigation.",
    },
    {
        "case_id": "CASE-002",
        "customer_id": "customer-a",
        "order_id": "ORDER-BRAVO",
        "product_id": "SHOE-BLUE-RUN",
        "product_name": "Blue running shoes",
        "status": "open",
        "order_date": "2026-09-22",
        "customer_message": "My blue running shoes arrived damaged and the sole is broken.",
        "support_notes": "Photo received. Replacement eligibility is being reviewed.",
    },
    {
        "case_id": "CASE-003",
        "customer_id": "customer-b",
        "order_id": "ORDER-CHARLIE",
        "product_id": "JACKET-RAIN",
        "product_name": "Rain jacket",
        "status": "resolved",
        "order_date": "2026-09-18",
        "customer_message": "The tracking page says delivered, but the parcel was not at my door.",
        "support_notes": "Replacement shipped and case closed.",
    },
    {
        "case_id": "CASE-004",
        "customer_id": "customer-b",
        "order_id": "ORDER-DELTA",
        "product_id": "HEADPHONES-WIRELESS",
        "product_name": "Wireless headphones",
        "status": "open",
        "order_date": "2026-09-21",
        "customer_message": "The headphones connect, but the left side has no sound.",
        "support_notes": "Troubleshooting steps sent; awaiting customer response.",
    },
    {
        "case_id": "CASE-005",
        "customer_id": "customer-a",
        "order_id": "ORDER-ECHO",
        "product_id": "COFFEE-MAKER",
        "product_name": "Compact coffee maker",
        "status": "open",
        "order_date": "2026-09-23",
        "customer_message": "I received the wrong item instead of the coffee maker I ordered.",
        "support_notes": "Warehouse pick error suspected; return label requested.",
    },
]


def searchable_text(case):
    """Text fields that would be embedded and tokenized in a real application."""
    return " ".join(
        [
            case["order_id"],
            case["product_id"],
            case["product_name"],
            case["customer_message"],
            case["support_notes"],
        ]
    )
