import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0009_alter_ticketcomment_pending_followup_to_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="is_pinned",
            field=models.BooleanField(default=False, verbose_name="置顶"),
        ),
        migrations.AddField(
            model_name="ticket",
            name="pinned_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="置顶时间"),
        ),
        migrations.AddField(
            model_name="ticket",
            name="pinned_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="pinned_tickets",
                to=settings.AUTH_USER_MODEL,
                verbose_name="置顶人",
            ),
        ),
    ]
