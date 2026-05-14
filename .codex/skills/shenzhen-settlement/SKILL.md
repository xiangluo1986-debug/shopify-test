---
name: shenzhen-settlement
description: Work on Shenzhen warehouse settlement, cost, profit, and payment workflows.
---

# Shenzhen Settlement Skill

Use this skill when working on Shenzhen warehouse settlement, packages, costs, profit, payment workflow, CSV export, or Shopify Order admin settlement UI.

## Scope and Permissions

- Settlement ERP only concerns Shenzhen warehouse items.
- Shenzhen Warehouse users must not see Admin / Finance profit data.
- Admin / Finance can see profit, exchange rate, low-margin alerts, and payment workflow actions.
- Shenzhen Warehouse can maintain costs before final finance/payment lock.

## Item Scope

Only include:

```text
ShopifyOrderItem.fulfillment_location == "shenzhen"
```

Exclude from settlement display, totals, cost completion, and CSV:

- Sydney items
- NULL location items
- other non-Shenzhen items

Do not delete historical non-Shenzhen rows just to hide them from ERP.

## Cost Formulas

For an item without package:

```text
item total = locked_product_cost_rmb * quantity + locked_shipping_cost_rmb - handling_fee_rmb
```

For package-level settlement:

```text
package total = package Shenzhen product costs + package.shipping_cost_rmb - package.ordering_cost_rmb
```

Order total must support both package-assigned items and unassigned item-level totals.

`handling_fee_rmb` means ordering cost / order placement cost and is a deduction.

## Package Workflow

1. Add package rows with package number, package shipping cost, package ordering cost, and note.
2. Save the order.
3. Assign Shenzhen order items to the saved package.
4. Recalculate or confirm costs.

Do not require package creation for simple one-product orders.

## Product Cost Rules

- Shenzhen Warehouse can edit order item product cost while order is editable.
- If matched product default cost is empty or zero, first valid item cost can fill `ShopifyProduct.product_cost_rmb`.
- If product default cost already exists, only overwrite it when the user chooses "update product default cost".
- Every product cost change should create `ShopifyProductCostHistory`.
- Do not overwrite manually maintained product cost from product sync.

## Profit Rules

Profit is Admin / Finance only.

Profit is in AUD and should account for:

- Shenzhen item revenue only
- Shopify confirmed tips via `total_tip_received`
- 2% payment fee deduction
- PL note ordering cost
- Shenzhen settlement cost converted using maintained AUD/CNY exchange rate

Do not count Sydney / other warehouse revenue as Shenzhen revenue.

For 100% off aftersales replacement orders, cap Shenzhen revenue by actual Shopify order total.

Only explicit Shopify tips should be counted as additional Shenzhen revenue. Other order-level differences should not automatically enter Shenzhen revenue.

Low-margin alert:

- If profit rate is below 35%, Admin / Finance should see recommended AUD revenue targets for 35% and 40% profit.
- Shenzhen Warehouse must not see this data.

## PL Note Rules

- Parse only the first Shopify order note line starting with `PL`.
- `PL` with no number means a small link; current estimate is A$1.60.
- `PL 8.50` means A$8.50 ordering cost.
- Do not auto-write PL values into `handling_fee_rmb` unless explicitly requested.

## Payment Workflow

Typical settlement statuses:

- `pending_warehouse`
- `warehouse_fulfilled`
- `cost_confirmed` means Shenzhen confirmed and waiting for Admin / Finance
- `pending_payment`
- `payment_submitted`
- `paid`

Shenzhen confirms first. Admin / Finance confirms after Shenzhen. Do not allow skipping the sequence.

## Validation

Ask before running Docker commands:

```powershell
docker compose exec -T web python manage.py check
```

Migrations or bulk cost backfills require explicit user confirmation.
