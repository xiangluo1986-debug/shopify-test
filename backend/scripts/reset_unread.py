import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model
from tickets.models import Ticket, TicketReadStatus

User = get_user_model()

users = list(User.objects.all())
tickets = list(Ticket.objects.all())

updated = 0
created = 0

for ticket in tickets:
    last_comment = ticket.comments.order_by("-created_at").first()
    if not last_comment:
        continue
    for user in users:
        obj, was_created = TicketReadStatus.objects.update_or_create(
            ticket=ticket,
            user=user,
            defaults={"last_seen_comment": last_comment},
        )
        if was_created:
            created += 1
        else:
            updated += 1

print(f"Reset done. Created={created}, Updated={updated}")
