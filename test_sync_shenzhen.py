#!/usr/bin/env python
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
import json

client = Client()
user = User.objects.filter(is_superuser=True).first()

if user:
    client.force_login(user)
    print('Testing sync_shenzhen_orders endpoint...')
    response = client.get('/auth/shopify/sync-shenzhen-orders')
    
    if response.status_code == 200:
        data = json.loads(response.content.decode())
        print(f'Success: {data.get("success")}')
        print(f'Created orders: {data.get("created_orders", 0)}')
        print(f'Updated orders: {data.get("updated_orders", 0)}')
        print(f'Created items: {data.get("created_items", 0)}')
        print(f'Skipped non-Shenzhen: {data.get("skipped_non_shenzhen", 0)}')
        print(f'Checked fulfillment orders: {data.get("checked_fulfillment_orders_count", 0)}')
        print(f'Detected locations (raw): {data.get("detected_locations_raw", [])}')
        print(f'Detected locations (normalized): {data.get("detected_locations_normalized", [])}')
        print(f'Shenzhen line items: {data.get("shenzhen_line_items_count", 0)}')
    else:
        print(f'Error: {response.status_code}')
        print(response.content.decode()[:300])
else:
    print('No superuser found')
