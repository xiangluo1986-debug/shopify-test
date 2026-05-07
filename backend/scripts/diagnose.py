import traceback
try:
    from tickets.models import Ticket, TicketComment
    from tickets.admin import TicketAdmin
    from django.contrib import admin
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory
    
    User = get_user_model()
    ticket = Ticket.objects.first()
    
    if ticket:
        print(f"✓ Ticket ID: {ticket.id}")
        print(f"✓ Comments count: {ticket.comments.count()}")
        
        # Try to access first comment
        comment = ticket.comments.first()
        if comment:
            print(f"✓ Comment ID: {comment.id}")
            print(f"✓ pending_followup_to: {comment.pending_followup_to}")
        
        # Try admin get_inlines with mock request
        admin_user = User.objects.filter(is_staff=True).first()
        
        if admin_user:
            factory = RequestFactory()
            request = factory.get('/admin/')
            request.user = admin_user
            
            ticket_admin = TicketAdmin(Ticket, admin.site)
            try:
                inlines = ticket_admin.get_inlines(request)
                print(f"✓ get_inlines returned: {inlines}")
                print("SUCCESS: No errors in get_inlines")
            except Exception as e:
                print(f"ERROR in get_inlines: {e}")
                traceback.print_exc()
        else:
            print("No admin user found")
    else:
        print("No tickets found")
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()
