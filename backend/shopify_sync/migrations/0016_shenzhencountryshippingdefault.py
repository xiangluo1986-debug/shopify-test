from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("shopify_sync", "0015_alter_shopifyproduct_sku"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShenzhenCountryShippingDefault",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("country_code", models.CharField(db_index=True, max_length=10, unique=True)),
                ("country_name", models.CharField(blank=True, default="", max_length=100)),
                ("default_shipping_cost_rmb", models.DecimalField(decimal_places=2, max_digits=10)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("note", models.TextField(blank=True, default="")),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_shenzhen_shipping_defaults",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["country_code"],
            },
        ),
    ]
