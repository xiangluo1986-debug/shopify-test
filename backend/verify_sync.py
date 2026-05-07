import os
import django
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
django.setup()

from shopify_sync.models import ShopifyOrder, ShopifyOrderItem

print("=" * 60)
print("SHENZHEN ORDERS SAMPLE")
print("=" * 60)

orders = ShopifyOrder.objects.filter(is_shenzhen_order=True).order_by('-synced_at')[:3]
for order in orders:
    print(f"\nOrder: {order.order_name}")
    print(f"  Customer: {order.customer_name}")
    print(f"  Location (raw): {order.current_location_raw}")
    print(f"  Location (normalized): {order.current_location}")
    print(f"  Settlement status: {order.settlement_status}")
    print(f"  Items count: {order.order_items.count()}")
    
    items = order.order_items.all()[:2]
    for item in items:
        print(f"    - SKU: {item.sku}, Qty: {item.quantity}, Price: {item.price}")
        print(f"      Matched product: {item.matched_product}")
        if item.matched_product:
            print(f"      Locked cost: ￥{item.locked_product_cost_rmb}")
        print(f"      Total cost: ￥{item.total_cost_rmb}")

print("\n" + "=" * 60)
print("ORDERS BY LOCATION")
print("=" * 60)
locations = ShopifyOrder.objects.values('current_location').distinct()
for loc in locations:
    count = ShopifyOrder.objects.filter(current_location=loc['current_location']).count()
    print(f"{loc['current_location']}: {count} orders")

print("\n" + "=" * 60)
print("SETTLEMENT STATUS DISTRIBUTION")
print("=" * 60)
statuses = ShopifyOrder.objects.values('settlement_status').distinct()
for status in statuses:
    count = ShopifyOrder.objects.filter(settlement_status=status['settlement_status']).count()
    print(f"{status['settlement_status']}: {count} orders")

print("\n" + "=" * 60)
print("COST LOCKING VERIFICATION")
print("=" * 60)
items_with_cost = ShopifyOrderItem.objects.filter(locked_product_cost_rmb__isnull=False).exclude(locked_product_cost_rmb=0).count()
items_total = ShopifyOrderItem.objects.count()
print(f"Items with locked cost: {items_with_cost}/{items_total}")

if items_with_cost > 0:
    sample_item = ShopifyOrderItem.objects.filter(locked_product_cost_rmb__isnull=False).exclude(locked_product_cost_rmb=0).first()
    print(f"\nSample item with locked cost:")
    print(f"  SKU: {sample_item.sku}")
    print(f"  Order: {sample_item.order.order_name}")
    print(f"  Matched product: {sample_item.matched_product.sku}")
    print(f"  Product cost: ￥{sample_item.matched_product.product_cost_rmb}")
    print(f"  Locked cost: ￥{sample_item.locked_product_cost_rmb}")
    print(f"  Total cost: ￥{sample_item.total_cost_rmb}")
