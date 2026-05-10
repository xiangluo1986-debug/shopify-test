from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shopify_sync", "0024_payment_submitted_workflow"),
    ]

    operations = [
        migrations.AddField(
            model_name="shopifyorder",
            name="total_tip_received",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
    ]
