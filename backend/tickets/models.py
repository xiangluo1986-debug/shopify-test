from django.conf import settings
from django.db import models


class Ticket(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "新建"
        IN_PROGRESS = "in_progress", "处理中"
        RESOLVED = "resolved", "已结束"
        REOPENED = "reopened", "重新开启"

    class Priority(models.TextChoices):
        LOW = "low", "低"
        NORMAL = "normal", "普通"
        HIGH = "high", "高"
        URGENT = "urgent", "紧急"

    title = models.CharField("标题", max_length=200)
    customer_name = models.CharField("客户姓名", max_length=120, blank=True, default="")
    # ✅ 客户邮箱暂时不删字段（避免丢数据），后面我们在 admin 里隐藏它
    customer_email = models.EmailField("客户邮箱", blank=True)
    order_no = models.CharField("订单号", max_length=80, blank=True, default="")
    # ✅ 原 product_sku -> product_name
    product_name = models.CharField("产品名称", max_length=200, blank=True)
    # ✅ 新增描述栏
    description = models.TextField("描述", blank=True)

    status = models.CharField("状态", max_length=20, choices=Status.choices, default=Status.NEW)
    priority = models.CharField("优先级", max_length=20, choices=Priority.choices, default=Priority.NORMAL)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_tickets",
        verbose_name="创建人",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
        verbose_name="指派给",
    )

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    def __str__(self):
        return f"#{self.id} {self.title}"


class TicketComment(models.Model):
    class PendingFollowupTo(models.TextChoices):
        OPS = "ops", "zhang-SupportOps"
        CS = "cs", "CustomerSupport"
        ADMIN = "admin", "admin"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments", verbose_name="工单")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="作者")

    is_factory_reply = models.BooleanField("工厂回复", default=False)
    content = models.TextField("内容")
    # ✅ 新增：管理员/客服可指定待跟进人（默认为空，使用自动判断逻辑）
    pending_followup_to = models.CharField(
        "指定待跟进",
        max_length=20,
        choices=PendingFollowupTo.choices,
        default="",
        blank=True,
        help_text="留空则使用自动判断逻辑；管理员/客服可显式指定由谁跟进"
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    def __str__(self):
        return f"Comment#{self.id} Ticket#{self.ticket_id}"


class TicketReadStatus(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="read_statuses", verbose_name="工单")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ticket_read_statuses", verbose_name="用户")
    last_seen_comment = models.ForeignKey(
        "TicketComment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="seen_by",
        verbose_name="最后查看的回复",
    )
    last_seen_at = models.DateTimeField("最后查看时间", auto_now=True)

    class Meta:
        unique_together = ("ticket", "user")

    def __str__(self):
        return f"ReadStatus Ticket#{self.ticket_id} User#{self.user_id}"

from django.conf import settings
from django.db import models

# models.py 里（确保文件顶部已经 import settings / models）

class TicketAttachment(models.Model):
    ticket = models.ForeignKey(
        "Ticket",
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="工单",
    )
    comment = models.ForeignKey(
        "TicketComment",
        on_delete=models.SET_NULL,   # ✅ 关键：不要 CASCADE
        null=True,
        blank=True,
        related_name="attachments",
        verbose_name="回复",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="上传者",
    )

    file = models.FileField(upload_to="ticket_uploads/%Y/%m/%d/", verbose_name="文件")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    def __str__(self):
        return f"Attachment #{self.id}"

