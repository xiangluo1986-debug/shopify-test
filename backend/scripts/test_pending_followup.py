import traceback

try:
    from django.contrib.auth import get_user_model
    from tickets.models import Ticket
    from tickets.admin import TicketAdmin
    from django.contrib import admin

    User = get_user_model()
    u, created = User.objects.get_or_create(username='zhang-SupportOps', defaults={'email': 'ops@example.com'})

    # 创建一个最小票据（字段以 models.py 为准）
    t = Ticket.objects.create(title='test-shell-pending', created_by=u)

    admin_instance = TicketAdmin(Ticket, admin.site)
    res = admin_instance.pending_followup(t)
    print('PENDING_HTML:')
    print(res)

except Exception:
    traceback.print_exc()
