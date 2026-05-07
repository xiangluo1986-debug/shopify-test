from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from django.conf import settings
from django.views.static import serve  # ✅ 用于生产环境直接提供 media 文件

admin.site.site_header = settings.ADMIN_SITE_HEADER
admin.site.site_title = settings.ADMIN_SITE_TITLE
admin.site.index_title = settings.ADMIN_INDEX_TITLE
# admin.site.index_template = "admin/shopify_sync_index.html"

urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    path("admin/", admin.site.urls),
    path("auth/shopify/", include("shopify_sync.urls")),

    # ✅ 生产环境也强制提供 media（DEBUG=False 也能打开上传图片）
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
