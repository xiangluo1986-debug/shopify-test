#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import User
from shopify_sync.views import sync_shenzhen_orders
from shopify_sync.models import ShopifyOrder, ShopifyOrderItem
import json

# Check existing data
print("=" * 50)
print("Before sync:")
print(f"ShopifyOrder count: {ShopifyOrder.objects.count()}")
print(f"ShopifyOrderItem count: {ShopifyOrderItem.objects.count()}")
print("=" * 50)

# Run sync
try:
    factory = RequestFactory()
    user = User.objects.filter(is_superuser=True).first()
    
    if not user:
        print("ERROR: No superuser found")
        sys.exit(1)
    
    request = factory.get('/auth/shopify/sync-shenzhen-orders')
    request.user = user
    
    print("Running sync_shenzhen_orders...")
    response = sync_shenzhen_orders(request)
    
    if response.status_code == 200:
        data = json.loads(response.content.decode())
        print("=" * 50)
        print("SYNC RESULTS:")
        print(f"Created orders: {data.get('created_orders', 0)}")
        print(f"Updated orders: {data.get('updated_orders', 0)}")
        print(f"Created items: {data.get('created_items', 0)}")
        print(f"Updated items: {data.get('updated_items', 0)}")
        print(f"Skipped non-Shenzhen: {data.get('skipped_non_shenzhen', 0)}")
        print(f"Transferred orders: {data.get('transferred_orders', 0)}")
        print(f"Checked fulfillment orders: {data.get('checked_fulfillment_orders_count', 0)}")
        print(f"Shenzhen line items detected: {data.get('shenzhen_line_items_count', 0)}")
        locs = data.get('detected_locations_normalized', [])
        if locs:
            print(f"Detected locations (normalized): {list(set(locs))}")
        print("=" * 50)
        
        # Check after sync
        print("After sync:")
        print(f"ShopifyOrder count: {ShopifyOrder.objects.count()}")
        print(f"ShopifyOrderItem count: {ShopifyOrderItem.objects.count()}")
        
        if ShopifyOrder.objects.count() > 0:
            shenzhen_orders = ShopifyOrder.objects.filter(is_shenzhen_order=True)
            print(f"Shenzhen orders: {shenzhen_orders.count()}")
            if shenzhen_orders.count() > 0:
                sample = shenzhen_orders.first()
                print(f"Sample: {sample.order_name} - Location: {sample.current_location} - Items: {sample.order_items.count()}")
    else:
        print(f"ERROR: Response status {response.status_code}")
        print(response.content.decode()[:1000])
        
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
