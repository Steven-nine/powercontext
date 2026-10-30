# 数据库查询记录（seekdb / OceanBase）

- 执行时间：2026-10-30T22:54:32+08:00
- 连接：127.0.0.1:2881/sdd_ctx

## 资料库统计

```sql
SELECT kind, COUNT(*) AS n FROM sdd_doc GROUP BY kind
```

```json
{
  "statement": "SELECT kind, COUNT(*) AS n FROM sdd_doc GROUP BY kind",
  "row_count": 3,
  "rows": [
    {
      "kind": "code",
      "n": 4
    },
    {
      "kind": "spec",
      "n": 1
    },
    {
      "kind": "test",
      "n": 3
    }
  ]
}

```

## 规格条目（用于上下文）

```sql
SELECT entry_id, title, revision FROM sdd_spec_entry ORDER BY entry_id
```

```json
{
  "statement": "SELECT entry_id, title, revision FROM sdd_spec_entry ORDER BY entry_id",
  "row_count": 6,
  "rows": [
    {
      "entry_id": "SPEC-CPN-001",
      "title": "优惠券",
      "revision": 2
    },
    {
      "entry_id": "SPEC-MEM-001",
      "title": "会员折扣",
      "revision": 2
    },
    {
      "entry_id": "SPEC-PRICE-001",
      "title": "商品金额计算",
      "revision": 2
    },
    {
      "entry_id": "SPEC-SETTLE-001",
      "title": "订单应付金额",
      "revision": 2
    },
    {
      "entry_id": "SPEC-SHIP-001",
      "title": "普通地区运费",
      "revision": 2
    },
    {
      "entry_id": "SPEC-SHIP-002",
      "title": "偏远地区运费",
      "revision": 2
    }
  ]
}

```

## 倒排索引命中（示例：shipping_fee / 中文单字 运、费）

```sql
SELECT t.term, t.doc_id, t.field, t.tf FROM sdd_term t WHERE t.term IN ('shipping_fee', '运', '费') ORDER BY t.tf DESC LIMIT 20
```

```json
{
  "statement": "SELECT t.term, t.doc_id, t.field, t.tf FROM sdd_term t WHERE t.term IN ('shipping_fee', '运', '费') ORDER BY t.tf DESC LIMIT 20",
  "row_count": 17,
  "rows": [
    {
      "term": "运",
      "doc_id": "settlement-spec",
      "field": "spec",
      "tf": 15
    },
    {
      "term": "费",
      "doc_id": "settlement-spec",
      "field": "spec",
      "tf": 15
    },
    {
      "term": "运",
      "doc_id": "settlement-spec",
      "field": "spec_entry",
      "tf": 12
    },
    {
      "term": "费",
      "doc_id": "settlement-spec",
      "field": "spec_entry",
      "tf": 12
    },
    {
      "term": "费",
      "doc_id": "business/tests/test_shipping.py",
      "field": "test",
      "tf": 9
    },
    {
      "term": "shipping_fee",
      "doc_id": "business/tests/test_shipping.py",
      "field": "test",
      "tf": 9
    },
    {
      "term": "费",
      "doc_id": "business/shopcalc/pricing.py",
      "field": "code",
      "tf": 9
    },
    {
      "term": "运",
      "doc_id": "business/shopcalc/pricing.py",
      "field": "code",
      "tf": 9
    },
    {
      "term": "运",
      "doc_id": "business/tests/test_shipping.py",
      "field": "test",
      "tf": 9
    },
    {
      "term": "费",
      "doc_id": "business/shopcalc/pricing.py",
      "field": "symbol",
      "tf": 5
    },
    {
      "term": "运",
      "doc_id": "business/shopcalc/pricing.py",
      "field": "symbol",
      "tf": 5
    },
    {
      "term": "费",
      "doc_id": "business/tests/test_shipping.py",
      "field": "symbol",
      "tf": 4
    },
    {
      "term": "运",
      "doc_id": "business/tests/test_shipping.py",
      "field": "symbol",
      "tf": 4
    },
    {
      "term": "shipping_fee",
      "doc_id": "business/shopcalc/pricing.py",
      "field": "code",
      "tf": 2
    },
    {
      "term": "shipping_fee",
      "doc_id": "business/shopcalc/pricing.py",
      "field": "symbol",
      "tf": 2
    },
    {
      "term": "shipping_fee",
      "doc_id": "business/shopcalc/__init__.py",
      "field": "code",
      "tf": 2
    },
    {
      "term": "运",
      "doc_id": "business/shopcalc/__init__.py",
      "field": "code",
      "tf": 1
    }
  ]
}

```

## 代码符号（上下文定位到函数与行号）

```sql
SELECT s.name, s.kind, s.line_start, s.line_end, s.cited_specs, d.path FROM sdd_symbol s JOIN sdd_doc d ON d.doc_id = s.doc_id WHERE d.kind = 'code' ORDER BY s.line_start
```

