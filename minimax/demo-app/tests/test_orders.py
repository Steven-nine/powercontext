from orders import list_orders, total_revenue


def test_all_orders():
    assert [order["id"] for order in list_orders()] == [1, 2, 3, 4]


def test_filter_status():
    assert [order["id"] for order in list_orders(status="paid")] == [2, 3]


def test_unknown_status_returns_empty():
    assert list_orders(status="refunded") == []


def test_stable_order():
    assert [order["id"] for order in list_orders(status="paid")] == [2, 3]


def test_total_revenue():
    assert total_revenue() == 185.0
    assert total_revenue(status="paid") == 150.0


def test_filter_min_total():
    assert [order["id"] for order in list_orders(min_total=60)] == [2, 3]


def test_filter_status_and_min_total():
    assert [order["id"] for order in list_orders(status="paid", min_total=70)] == [3]
