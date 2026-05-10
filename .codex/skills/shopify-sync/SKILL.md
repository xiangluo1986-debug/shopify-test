# Shopify Sync Skill

Use this skill when working on Shopify order sync, product sync, Shopify API reads, pagination, retry behavior, or sync dashboard / scheduler issues in this aftersales project.

## Safety

- Never read or print Shopify access tokens or `.env`.
- Do not write to Shopify unless the user explicitly asks and confirms the risk.
- Do not delete ShopifyOrder, ShopifyOrderItem, or ShopifyProduct data during debugging.
- Prefer read-only database queries and code inspection first.
- For large syncs, start with a small range such as `--days 1` or `--days 3`.

## REST Pagination

- Shopify REST pagination must use the HTTP `Link` response header.
- Extract only the URL segment with `rel="next"`.
- Continue with `page_info` and `limit=250`.
- Follow-up page requests should only include `limit` and `page_info`.
- Do not parse pagination from the JSON body.
- Do not use a `cursor` parameter for Shopify REST orders/products.
- Keep a `seen_page_info` guard to prevent loops.

## Rate Limits

- On HTTP `429`, read `Retry-After` and wait before retrying.
- If `Retry-After` is missing, wait a small bounded delay.
- Retry 5xx temporary errors with a bounded retry count.
- Do not swallow other 4xx errors.

## Product Sync Rules

- Products are stored locally at variant level in `ShopifyProduct`.
- Compare Shopify product count carefully: local rows are variants, not top-level products.
- Sync should save product and variant identifiers, SKU, title, status, image, timestamps, and variant price.
- Do not skip products just because SKU is empty.
- Product sync must not overwrite manually maintained cost and dimension fields.

## Order Sync Rules

- `fetch_shopify_orders()` should request fields needed by settlement: `tags`, `line_items`, `note`, `note_attributes`, and `total_tip_received`.
- Shenzhen order sync requires exact order tag `ship from china` and a line item / fulfillment order assigned to Shenzhen.
- Save only Shenzhen line items for settlement.
- Do not delete historical Sydney / NULL / non-Shenzhen data during rule changes.
- Existing protected settlement statuses should not have user-entered costs overwritten by sync.

## Matching Order Items to Products

Match order items to `ShopifyProduct` in this order:

1. `shopify_variant_id`
2. `shopify_product_id`
3. `sku`

Even if no match is found, keep snapshots of title, SKU, quantity, price, product ID, and variant ID.

## Manual Verification Commands

Ask before running Docker commands. Common low-risk checks:

```powershell
docker compose exec -T web python manage.py check
docker compose logs --tail=100 scheduler
docker compose exec -T web python manage.py sync_shenzhen_orders --days 1
```

Historical syncs such as 30 or 60 days should be user-confirmed.
