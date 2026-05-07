from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shopify_sync', '0008_shopifyorder_tracking_number_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='shopifyorder',
            name='fulfilled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shopifyorder',
            name='fulfillment_status_raw',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='shopifyorder',
            name='last_order_synced_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shopifyorder',
            name='tracking_company',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='shopifyorder',
            name='tracking_url',
            field=models.URLField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name='shopifyorderitem',
            name='fulfilled_quantity',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shopifyorderitem',
            name='fulfillment_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shopifyorderitem',
            name='item_fulfilled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
