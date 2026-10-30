"""优惠券与会员折扣回归测试：SPEC-CPN-001 / SPEC-MEM-001。"""

from decimal import Decimal

from shopcalc.discounts import apply_coupon, member_rate
from shopcalc.models import Coupon


def test_coupon_is_not_applied_when_threshold_is_not_reached():
    coupon = Coupon(code="BIG", amount_off=Decimal("50"), min_subtotal=Decimal("200"))
    assert apply_coupon(Decimal("199.99"), coupon) == Decimal("199.99")


def test_coupon_percent_off_is_applied():
    coupon = Coupon(code="PCT20", percent_off=Decimal("0.2"))
    assert apply_coupon(Decimal("100"), coupon) == Decimal("80")


def test_coupon_amount_off_is_applied_after_percent_off():
    coupon = Coupon(code="BOTH", percent_off=Decimal("0.2"), amount_off=Decimal("10"))
    assert apply_coupon(Decimal("100"), coupon) == Decimal("70")


def test_coupon_never_produces_negative_amount():
    coupon = Coupon(code="HUGE", amount_off=Decimal("500"))
    assert apply_coupon(Decimal("100"), coupon) == Decimal("0")


def test_member_rate_for_each_level():
    assert member_rate("silver") == Decimal("0.95")
    assert member_rate("gold") == Decimal("0.90")
    assert member_rate("normal") == Decimal("1")
    assert member_rate("unknown-level") == Decimal("1")
