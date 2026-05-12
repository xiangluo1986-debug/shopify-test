from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("shopify_sync", "0025_shopifyorder_total_tip_received"),
    ]

    operations = [
        migrations.AddField(
            model_name="shopifyorder",
            name="exception_review_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="shopifyorder",
            name="exception_review_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shopifyorder",
            name="exception_review_requested_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="shopify_orders_exception_requested",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="shopifyorder",
            name="exception_review_response",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="shopifyorder",
            name="exception_review_responded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shopifyorder",
            name="exception_review_responded_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="shopify_orders_exception_responded",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="shopifyorder",
            name="settlement_status",
            field=models.CharField(
                choices=[
                    ("pending_warehouse", "待深圳仓确认"),
                    ("warehouse_fulfilled", "深圳仓已发货"),
                    ("cost_confirmed", "深圳仓已确认成本"),
                    ("admin_confirmed", "admin已确认"),
                    ("pending_payment", "待支付"),
                    ("payment_submitted", "已提交支付，待深圳仓确认收款"),
                    ("paid", "已支付"),
                    ("transferred", "已转其他仓"),
                    ("cancelled", "已取消深圳仓履约"),
                    ("exception", "同步异常待审核"),
                    ("exception_review", "异常待审核"),
                ],
                default="pending_warehouse",
                max_length=20,
            ),
        ),
    ]
