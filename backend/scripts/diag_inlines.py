import os, sys, django, traceback
# ensure project root is on sys.path when running as a script inside container
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
django.setup()

from django.test import RequestFactory
from django.contrib import admin as djadmin
from django.contrib.auth import get_user_model
from tickets.admin import TicketAdmin
from tickets.models import Ticket

User = get_user_model()
user = User.objects.filter(is_superuser=True).first()
if not user:
    print('No superuser found; aborting')
    sys.exit(1)

rf = RequestFactory()
request = rf.get('/admin/')
request.user = user

admin_instance = TicketAdmin(Ticket, djadmin.site)

try:
    ticket = Ticket.objects.first()
    if not ticket:
        print('No Ticket instances found')
        sys.exit(0)
    print(f'Ticket id={ticket.id}');
    # call get_formsets_with_inlines to simulate admin change page
    formsets = list(admin_instance.get_formsets_with_inlines(request, ticket))
    print('get_formsets_with_inlines executed successfully; formsets count =', len(formsets))
    # Also test get_inline_instances
    try:
        inlines = admin_instance.get_inline_instances(request, ticket)
        print('get_inline_instances OK; inline class names =', [i.__class__.__name__ for i in inlines])
    except Exception as e:
        print('get_inline_instances ERROR:')
        traceback.print_exc()

except Exception:
    print('Error during get_formsets_with_inlines:')
    traceback.print_exc()
