from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("shopify_sync", "0021_shopifyorder_shopify_note_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ShopifyProductCostHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("shopify_product_id", models.BigIntegerField(blank=True, db_index=True, null=True)),
                ("shopify_variant_id", models.BigIntegerField(blank=True, db_index=True, null=True)),
                ("sku", models.CharField(blank=True, default="", max_length=255)),
                ("product_title", models.CharField(blank=True, default="", max_length=500)),
                ("old_item_cost_rmb", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("new_item_cost_rmb", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("old_product_cost_rmb", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("new_product_cost_rmb", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("overwrite_product_cost", models.BooleanField(default=False)),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                ("source", models.CharField(blank=True, default="order_item_inline", max_length=100)),
                ("note", models.TextField(blank=True, default="")),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="shopify_product_cost_changes", to=settings.AUTH_USER_MODEL)),
                ("order", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="product_cost_histories", to="shopify_sync.shopifyorder")),
                ("order_item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="product_cost_histories", to="shopify_sync.shopifyorderitem")),
                ("product", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="cost_histories", to="shopify_sync.shopifyproduct")),
            ],
            options={
                "ordering": ["-changed_at"],
            },
        ),
    ]
