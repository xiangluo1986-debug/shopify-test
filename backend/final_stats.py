import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from shopify_sync.models import ShopifyProduct, ShopifyOrderItem
print('FINAL_STATS:')
print('total_products=', ShopifyProduct.objects.count())
print('products_blank_sku=', ShopifyProduct.objects.filter(sku='').count())
print('total_order_items=', ShopifyOrderItem.objects.count())
unmatched_all = ShopifyOrderItem.objects.filter(matched_product__isnull=True).count()
matched_all = ShopifyOrderItem.objects.filter(matched_product__isnull=False).count()
print('matched_items=', matched_all)
print('unmatched_items_total=', unmatched_all)
unmatched_variant = ShopifyOrderItem.objects.filter(matched_product__isnull=True, shopify_variant_id__isnull=False)
print('unmatched_by_variant_id=', unmatched_variant.count())
