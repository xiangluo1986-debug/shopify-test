import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import User
from shopify_sync.views import sync_shenzhen_orders
import json

factory = RequestFactory()
user = User.objects.filter(is_superuser=True).first()
if user:
    request = factory.get('/auth/shopify/sync-shenzhen-orders')
    request.user = user
    print('Testing sync_shenzhen_orders...')
    response = sync_shenzhen_orders(request)
    print(f'Status: {response.status_code}')
    if response.status_code == 200:
        data = json.loads(response.content.decode())
        print(f'Success: {data.get("success")}')
        print(f'Orders in first page: {data.get("order_count_first_page", 0)}')
        print(f'Created orders: {data.get("created_orders", 0)}')
        print(f'Skipped non-Shenzhen: {data.get("skipped_non_shenzhen", 0)}')
    else:
        print(f'Error: {response.content.decode()[:300]}')
else:
    print('No superuser found')