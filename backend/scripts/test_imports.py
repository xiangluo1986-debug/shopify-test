import traceback

try:
    from tickets.admin import FollowUpByFilter
    print('FollowUpByFilter imported OK')
except Exception:
    traceback.print_exc()
