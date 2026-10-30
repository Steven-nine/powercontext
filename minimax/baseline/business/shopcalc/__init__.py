"""shopcalc —— 订单结算与优惠计算业务工程。

这是一个可运行、可测试的最小业务工程，用于演示 SDD 上下文管理模块
（见 ``minimax/sddctx``）如何把规格、代码与测试组织成开发上下文。
"""

from .models import Coupon, Order, OrderItem
from .pricing import (
    FREE_SHIPPING_THRESHOLD,
    STANDARD_SHIPPING_FEE,
    discounted_subtotal,
    shipping_fee,
    subtotal,
    total,
)

__all__ = (
    "Coupon",
    "FREE_SHIPPING_THRESHOLD",
    "Order",
    "OrderItem",
    "STANDARD_SHIPPING_FEE",
    "discounted_subtotal",
    "shipping_fee",
    "subtotal",
    "total",
)
