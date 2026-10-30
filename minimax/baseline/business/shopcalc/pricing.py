"""商品金额与运费计算。

规格来源：``specs/settlement_spec.md`` 中的 SPEC-PRICE-001 与 SPEC-SHIP-001。
"""

from __future__ import annotations

from decimal import Decimal

from .discounts import apply_coupon, member_rate
from .models import Order

ZERO = Decimal("0")
CENT = Decimal("0.01")

#: 免运费门槛：优惠后商品金额达到该值时免收运费（SPEC-SHIP-001）。
FREE_SHIPPING_THRESHOLD = Decimal("99")
#: 普通地区运费（SPEC-SHIP-001）。
STANDARD_SHIPPING_FEE = Decimal("8")


def subtotal(order: Order) -> Decimal:
    """订单商品小计（未优惠）。"""

    return sum((item.line_total for item in order.items), ZERO)


def discounted_subtotal(order: Order) -> Decimal:
    """优惠后商品金额：先优惠券（SPEC-CPN-001），再会员折扣（SPEC-MEM-001）。"""

    total = apply_coupon(subtotal(order), order.coupon)
    total = total * member_rate(order.member_level)
    return total.quantize(CENT)


def shipping_fee(order: Order) -> Decimal:
    """按 SPEC-SHIP-001 计算运费。

    优惠后商品金额达到免运费门槛时运费为 0，否则收取普通地区运费。
    """

    if discounted_subtotal(order) >= FREE_SHIPPING_THRESHOLD:
        return ZERO
    return STANDARD_SHIPPING_FEE


def total(order: Order) -> Decimal:
    """订单应付金额 = 优惠后商品金额 + 运费。"""

    return discounted_subtotal(order) + shipping_fee(order)
