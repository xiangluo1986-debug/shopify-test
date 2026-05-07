from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("shopify_sync", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShopifyOrder",
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
                ("shopify_order_id", models.BigIntegerField()),
                ("order_name", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField()),
                ("financial_status", models.CharField(blank=True, max_length=50)),
                (
                    "fulfillment_status",
                    models.CharField(blank=True, max_length=50, null=True),
                ),
                (
                    "total_price",
                    models.DecimalField(decimal_places=2, max_digits=10),
                ),
                ("currency", models.CharField(default="USD", max_length=3)),
                ("synced_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "installation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="orders",
                        to="shopify_sync.shopifyinstallation",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="shopifyorder",
            constraint=models.UniqueConstraint(
                fields=("installation", "shopify_order_id"),
                name="unique_installation_order",
            ),
        ),
    ]
