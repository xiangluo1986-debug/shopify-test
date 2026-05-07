import traceback
try:
    from tickets.models import Ticket
    from tickets.admin import TicketAdmin
    from django.contrib import admin
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory
    
    User = get_user_model()
    ticket = Ticket.objects.filter(pk=87).first()
    
    if not ticket:
        print("Ticket 87 not found, trying first ticket...")
        ticket = Ticket.objects.first()
    
    if ticket:
        print(f"✓ Using Ticket ID: {ticket.id}")
        
        # Simulate admin user request
        admin_user = User.objects.filter(is_staff=True).first()
        if not admin_user:
            print("ERROR: No admin user found")
        else:
            factory = RequestFactory()
            request = factory.get('/admin/')
            request.user = admin_user
            
            ticket_admin = TicketAdmin(Ticket, admin.site)
            
            # Try to get form
            try:
                form_class = ticket_admin.get_form(request, ticket)
                print(f"✓ Form class: {form_class}")
            except Exception as e:
                print(f"ERROR in get_form: {e}")
                traceback.print_exc()
            
            # Try to get inlines
            try:
                inlines = ticket_admin.get_inlines(request)
                print(f"✓ Inlines: {[i.__name__ for i in inlines]}")
                
                # Try to instantiate each inline
                for inline_class in inlines:
                    try:
                        inline = inline_class(Ticket, admin.site)
                        print(f"  ✓ {inline_class.__name__} instantiated")
                    except Exception as e:
                        print(f"  ERROR instantiating {inline_class.__name__}: {e}")
                        traceback.print_exc()
            except Exception as e:
                print(f"ERROR in get_inlines: {e}")
                traceback.print_exc()
    else:
        print("No tickets found")
except Exception as e:
    print(f"MAIN ERROR: {e}")
    traceback.print_exc()
