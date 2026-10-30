"""优惠券与会员折扣规则。

规格来源：``specs/settlement_spec.md`` 中的 SPEC-CPN-001 与 SPEC-MEM-001。
"""

from __future__ import annotations

from decimal import Decimal

from .models import Coupon

ZERO = Decimal("0")
ONE = Decimal("1")

#: 会员等级折扣率（SPEC-MEM-001）。
MEMBER_DISCOUNTS: dict[str, Decimal] = {
    "silver": Decimal("0.95"),
    "gold": Decimal("0.90"),
}


def apply_coupon(subtotal: Decimal, coupon: Coupon | None) -> Decimal:
    """按 SPEC-CPN-001 计算优惠券后的商品金额。

    - 优惠券门槛未达成时，商品金额保持不变；
    - ``percent_off`` 为百分比折扣（``0.2`` 表示减免 20%）；
    - ``amount_off`` 为固定减免金额，在百分比折扣之后计算；
    - 结果不小于 0。
    """

    if coupon is None or not coupon.is_applicable(subtotal):
        return subtotal
    total = subtotal
    if coupon.percent_off > ZERO:
        total = total * (ONE - coupon.percent_off)
    if coupon.amount_off > ZERO:
        total = total - coupon.amount_off
    return max(total, ZERO)


def member_rate(member_level: str) -> Decimal:
    """返回会员等级折扣率；普通会员返回 1（SPEC-MEM-001）。"""

    return MEMBER_DISCOUNTS.get(member_level, ONE)
