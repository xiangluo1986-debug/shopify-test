from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("shopify_sync", "0016_shenzhencountryshippingdefault"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShenzhenProductCountryShippingDefault",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("country_code", models.CharField(db_index=True, max_length=10)),
                ("country_name", models.CharField(blank=True, default="", max_length=100)),
                ("shopify_product_id", models.BigIntegerField(blank=True, db_index=True, null=True)),
                ("shopify_variant_id", models.BigIntegerField(blank=True, db_index=True, null=True)),
                ("sku", models.CharField(blank=True, default="", max_length=255)),
                ("product_title", models.CharField(blank=True, default="", max_length=500)),
                ("variant_title", models.CharField(blank=True, default="", max_length=255)),
                ("default_shipping_cost_rmb", models.DecimalField(decimal_places=2, max_digits=10)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("note", models.TextField(blank=True, default="")),
                (
                    "matched_product",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="shipping_defaults",
                        to="shopify_sync.shopifyproduct",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_shenzhen_product_shipping_defaults",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["country_code", "product_title", "variant_title"],
                "unique_together": {("country_code", "shopify_variant_id")},
                "indexes": [
                    models.Index(fields=["country_code", "shopify_variant_id"], name="shopify_syn_country_dba550_idx"),
                    models.Index(fields=["country_code", "shopify_product_id"], name="shopify_syn_country_9eb8b8_idx"),
                ],
            },
        ),
    ]
