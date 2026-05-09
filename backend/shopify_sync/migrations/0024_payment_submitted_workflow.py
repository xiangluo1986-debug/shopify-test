from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shopify_sync", "0023_financeexchangerate"),
    ]

    operations = [
        migrations.AddField(
            model_name="settlementbatch",
            name="payment_proof",
            field=models.FileField(blank=True, help_text="付款凭证", null=True, upload_to="settlement_payment_proofs/"),
        ),
        migrations.AddField(
            model_name="settlementbatch",
            name="payment_submitted_at",
            field=models.DateTimeField(blank=True, help_text="提交支付时间", null=True),
        ),
        migrations.AddField(
            model_name="settlementbatch",
            name="payment_submitted_by",
            field=models.CharField(blank=True, help_text="提交支付人", max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name="settlementbatch",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "草稿"),
                    ("pending_payment", "待支付"),
                    ("payment_submitted", "已提交支付，待深圳仓确认收款"),
                    ("paid", "已支付"),
                    ("cancelled", "已取消"),
                ],
                default="draft",
                help_text="批次状态",
                max_length=20,
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
                    ("exception", "异常待审核"),
                ],
                default="pending_warehouse",
                max_length=20,
            ),
        ),
    ]
