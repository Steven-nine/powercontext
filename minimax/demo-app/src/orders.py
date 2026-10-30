"""In-memory orders service used by the SDD demo."""

ORDERS = [
    {"id": 1, "status": "pending", "total": 25.0},
    {"id": 2, "status": "paid", "total": 60.0},
    {"id": 3, "status": "paid", "total": 90.0},
    {"id": 4, "status": "cancelled", "total": 10.0},
]


def list_orders(status=None):
    """Returns orders filtered by status."""

    return [order for order in ORDERS if status is None or order["status"] == status]


def total_revenue(status=None):
    """Returns the sum of totals for the selected orders."""

    return sum(order["total"] for order in list_orders(status))
