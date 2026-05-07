from tickets.models import TicketComment

# 查看现存评论的 pending_followup_to 值
comments = TicketComment.objects.all()
print(f"总评论数：{comments.count()}")
print("\n前5条评论的 pending_followup_to 值：")
for c in comments[:5]:
    print(f"Comment#{c.id}: pending_followup_to='{c.pending_followup_to}' (author: {c.author.username})")

# 统计不同值
print("\npending_followup_to 值分布：")
for val in ['ops', 'cs', '']:
    count = comments.filter(pending_followup_to=val).count()
    print(f"  '{val}': {count}")

# 检查一个特定工单（从截图看是 #87）
print("\n\n检查工单 #87 的情况：")
from tickets.models import Ticket
try:
    ticket = Ticket.objects.get(id=87)
    print(f"工单 #87: {ticket.title}")
    print(f"创建人: {ticket.created_by.username if ticket.created_by else 'None'}")
    print(f"状态: {ticket.status}")
    
    last_comment = ticket.comments.order_by("-created_at").first()
    if last_comment:
        print(f"\n最后评论:")
        print(f"  ID: {last_comment.id}")
        print(f"  作者: {last_comment.author.username}")
        print(f"  pending_followup_to: '{last_comment.pending_followup_to}'")
    else:
        print("没有评论")
except Exception as e:
    print(f"错误: {e}")
