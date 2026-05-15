from django.urls import path

from . import views

urlpatterns = [
    path("install/", views.install, name="shopify_install"),
    path("callback/", views.callback, name="shopify_callback"),
    path("test-orders/", views.test_orders, name="shopify_test_orders"),
    path("sync-orders/", views.sync_orders, name="shopify_sync_orders"),
    path("orders-search/", views.orders_search, name="shopify_orders_search"),
    path("sync-products/", views.sync_products, name="shopify_sync_products"),
    path("sync-shenzhen-orders/", views.sync_shenzhen_orders, name="shopify_sync_shenzhen_orders"),
    path("update-shenzhen-tracking/", views.update_shenzhen_tracking, name="shopify_update_shenzhen_tracking"),
    path("sync-dashboard/", views.sync_dashboard, name="shopify_sync_dashboard"),
    path(
        "translation-console/product-search/",
        views.translation_console_product_search,
        name="shopify_translation_console_product_search",
    ),
    path(
        "translation-console/job-status/",
        views.translation_console_job_status,
        name="shopify_translation_console_job_status",
    ),
]
