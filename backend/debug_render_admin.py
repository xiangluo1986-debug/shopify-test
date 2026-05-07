from django.test import RequestFactory
from django.contrib.auth import get_user_model
from django.contrib import admin
from shopify_sync.admin import ShopifyOrderAdmin
from shopify_sync.models import ShopifyOrder

User = get_user_model()
user = User.objects.filter(is_superuser=True).first()
print('SUPERUSER', bool(user), getattr(user, 'username', None))
ma = ShopifyOrderAdmin(ShopifyOrder, admin.site)
print('HAS_METHOD', hasattr(ma, 'display_missing_product_data'))
print('METHOD', getattr(ma, 'display_missing_product_data', None))
print('LIST_DISPLAY', ma.list_display)
print('FIELDS_COUNT', len(ma.list_display))

rf = RequestFactory()
request = rf.get('/admin/shopify_sync/shopifyorder/')
request.user = user
request._dont_enforce_csrf_checks = True
response = ma.changelist_view(request)
print('RESPONSE', getattr(response, 'status_code', None), type(response))
try:
    response.render()
    print('RENDER SUCCESS')
except Exception:
    import traceback
    traceback.print_exc()
    with open('/app/render_error.txt', 'w', encoding='utf-8') as f:
        traceback.print_exc(file=f)
    print('WROTE /app/render_error.txt')
