import requests
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from shopify_sync.models import ShopifyInstallation

# Get the installation
inst = ShopifyInstallation.objects.get(shop="kidstoylover.myshopify.com")
print(f"Token: {inst.access_token[:10]}...{inst.access_token[-10:]}")
print(f"Scope: {inst.scope}")

# Try API call with different parameters
url = f"https://kidstoylover.myshopify.com/admin/api/2024-01/products.json"
headers = {"X-Shopify-Access-Token": inst.access_token}

# Test 1: No parameters
print("\n=== Test 1: No parameters ===")
resp = requests.get(url, headers=headers, timeout=10)
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"Response keys: {list(data.keys())}")
print(f"Products count: {len(data.get('products', []))}")
if len(data.get('products', [])) > 0:
    print(f"First product: {data['products'][0]}")

# Test 2: With limit only
print("\n=== Test 2: With limit=10 ===")
resp = requests.get(url, params={"limit": 10}, headers=headers, timeout=10)
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"Products count: {len(data.get('products', []))}")

# Test 3: Check shop info
print("\n=== Test 3: Get shop info ===")
shop_url = "https://kidstoylover.myshopify.com/admin/api/2024-01/shop.json"
resp = requests.get(shop_url, headers=headers, timeout=10)
print(f"Status: {resp.status_code}")
shop_data = resp.json()
if 'shop' in shop_data:
    shop = shop_data['shop']
    print(f"Shop name: {shop.get('name')}")
    print(f"Shop domain: {shop.get('domain')}")
    print(f"Shop myshopify_domain: {shop.get('myshopify_domain')}")
else:
    print(f"Response: {shop_data}")

# Test 4: Try with different fields parameter
print("\n=== Test 4: With fields parameter ===")
resp = requests.get(url, params={"limit": 250, "fields": "id,title,handle,variants"}, headers=headers, timeout=10)
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"Products count: {len(data.get('products', []))}")
