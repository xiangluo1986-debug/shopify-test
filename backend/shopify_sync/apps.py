from django.apps import AppConfig


class ShopifySyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "shopify_sync"
    verbose_name = "Shopify Sync"

    def ready(self):
        from django.db.models.signals import post_migrate

        def create_default_groups(sender, **kwargs):
            from django.contrib.auth.models import Group
            for name in ["Super Admin", "Finance", "Admin", "Shenzhen Warehouse"]:
                Group.objects.get_or_create(name=name)

        post_migrate.connect(create_default_groups, sender=self)
