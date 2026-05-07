#!/usr/bin/env python
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from shopify_sync.models import ShopifyProduct, ShopifyOrderItem, ShopifyInstallation
from shopify_sync.sync_helpers import sync_products_for_installation, sync_shenzhen_orders_for_installation

# Run product sync
print("=" * 60)
print("RUNNING PRODUCT SYNC...")
print("=" * 60)
try:
    inst = ShopifyInstallation.objects.get(shop='kidstoylover.myshopify.com')
    result = sync_products_for_installation(inst)
    print("SYNC_RESULT:")
    for k, v in result.items():
        print(f"  {k}: {v}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

# Check product stats
print("\n" + "=" * 60)
print("PRODUCT STATS AFTER SYNC")
print("=" * 60)
print("total_products:", ShopifyProduct.objects.count())
print("products_with_blank_sku:", ShopifyProduct.objects.filter(sku='').count())
print("products_with_null_sku:", ShopifyProduct.objects.filter(sku__isnull=True).count())

# Run order sync
print("\n" + "=" * 60)
print("RUNNING ORDER SYNC...")
print("=" * 60)
try:
    result = sync_shenzhen_orders_for_installation(inst)
    print("ORDER_SYNC_RESULT:")
    for k, v in result.items():
        if k != "errors":
            print(f"  {k}: {v}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

# Check matching stats
print("\n" + "=" * 60)
print("ORDER ITEM MATCHING STATS")
print("=" * 60)
unmatched_variant = ShopifyOrderItem.objects.filter(matched_product__isnull=True, shopify_variant_id__isnull=False)
unmatched_product = ShopifyOrderItem.objects.filter(matched_product__isnull=True, shopify_variant_id__isnull=True, shopify_product_id__isnull=False)
unmatched_neither = ShopifyOrderItem.objects.filter(matched_product__isnull=True, shopify_variant_id__isnull=True, shopify_product_id__isnull=True)
matched = ShopifyOrderItem.objects.filter(matched_product__isnull=False)

print("total_order_items:", ShopifyOrderItem.objects.count())
print("matched_items:", matched.count())
print("unmatched_by_variant_id:", unmatched_variant.count())
print("unmatched_by_product_id:", unmatched_product.count())
print("unmatched_no_ids:", unmatched_neither.count())

print("\nUNMATCHED_SAMPLES (variant_id):")
for item in unmatched_variant[:10]:
    print(f"  order={item.order.order_number} sku={item.sku} product_id={item.shopify_product_id} variant_id={item.shopify_variant_id} title={item.product_title}")

print("\nUNMATCHED_SAMPLES (product_id):")
for item in unmatched_product[:10]:
    print(f"  order={item.order.order_number} sku={item.sku} product_id={item.shopify_product_id} variant_id={item.shopify_variant_id} title={item.product_title}")
