import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from tickets.models import TicketComment, Ticket
import collections

comments = TicketComment.objects.all()
counter = collections.Counter((c.pending_followup_to for c in comments))
print(f'现在的值分布: {dict(counter)}')

ticket = Ticket.objects.get(id=87)
last_c = ticket.comments.order_by('-created_at').first()
if last_c:
    print(f'工单 #87: 作者={last_c.author.username}, pending_followup_to="{last_c.pending_followup_to}" (空则为自动判断模式)')
