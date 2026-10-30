"""运费规格测试：SPEC-SHIP-001（普通地区）与 SPEC-SHIP-002（偏远地区）。"""

from decimal import Decimal

import pytest

from shopcalc.models import Coupon, Order, OrderItem
from shopcalc.pricing import shipping_fee, total

REMOTE_REGIONS = ("新疆", "西藏", "内蒙古")


def make_order(amount: str, region: str = "") -> Order:
    """构造单行订单，``amount`` 为单价。"""

    return Order(
        order_id="O-1001",
        items=(OrderItem(sku="SKU-1", unit_price=Decimal(amount), quantity=1),),
        region=region,
    )


# --- SPEC-SHIP-001 普通地区运费（既有行为，回归） ---

def test_shipping_is_free_when_subtotal_reaches_threshold():
    assert shipping_fee(make_order("99")) == Decimal("0")


def test_shipping_fee_is_eight_yuan_when_subtotal_below_threshold():
    assert shipping_fee(make_order("88.50")) == Decimal("8")


def test_shipping_fee_uses_discounted_subtotal_not_raw_subtotal():
    discounted = Order(
        order_id="O-1002",
        items=(OrderItem(sku="SKU-1", unit_price=Decimal("120"), quantity=1),),
        coupon=Coupon(code="SAVE-30", amount_off=Decimal("30")),
    )
    plain = Order(
        order_id="O-1003",
        items=(OrderItem(sku="SKU-1", unit_price=Decimal("120"), quantity=1),),
    )
    # 优惠券后只剩 90 元，低于 99 元门槛 → 收 8 元运费
    assert shipping_fee(discounted) == Decimal("8")
    # 未使用优惠券 → 满 99 免运费
    assert shipping_fee(plain) == Decimal("0")


def test_shipping_fee_is_not_counted_into_the_free_shipping_threshold():
    """运费不参与免运费门槛计算：门槛只看优惠后商品金额。"""

    order = make_order("99")
    assert shipping_fee(order) == Decimal("0")
    assert total(order) == Decimal("99")


def test_non_remote_region_keeps_standard_shipping_fee():
    assert shipping_fee(make_order("50", region="广东")) == Decimal("8")


# --- SPEC-SHIP-002 偏远地区运费（本次任务新增的目标行为） ---

@pytest.mark.parametrize("region", REMOTE_REGIONS)
def test_remote_region_shipping_fee_is_fixed_twenty_yuan(region):
    """偏远地区运费固定 ¥20.00（SPEC-SHIP-002）。"""

    assert shipping_fee(make_order("50", region=region)) == Decimal("20")


@pytest.mark.parametrize("region", REMOTE_REGIONS)
def test_remote_region_shipping_fee_overrides_free_shipping_threshold(region):
    """SPEC-SHIP-002 优先于 SPEC-SHIP-001：满 ¥99 仍收 ¥20 运费。"""

    assert shipping_fee(make_order("500", region=region)) == Decimal("20")
