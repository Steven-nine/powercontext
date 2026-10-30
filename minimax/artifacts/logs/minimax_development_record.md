# MiniMax 开发记录（本次任务）

- 接口：`POST https://api.minimax.cn/v1/chat/completions`（OpenAI 兼容）
- 模型：`MiniMax-M3.1-Flash`
- 调用次数：1
- 记录生成时间：2026-10-30T22:54:18+08:00

## 调用汇总

| call_id | model | response_id | finish_reason | prompt_tokens | completion_tokens | reasoning_tokens |
|---|---|---|---|---|---|---|
| call-20261030T145408-001 | MiniMax-M3.1-Flash | 0733e29033ae12b7720b8ce5682e75ee | stop | 3866 | 778 | 319 |

## call-20261030T145408-001 · 请求（role=user）

```
# 开发任务

实现 SPEC-SHIP-002 偏远地区运费规则 shipping_fee：新疆、西藏、内蒙古订单固定收取 ¥20 运费，且优先于满 99 免运费规则

任务点名的规格条目：SPEC-SHIP-002


# 适用的规格条目

## SPEC-SHIP-002 偏远地区运费
来源：specs/settlement_spec.md（规格版本 1.2）

- 收货地区属于 **新疆、西藏、内蒙古** 时，运费固定为 **¥20.00**。
- 该规则 **优先于** SPEC-SHIP-001：即使优惠后商品金额满 ¥99.00，仍收取 ¥20.00 运费。
- 运费金额不计入商品金额，也不参与免运费门槛的计算。

## SPEC-CPN-001 优惠券
来源：specs/settlement_spec.md（规格版本 1.2）

- 优惠券门槛 `min_subtotal` 未达成时，优惠券不生效，商品金额保持不变。
- `percent_off` 为百分比折扣，`0.2` 表示减免 20%；`amount_off` 为固定减免金额。
- 固定减免在百分比折扣之后计算；优惠后商品金额不得小于 0。

## SPEC-SHIP-001 普通地区运费
来源：specs/settlement_spec.md（规格版本 1.2）

- 优惠后商品金额 **大于等于 ¥99.00** 时免运费，运费为 ¥0.00。
- 否则收取普通地区运费 **¥8.00**。
- 免运费门槛只看优惠后商品金额，**不包含运费本身**。

## SPEC-SETTLE-001 订单应付金额
来源：specs/settlement_spec.md（规格版本 1.2）

- 订单应付金额 = 优惠后商品金额 + 运费。

## SPEC-PRICE-001 商品金额计算
来源：specs/settlement_spec.md（规格版本 1.2）

- 订单商品小计 = 所有订单行 `unit_price × quantity` 之和。
- 优惠后商品金额先应用优惠券（SPEC-CPN-001），再应用会员折扣（SPEC-MEM-001）。
- 优惠后商品金额四舍五入保留两位小数。

## SPEC-MEM-001 会员折扣
来源：specs/settlement_spec.md（规格版本 1.2）

- 会员等级 `silver` 折扣率 0.95，`gold` 折扣率 0.90，普通会员折扣率 1。
- 会员折扣在优惠券之后计算。


# 需要修改的代码

## business/shopcalc/pricing.py
```python
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

```

## business/shopcalc/discounts.py
```python
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

```

## business/shopcalc/models.py
```python
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

```


# 用于验证的测试

## business/tests/test_shipping.py（目标测试）
```python
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

```

## business/tests/test_discounts.py（回归测试）
```python
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

```

## business/tests/test_pricing.py（回归测试）
```python
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

```

## business/tests/test_shipping.py（目标测试）
```python
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

```


# 已有任务状态

- 已完成：（无）

- 待办：（无）

- 已有验证结果：（无）


# 输出要求
请实现上述规格，使目标测试全部通过，同时保证回归测试继续通过。
只输出 unified diff，路径相对于仓库根目录（例如 `diff --git a/minimax/business/shopcalc/pricing.py b/minimax/business/shopcalc/pricing.py`）。

```

## call-20261030T145408-001 · 响应

- response_id：`0733e29033ae12b7720b8ce5682e75ee`
- finish_reason：`stop`
- usage：`{"total_tokens": 4644, "total_characters": 0, "prompt_tokens": 3866, "completion_tokens": 778, "completion_tokens_details": {"reasoning_tokens": 319}, "prompt_tokens_details": {"cached_tokens": 3840}}`

```diff
diff --git a/minimax/business/shopcalc/pricing.py b/minimax/business/shopcalc/pricing.py
index 76f6e0b..1a4d51c 100644
--- a/minimax/business/shopcalc/pricing.py
+++ b/minimax/business/shopcalc/pricing.py
@@ -1,6 +1,6 @@
 """商品金额与运费计算。
 
-规格来源：``specs/settlement_spec.md`` 中的 SPEC-PRICE-001 与 SPEC-SHIP-001。
+规格来源：``specs/settlement_spec.md`` 中的 SPEC-PRICE-001、SPEC-SHIP-001 与 SPEC-SHIP-002。
 """
 
 from __future__ import annotations
@@ -12,8 +12,13 @@ CENT = Decimal("0.01")
 FREE_SHIPPING_THRESHOLD = Decimal("99")
 #: 普通地区运费（SPEC-SHIP-001）。
 STANDARD_SHIPPING_FEE = Decimal("8")
+#: 偏远地区（SPEC-SHIP-002）。
+REMOTE_REGIONS = frozenset({"新疆", "西藏", "内蒙古"})
+#: 偏远地区固定运费，优先于普通地区免运费规则（SPEC-SHIP-002）。
+REMOTE_SHIPPING_FEE = Decimal("20")
 
 
 def subtotal(order: Order) -> Decimal:
@@ -29,12 +34,16 @@ def discounted_subtotal(order: Order) -> Decimal:
 
 
 def shipping_fee(order: Order) -> Decimal:
-    """按 SPEC-SHIP-001 计算运费。
+    """按 SPEC-SHIP-001 与 SPEC-SHIP-002 计算运费。
 
-    优惠后商品金额达到免运费门槛时运费为 0，否则收取普通地区运费。
+    偏远地区固定收取 20 元运费；其他地区在优惠后商品金额达到免运费门槛时
+    免收运费，否则收取普通地区运费。
     """
 
+    if order.region in REMOTE_REGIONS:
+        return REMOTE_SHIPPING_FEE
     if discounted_subtotal(order) >= FREE_SHIPPING_THRESHOLD:
         return ZERO
     return STANDARD_SHIPPING_FEE
*** End Patch
```
