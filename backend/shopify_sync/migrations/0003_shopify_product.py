from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("shopify_sync", "0002_shopify_order"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShopifyProduct",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("shopify_product_id", models.BigIntegerField()),
                ("shopify_variant_id", models.BigIntegerField(unique=True)),
                ("product_title", models.CharField(max_length=255)),
                ("variant_title", models.CharField(blank=True, max_length=255)),
                ("sku", models.CharField(blank=True, max_length=255)),
                ("handle", models.CharField(blank=True, max_length=255)),
                ("vendor", models.CharField(blank=True, max_length=255)),
                ("product_type", models.CharField(blank=True, max_length=255)),
                ("status", models.CharField(default="active", max_length=50)),
                ("image_url", models.URLField(blank=True, max_length=500)),
                (
                    "price",
                    models.DecimalField(decimal_places=2, default=0, max_digits=10),
                ),
                ("inventory_quantity", models.IntegerField(default=0)),
                ("is_shenzhen_product", models.BooleanField(default=False)),
                (
                    "product_cost_rmb",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=10, null=True
                    ),
                ),
                ("shipping_cost_rules", models.JSONField(blank=True, default=dict)),
                ("last_synced_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "installation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="products",
                        to="shopify_sync.shopifyinstallation",
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.AddIndex(
            model_name="shopifyproduct",
            index=models.Index(
                fields=["installation", "sku"], name="shopify_syn_install_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="shopifyproduct",
            index=models.Index(
                fields=["shopify_variant_id"], name="shopify_syn_variant_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="shopifyproduct",
            constraint=models.UniqueConstraint(
                fields=("installation", "shopify_variant_id"),
                name="unique_installation_variant",
            ),
        ),
    ]
