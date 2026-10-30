"""商品金额与应付金额回归测试：SPEC-PRICE-001 / SPEC-SETTLE-001。"""

from decimal import Decimal

from shopcalc.models import Coupon, Order, OrderItem
from shopcalc.pricing import discounted_subtotal, subtotal, total


def test_subtotal_sums_all_order_lines():
    order = Order(
        order_id="O-2001",
        items=(
            OrderItem(sku="SKU-A", unit_price=Decimal("19.90"), quantity=2),
            OrderItem(sku="SKU-B", unit_price=Decimal("5.00"), quantity=3),
        ),
    )
    assert subtotal(order) == Decimal("54.80")


def test_discounted_subtotal_applies_coupon_before_member_discount():
    order = Order(
        order_id="O-2002",
        items=(OrderItem(sku="SKU-A", unit_price=Decimal("200"), quantity=1),),
        coupon=Coupon(code="PCT20", percent_off=Decimal("0.2")),
        member_level="silver",
    )
    # 200 → 优惠券 8 折 → 160 → 会员 0.95 → 152.00
    assert discounted_subtotal(order) == Decimal("152.00")


def test_total_is_discounted_subtotal_plus_shipping_fee():
    order = Order(
        order_id="O-2003",
        items=(OrderItem(sku="SKU-A", unit_price=Decimal("30"), quantity=1),),
    )
    assert total(order) == Decimal("38.00")


def test_order_item_rejects_negative_quantity():
    import pytest

    with pytest.raises(ValueError):
        OrderItem(sku="SKU-A", unit_price=Decimal("1"), quantity=-1)
