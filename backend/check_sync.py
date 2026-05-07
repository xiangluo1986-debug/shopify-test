#!/usr/bin/env python
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from shopify_sync.models import ShopifyProduct, ShopifyOrderItem, ShopifyInstallation
from shopify_sync.sync_helpers import sync_products_for_installation

# Run product sync
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

# Check before/after stats
print("\nSTATS_AFTER_SYNC:")
print("total_products:", ShopifyProduct.objects.count())
print("products_with_blank_sku:", ShopifyProduct.objects.filter(sku='').count())
print("products_with_null_sku:", ShopifyProduct.objects.filter(sku__isnull=True).count())

unmatched = ShopifyOrderItem.objects.filter(matched_product__isnull=True, shopify_variant_id__isnull=False)
print("unmatched_items_by_variant_id:", unmatched.count())

unmatched_product_id = ShopifyOrderItem.objects.filter(matched_product__isnull=True, shopify_variant_id__isnull=True, shopify_product_id__isnull=False)
print("unmatched_items_by_product_id:", unmatched_product_id.count())

print("\nUNMATCHED_SAMPLES:")
for item in unmatched[:10]:
    print(f"  order={item.order.order_number} sku={item.sku} product_id={item.shopify_product_id} variant_id={item.shopify_variant_id} title={item.product_title}")
