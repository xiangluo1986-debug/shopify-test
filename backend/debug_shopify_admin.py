from django.test import RequestFactory
from django.contrib.auth import get_user_model
from django.contrib import admin
from shopify_sync.admin import ShopifyOrderAdmin
from shopify_sync.models import ShopifyOrder

User = get_user_model()
user = User.objects.filter(is_superuser=True).first()
print(SUPERUSER, bool(user), getattr(user, username, None))
if not user:
    raise SystemExit(No
