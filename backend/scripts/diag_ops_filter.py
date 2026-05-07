import os
import sys
import django

# Ensure project root is on sys.path for imports when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from tickets.admin import TicketAdmin, ticket_is_closed, OPS_USERNAME
from tickets.models import Ticket, TicketComment
from django.contrib import admin as djadmin
from django.db.models import Q, OuterRef, Subquery, Exists

ta = TicketAdmin(Ticket, djadmin.site)

last_comment_qs = TicketComment.objects.filter(ticket=OuterRef("pk")).order_by("-created_at")
last_author_username = Subquery(last_comment_qs.values("author__username")[:1])
last_pending_to = Subquery(last_comment_qs.values("pending_followup_to")[:1])
has_comments = Exists(TicketComment.objects.filter(ticket=OuterRef("pk")))

qs = Ticket.objects.annotate(
    _has_comments=has_comments,
    _last_author_username=last_author_username,
    _last_pending_to=last_pending_to,
)

closed_mark_q = (
    Q(status__icontains="已结束")
    | Q(status__icontains="结束")
    | Q(status__icontains="关闭")
    | Q(status__icontains="已关闭")
    | Q(status__icontains="closed")
    | Q(status__icontains="done")
    | Q(status__icontains="finished")
    | Q(status__icontains="resolved")
)
reopen_q = Q(status__icontains="重新开启") | Q(status__icontains="reopen")

is_closed_q = closed_mark_q & ~reopen_q
open_qs = qs.exclude(is_closed_q)

ops_uname = (OPS_USERNAME or "").strip()
last_is_ops = Q(_last_author_username__iexact=ops_uname)
creator_is_ops = Q(created_by__username__iexact=ops_uname)
new_mark_q = Q(status__icontains="新建") | Q(status__icontains="new") | Q(status__icontains="open")

filter_ops_q = Q(_last_pending_to="ops") | (
    Q(_last_pending_to__in=["", None])
    & (
        (Q(_has_comments=False) & ~(creator_is_ops & new_mark_q))
        | (Q(_has_comments=True) & ~last_is_ops)
    )
)

filter_ops_ids = set(open_qs.filter(filter_ops_q).values_list("id", flat=True))

pending_ops_ids = set()
for t in Ticket.objects.all():
    if ticket_is_closed(t):
        continue
    if "待zhang-SupportOps回复" in str(ta.pending_followup(t)):
        pending_ops_ids.add(t.id)

only_in_pending = sorted(pending_ops_ids - filter_ops_ids)
only_in_filter = sorted(filter_ops_ids - pending_ops_ids)

print("pending_followup=ops count:", len(pending_ops_ids))
print("filter=ops count:", len(filter_ops_ids))
print("only in pending_followup:", only_in_pending[:20])
print("only in filter:", only_in_filter[:20])
