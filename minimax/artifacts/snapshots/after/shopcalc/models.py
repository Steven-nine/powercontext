"""订单结算领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal("0")


@dataclass(frozen=True)
class OrderItem:
    """订单行：单价与数量。"""

    sku: str
    unit_price: Decimal
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise ValueError("quantity must not be negative")
        if self.unit_price < ZERO:
            raise ValueError("unit_price must not be negative")

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass(frozen=True)
class Coupon:
    """优惠券：满减、折扣或二者组合。"""

    code: str
    amount_off: Decimal = ZERO
    percent_off: Decimal = ZERO
    min_subtotal: Decimal = ZERO

    def is_applicable(self, subtotal: Decimal) -> bool:
        """门槛判断：商品金额达到 ``min_subtotal`` 时优惠券才可使用。"""

        return subtotal >= self.min_subtotal


@dataclass(frozen=True)
class Order:
    """订单聚合根。"""

    order_id: str
    items: tuple[OrderItem, ...] = ()
    region: str = ""
    coupon: Coupon | None = None
    member_level: str = "normal"
