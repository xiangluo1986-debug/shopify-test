from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("shopify_sync", "0019_shopifysyncstate"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShopifyOrderPackage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("package_no", models.PositiveIntegerField(default=1)),
                ("tracking_number", models.CharField(blank=True, default="", max_length=255)),
                ("carrier", models.CharField(blank=True, default="", max_length=100)),
                ("country_code", models.CharField(blank=True, default="", max_length=10)),
                ("shipping_cost_rmb", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("ordering_cost_rmb", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("note", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="packages", to="shopify_sync.shopifyorder")),
            ],
            options={
                "ordering": ["order", "package_no"],
                "unique_together": {("order", "package_no")},
            },
        ),
        migrations.AddField(
            model_name="shopifyorderitem",
            name="package",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="items", to="shopify_sync.shopifyorderpackage"),
        ),
    ]