```json
{
  "statement": "SELECT s.name, s.kind, s.line_start, s.line_end, s.cited_specs, d.path FROM sdd_symbol s JOIN sdd_doc d ON d.doc_id = s.doc_id WHERE d.kind = 'code' ORDER BY s.line_start",
  "row_count": 12,
  "rows": [
    {
      "name": "OrderItem",
      "kind": "class",
      "line_start": 12,
      "line_end": 27,
      "cited_specs": "",
      "path": "business/shopcalc/models.py"
    },
    {
      "name": "OrderItem.__post_init__",
      "kind": "method",
      "line_start": 19,
      "line_end": 23,
      "cited_specs": "",
      "path": "business/shopcalc/models.py"
    },
    {
      "name": "apply_coupon",
      "kind": "function",
      "line_start": 22,
      "line_end": 38,
      "cited_specs": "SPEC-CPN-001",
      "path": "business/shopcalc/discounts.py"
    },
    {
      "name": "subtotal",
      "kind": "function",
      "line_start": 22,
      "line_end": 25,
      "cited_specs": "",
      "path": "business/shopcalc/pricing.py"
    },
    {
      "name": "OrderItem.line_total",
      "kind": "method",
      "line_start": 26,
      "line_end": 27,
      "cited_specs": "",
      "path": "business/shopcalc/models.py"
    },
    {
      "name": "discounted_subtotal",
      "kind": "function",
      "line_start": 28,
      "line_end": 33,
      "cited_specs": "SPEC-CPN-001,SPEC-MEM-001",
      "path": "business/shopcalc/pricing.py"
    },
    {
      "name": "Coupon",
      "kind": "class",
      "line_start": 31,
      "line_end": 42,
      "cited_specs": "",
      "path": "business/shopcalc/models.py"
    },
    {
      "name": "shipping_fee",
      "kind": "function",
      "line_start": 36,
      "line_end": 44,
      "cited_specs": "SPEC-SHIP-001",
      "path": "business/shopcalc/pricing.py"
    },
    {
      "name": "Coupon.is_applicable",
      "kind": "method",
      "line_start": 39,
      "line_end": 42,
      "cited_specs": "",
      "path": "business/shopcalc/models.py"
    },
    {
      "name": "member_rate",
      "kind": "function",
      "line_start": 41,
      "line_end": 44,
      "cited_specs": "SPEC-MEM-001",
      "path": "business/shopcalc/discounts.py"
    },
    {
      "name": "Order",
      "kind": "class",
      "line_start": 46,
      "line_end": 53,
      "cited_specs": "",
      "path": "business/shopcalc/models.py"
    },
    {
      "name": "total",
      "kind": "function",
      "line_start": 47,
      "line_end": 50,
      "cited_specs": "",
      "path": "business/shopcalc/pricing.py"
    }
  ]
}

```

## 文档修订历史（规格更新可见）

```sql
SELECT doc_id, revision, version, content_sha256 FROM sdd_doc_revision ORDER BY doc_id, revision
```

```json
{
  "statement": "SELECT doc_id, revision, version, content_sha256 FROM sdd_doc_revision ORDER BY doc_id, revision",
  "row_count": 9,
  "rows": [
    {
      "doc_id": "business/shopcalc/__init__.py",
      "revision": 1,
      "version": "",
      "content_sha256": "2a9db72629c7b3bb0c631dd4d772fe588e7379b43a7f3c95f2e44f818febb0d8"
    },
    {
      "doc_id": "business/shopcalc/discounts.py",
      "revision": 1,
      "version": "",
      "content_sha256": "e970c237cec1fb56fc9eafa638e805ee7bfbb139ca475be50ce2bef6ef739172"
    },
    {
      "doc_id": "business/shopcalc/models.py",
      "revision": 1,
      "version": "",
      "content_sha256": "a4fc08c241ac2b455aeeaedd7d20d50b70b43c8cc7972959bbd30f1f0f01e4ca"
    },
    {
      "doc_id": "business/shopcalc/pricing.py",
      "revision": 1,
      "version": "",
      "content_sha256": "e83cd9d921969c6f72e6494d283e686db3523899e6e1e1a18e879aaf40baaf97"
    },
    {
      "doc_id": "business/tests/test_discounts.py",
      "revision": 1,
      "version": "",
      "content_sha256": "cd09e76db8bfd57aecea939e34408e81fe7c2a2e28e50f4ed6d9fd48675eef18"
    },
    {
      "doc_id": "business/tests/test_pricing.py",
      "revision": 1,
      "version": "",
      "content_sha256": "38add197317b1cf5b3263289f76aa0e08fd02dcb11701cea8764bcab28bb5ddd"
    },
    {
      "doc_id": "business/tests/test_shipping.py",
      "revision": 1,
      "version": "",
      "content_sha256": "2136a43fe906431bee6c7d3bff1555fc24f7efaa42d52c4fccc875d8add70503"
    },
    {
      "doc_id": "settlement-spec",
      "revision": 1,
      "version": "1.1",
      "content_sha256": "1d34ed3c6a63604731bb0f807f2c1c041964c5a6453e764d28b427727a567c01"
    },
    {
      "doc_id": "settlement-spec",
      "revision": 2,
      "version": "1.2",
      "content_sha256": "48fd67ba93ad307971d11bf81274295ae53ace389462ba061a4732969a0d5c4a"
    }
  ]
}

```
