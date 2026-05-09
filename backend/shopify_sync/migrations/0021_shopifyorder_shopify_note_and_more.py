from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shopify_sync", "0020_shopifyorderpackage_shopifyorderitem_package"),
    ]

    operations = [
        migrations.AddField(
            model_name="shopifyorder",
            name="shopify_note",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shopifyorder",
            name="shopify_note_attributes",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
