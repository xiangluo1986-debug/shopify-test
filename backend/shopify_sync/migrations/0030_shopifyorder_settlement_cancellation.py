from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("shopify_sync", "0029_shopifyorder_shopify_tags"),
    ]

    operations = [
        migrations.AddField(
            model_name="shopifyorder",
            name="settlement_cancel_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="shopifyorder",
            name="settlement_cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shopifyorder",
            name="settlement_cancelled_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="shopify_orders_settlement_cancelled",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
