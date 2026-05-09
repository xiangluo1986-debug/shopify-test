from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("shopify_sync", "0022_shopifyproductcosthistory"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FinanceExchangeRate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("base_currency", models.CharField(db_index=True, default="AUD", max_length=3)),
                ("quote_currency", models.CharField(db_index=True, default="CNY", max_length=3)),
                ("rate", models.DecimalField(decimal_places=4, max_digits=10)),
                ("effective_date", models.DateField(db_index=True, default=django.utils.timezone.localdate)),
                ("is_active", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("note", models.TextField(blank=True, default="")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_finance_exchange_rates", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-effective_date", "-updated_at"],
                "indexes": [
                    models.Index(fields=["base_currency", "quote_currency", "is_active"], name="shopify_syn_fx_pair_active_idx"),
                ],
            },
        ),
    ]
