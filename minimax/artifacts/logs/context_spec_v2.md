# 开发上下文：实现 SPEC-SHIP-002 偏远地区运费规则 shipping_fee：新疆、西藏、内蒙古订单固定收取 ¥20 运费，且优先于满 99 免运费规则

- 生成时间：2026-10-30T22:54:07+08:00
- 任务点名的规格条目：SPEC-SHIP-002
- PowerContext Scope：scp_6vz8jsv07e5r9ka7symnn1tfjq

## 1. 适用的规格条目

- **SPEC-SHIP-002** 偏远地区运费  
  - 来源：`specs/settlement_spec.md`（规格版本 1.2，修订 2）
  - 内容：- 收货地区属于 **新疆、西藏、内蒙古** 时，运费固定为 **¥20.00**。
- 该规则 **优先于** SPEC-SHIP-001：即使优惠后商品金额满 ¥99.00，仍收取 ¥20.00 运费。
- 运费金额不计入商品金额，也不参与免运费门槛的计算。
- **SPEC-CPN-001** 优惠券  
  - 来源：`specs/settlement_spec.md`（规格版本 1.2，修订 2）
  - 内容：- 优惠券门槛 `min_subtotal` 未达成时，优惠券不生效，商品金额保持不变。
- `percent_off` 为百分比折扣，`0.2` 表示减免 20%；`amount_off` 为固定减免金额。
- 固定减免在百分比折扣之后计算；优惠后商品金额不得小于 0。
- **SPEC-SHIP-001** 普通地区运费  
  - 来源：`specs/settlement_spec.md`（规格版本 1.2，修订 2）
  - 内容：- 优惠后商品金额 **大于等于 ¥99.00** 时免运费，运费为 ¥0.00。
- 否则收取普通地区运费 **¥8.00**。
- 免运费门槛只看优惠后商品金额，**不包含运费本身**。
- **SPEC-SETTLE-001** 订单应付金额  
  - 来源：`specs/settlement_spec.md`（规格版本 1.2，修订 2）
  - 内容：- 订单应付金额 = 优惠后商品金额 + 运费。
- **SPEC-PRICE-001** 商品金额计算  
  - 来源：`specs/settlement_spec.md`（规格版本 1.2，修订 2）
  - 内容：- 订单商品小计 = 所有订单行 `unit_price × quantity` 之和。
- 优惠后商品金额先应用优惠券（SPEC-CPN-001），再应用会员折扣（SPEC-MEM-001）。
- 优惠后商品金额四舍五入保留两位小数。
- **SPEC-MEM-001** 会员折扣  
  - 来源：`specs/settlement_spec.md`（规格版本 1.2，修订 2）
  - 内容：- 会员等级 `silver` 折扣率 0.95，`gold` 折扣率 0.90，普通会员折扣率 1。
- 会员折扣在优惠券之后计算。

## 2. 需要修改的代码

- `business/shopcalc/pricing.py` → shipping_fee  
  - 签名：shipping_fee(order)
  - 行号：36-44
- `business/shopcalc/discounts.py` → apply_coupon  
  - 签名：apply_coupon(subtotal, coupon)
  - 行号：22-38
- `business/shopcalc/pricing.py` → total  
  - 签名：total(order)
  - 行号：47-50
- `business/shopcalc/discounts.py` → member_rate  
  - 签名：member_rate(member_level)
  - 行号：41-44
- `business/shopcalc/pricing.py` → discounted_subtotal  
  - 签名：discounted_subtotal(order)
  - 行号：28-33
- `business/shopcalc/pricing.py` → subtotal  
  - 签名：subtotal(order)
  - 行号：22-25
- `business/shopcalc/models.py` → Coupon  
  - 签名：class Coupon
  - 行号：31-42
- `business/shopcalc/models.py` → Order  
  - 签名：class Order
  - 行号：46-53
- `business/shopcalc/models.py` → OrderItem  
  - 签名：class OrderItem
  - 行号：12-27
- `business/shopcalc/models.py` → Coupon.is_applicable  
  - 签名：Coupon.is_applicable(self, subtotal)
  - 行号：39-42

## 3. 用于验证的测试

- [目标测试] `business/tests/test_shipping.py`::test_remote_region_shipping_fee_is_fixed_twenty_yuan  
  - 说明：偏远地区运费固定 ¥20.00（SPEC-SHIP-002）。
- [目标测试] `business/tests/test_shipping.py`::test_remote_region_shipping_fee_overrides_free_shipping_threshold  
  - 说明：SPEC-SHIP-002 优先于 SPEC-SHIP-001：满 ¥99 仍收 ¥20 运费。
- [回归测试] `business/tests/test_discounts.py`::test_coupon_amount_off_is_applied_after_percent_off  
- [回归测试] `business/tests/test_discounts.py`::test_coupon_is_not_applied_when_threshold_is_not_reached  
- [回归测试] `business/tests/test_discounts.py`::test_coupon_never_produces_negative_amount  
- [回归测试] `business/tests/test_discounts.py`::test_coupon_percent_off_is_applied  
- [回归测试] `business/tests/test_discounts.py`::test_member_rate_for_each_level  
- [回归测试] `business/tests/test_pricing.py`::test_discounted_subtotal_applies_coupon_before_member_discount  
- [回归测试] `business/tests/test_pricing.py`::test_order_item_rejects_negative_quantity  
- [回归测试] `business/tests/test_pricing.py`::test_subtotal_sums_all_order_lines  
- [回归测试] `business/tests/test_pricing.py`::test_total_is_discounted_subtotal_plus_shipping_fee  
- [回归测试] `business/tests/test_shipping.py`::test_non_remote_region_keeps_standard_shipping_fee  
- [回归测试] `business/tests/test_shipping.py`::test_shipping_fee_is_eight_yuan_when_subtotal_below_threshold  
- [回归测试] `business/tests/test_shipping.py`::test_shipping_fee_is_not_counted_into_the_free_shipping_threshold  
  - 说明：运费不参与免运费门槛计算：门槛只看优惠后商品金额。
- [回归测试] `business/tests/test_shipping.py`::test_shipping_fee_uses_discounted_subtotal_not_raw_subtotal  
- [回归测试] `business/tests/test_shipping.py`::test_shipping_is_free_when_subtotal_reaches_threshold  

## 4. 任务状态（PowerContext）

- 已完成事项：0 条
- 待办事项：0 条
- 已有验证结果：0 条
