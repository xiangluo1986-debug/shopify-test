from django.contrib import admin, messages
from django.utils.html import format_html
from django.urls import reverse, path
from django.shortcuts import redirect
from django.db.models import Q, OuterRef, Subquery, Exists, F

from .models import Ticket, TicketComment, TicketAttachment, TicketReadStatus


# ==========
# 角色判断（按你的用户名规则）
# ==========
OPS_USERNAME = "zhang-SupportOps"
CS_KEYWORDS = ["customersupport", "customer-support", "cui-customersupport", "support"]  # 你可以按需增减


def is_ops_user(user) -> bool:
    if not user:
        return False
    return (getattr(user, "username", "") or "").strip().lower() == OPS_USERNAME.lower()


def is_customer_support_user(user) -> bool:
    """
    这里用“用户名包含关键词”来判断 CustomerSupport（更灵活）
    你实际用的是 'cui-customerSupport' 这种，也能命中
    """
    if not user:
        return False
    uname = (getattr(user, "username", "") or "").strip().lower()
    return any(k in uname for k in CS_KEYWORDS) and (not is_ops_user(user))


def ticket_is_closed(ticket: Ticket) -> bool:
    """
    ✅ 已结束不显示待跟进（除非重新开启）
    兼容：status 存储值 / choices label（get_status_display）
    """
    raw = str(getattr(ticket, "status", "") or "").strip()
    raw_low = raw.lower()

    label = ""
    if hasattr(ticket, "get_status_display"):
        try:
            label = str(ticket.get_status_display() or "").strip()
        except Exception:
            label = ""
    label_low = label.lower()

    # 重新开启：永远不算关闭
    if ("重新开启" in raw) or ("reopen" in raw_low) or ("重新开启" in label) or ("reopen" in label_low):
        return False

    # 只要任意一个命中“已结束/关闭/closed”
    keywords_cn = ("已结束", "结束", "关闭", "已关闭")
    keywords_en = ("closed", "done", "finished", "resolved")

    if any(k in raw for k in keywords_cn) or any(k in label for k in keywords_cn):
        return True
    if any(k in raw_low for k in keywords_en) or any(k in label_low for k in keywords_en):
        return True

    return False


def ticket_is_new(ticket: Ticket) -> bool:
    """
    新建：用 status 或 label 双保险
    """
    raw = str(getattr(ticket, "status", "") or "").strip()
    raw_low = raw.lower()

    label = ""
    if hasattr(ticket, "get_status_display"):
        try:
            label = str(ticket.get_status_display() or "").strip()
        except Exception:
            label = ""
    label_low = label.lower()

    if "新建" in raw or "new" in raw_low or "open" in raw_low:
        return True
    if "新建" in label or "new" in label_low or "open" in label_low:
        return True
    return False


# ==========
# ✅ 新增：按“谁跟进（谁需要回复）”的筛选器（修正版）
# ==========
class FollowUpByFilter(admin.SimpleListFilter):
    title = "跟进人"
    parameter_name = "followup_by"

    def lookups(self, request, model_admin):
        return (
            ("ops", "待 zhang-SupportOps 跟进"),
            ("cs", "待 CustomerSupport 跟进"),
            ("admin", "待 admin 跟进"),
            ("closed", "已结束/关闭"),
        )

    def queryset(self, request, queryset):
        val = self.value()
        if not val:
            return queryset

        # ---- 1) 取“最后一条评论作者 username” & 是否有评论 ----
        last_comment_qs = TicketComment.objects.filter(ticket=OuterRef("pk")).order_by("-created_at")
        last_author_username = Subquery(last_comment_qs.values("author__username")[:1])
        last_pending_to = Subquery(last_comment_qs.values("pending_followup_to")[:1])
        has_comments = Exists(TicketComment.objects.filter(ticket=OuterRef("pk")))

        qs = queryset.annotate(
            _has_comments=has_comments,
            _last_author_username=last_author_username,
            _last_pending_to=last_pending_to,
        )

        # ---- 2) DB 层关闭判断（关键修正：closed_mark 且不是 reopen）----
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

        is_closed_q = closed_mark_q & ~reopen_q  # ✅ 重新开启不算关闭

        if val == "closed":
            return qs.filter(is_closed_q)

        # “未关闭”的工单（包含重新开启）
        open_qs = qs.exclude(is_closed_q)

        # ---- 3) OPS 判断（最后评论作者是 OPS）----
        ops_uname = (OPS_USERNAME or "").strip()
        last_is_ops = Q(_last_author_username__iexact=ops_uname)
        # 创建者是 OPS（用于新建但无评论的工单）
        creator_is_ops = Q(created_by__username__iexact=ops_uname)
        # 新建状态的 DB 层判断（用于无评论且为新建的工单）
        new_mark_q = Q(status__icontains="新建") | Q(status__icontains="new") | Q(status__icontains="open")

        # ---- 4) 按 pending_followup 的规则复刻（关键修正）----
        # 你的 pending_followup 实际规则：
        # - 关闭：不显示（已在 open_qs 里排除）
        # - last_comment is None：永远是“待 OPS”
        # - last_comment.author 是 OPS：待 CS
        # - 其他情况（CS 或 其他人）：待 OPS

        if val == "cs":
            # ✅ 待 CS：
            # - 有评论且最后评论是 OPS；或
            # - 无评论且创建者是 OPS 且 状态为 新建（OPS 新建票据需 CS 回复）
            return open_qs.filter(
                Q(_last_pending_to="cs")
                | (
                    (Q(_last_pending_to="") | Q(_last_pending_to__isnull=True))
                    & (
                        (Q(_has_comments=True) & last_is_ops)
                        | (Q(_has_comments=False) & creator_is_ops & new_mark_q)
                    )
                )
            )

        if val == "admin":
            # ✅ 待 admin：最后评论明确指定 pending_followup_to=admin
            return open_qs.filter(_last_pending_to="admin")

        if val == "ops":
            # ✅ 待 OPS：
            # - 无评论但不是（创建者为 OPS 且状态新建）的情况；或
            # - 有评论且最后不是 OPS
            return open_qs.filter(
                Q(_last_pending_to="ops")
                | (
                    (Q(_last_pending_to="") | Q(_last_pending_to__isnull=True))
                    & (
                        (Q(_has_comments=False) & ~(creator_is_ops & new_mark_q))
                        | (Q(_has_comments=True) & ~last_is_ops)
                    )
                )
            )

        return open_qs


# ==========
# ✅ 新增：按“是否有更新”筛选（基于最后一条评论是否未读）
# ==========
class UpdatedFilter(admin.SimpleListFilter):
    title = "更新"
    parameter_name = "updated"

    def lookups(self, request, model_admin):
        return (
            ("unread", "有更新(未读)"),
        )

    def queryset(self, request, queryset):
        val = self.value()
        if val != "unread":
            return queryset
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return queryset.none()

        last_comment_qs = TicketComment.objects.filter(ticket=OuterRef("pk")).order_by("-created_at")
        last_comment_id = Subquery(last_comment_qs.values("id")[:1])
        last_comment_author_id = Subquery(last_comment_qs.values("author_id")[:1])

        read_status_qs = TicketReadStatus.objects.filter(ticket=OuterRef("pk"), user=request.user)
        last_seen_comment_id = Subquery(read_status_qs.values("last_seen_comment_id")[:1])

        qs = queryset.annotate(
            _last_comment_id=last_comment_id,
            _last_comment_author_id=last_comment_author_id,
            _last_seen_comment_id=last_seen_comment_id,
        )

        return qs.filter(
            _last_comment_id__isnull=False
        ).exclude(
            _last_comment_author_id=request.user.id
        ).filter(
            Q(_last_seen_comment_id__isnull=True) | Q(_last_seen_comment_id__lt=F("_last_comment_id"))
        )


# ==========
# Inline：评论附件（挂在 TicketCommentAdmin 里）
# ==========
class TicketAttachmentInline(admin.TabularInline):
    model = TicketAttachment
    extra = 1
    fields = ("file", "uploaded_by")
    readonly_fields = ("uploaded_by",)  # ✅ 自动绑定当前用户，显示但不可改
    can_delete = True


# ==========
# ✅ Inline：Ticket 主贴页面的“主贴附件”
# 只显示 comment = None 的附件，避免和评论附件重复
# ==========
class TicketMainAttachmentInline(admin.TabularInline):
    model = TicketAttachment
    extra = 1
    can_delete = True
    fields = ("file", "file_link", "uploaded_by", "created_at")
    readonly_fields = ("file_link", "uploaded_by", "created_at")
    ordering = ("-created_at",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(comment__isnull=True)

    @admin.display(description="链接")
    def file_link(self, obj: TicketAttachment):
        if not obj or not getattr(obj, "file", None):
            return "-"
        try:
            url = obj.file.url
        except Exception:
            return "-"
        name = obj.file.name.rsplit("/", 1)[-1]
        return format_html("<a href='{}' target='_blank'>{}</a>", url, name)


# ==========
# Inline：Ticket 页面里的评论列表
# ==========
class TicketCommentInline(admin.TabularInline):
    model = TicketComment
    extra = 0
    fields = ("author", "is_factory_reply", "content", "pending_followup_to", "created_at", "attachments_link")
    readonly_fields = ("author", "created_at", "attachments_link")
    ordering = ("created_at",)

    def get_fields(self, request, obj=None):
        """只有 superuser/staff 可以看到并编辑 `pending_followup_to` 内联字段"""
        fields = list(self.fields)
        if not (request.user.is_superuser or request.user.is_staff):
            if "pending_followup_to" in fields:
                fields.remove("pending_followup_to")
        return fields

    @admin.display(description="附件")
    def attachments_link(self, obj: TicketComment):
        if not obj or not obj.pk:
            return "-"
        cnt = getattr(obj, "attachments", None).count() if hasattr(obj, "attachments") else 0

        try:
            url = reverse("admin:tickets_ticketcomment_change", args=[obj.pk])
        except Exception:
            url = f"/admin/tickets/ticketcomment/{obj.pk}/change/"

        return format_html("<a href='{}'>管理附件 ({})</a>", url, cnt)


# ==========
# 移除 TicketCommentAdminInline（与 TicketCommentInline 逻辑重复）
# 用户在单独的评论编辑页面修改 pending_followup_to
# =========


# ==========
# Ticket Admin
# ==========
@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    inlines = [TicketMainAttachmentInline, TicketCommentInline]
    show_facets = admin.ShowFacets.ALWAYS

    list_display = (
        "id",
        "title",
        "update_badge",
        "status",
        "priority",
        "order_no",
        "customer_name",
        "product_name",
        "created_by",
        "created_at",
        "pending_followup",
        "last_update_time",
    )
    list_display_links = ("id", "title")

    # ✅✅ 新增“跟进人/更新”筛选
    list_filter = ("status", "priority", FollowUpByFilter, UpdatedFilter)

    search_fields = ("title", "order_no", "customer_name", "product_name", "description")
    list_editable = ("status", "priority")
    ordering = ("-created_at",)
    
    # ✅ 性能优化：分页、查询优化、日期导航
    list_per_page = 20  # 每页 20 条工单（避免一次加载过多数据）
    list_select_related = ("created_by",)  # 优化外键查询，减少 N+1 问题
    date_hierarchy = "created_at"  # 按日期层级筛选，快速定位工单

    fields = (
        "title",
        "customer_name",
        "order_no",
        "product_name",
        "description",
        "status",
        "priority",
        "created_by",
    )
    readonly_fields = ("created_by",)

    def get_queryset(self, request):
        self.request = request
        return super().get_queryset(request)

    # 暂时使用普通用户版的 Inline（避免权限检查导致的错误）
    # TODO: 修复 get_inlines 方法后重新启用

    def _get_last_comment(self, obj: Ticket):
        if not hasattr(obj, "_last_comment_cache"):
            obj._last_comment_cache = obj.comments.select_related("author").order_by("-created_at").first()
        return obj._last_comment_cache

    def _mark_ticket_read(self, request, obj: Ticket):
        last_comment = self._get_last_comment(obj)
        if not last_comment:
            return
        if getattr(last_comment, "author_id", None) == request.user.id:
            return
        TicketReadStatus.objects.update_or_create(
            ticket=obj,
            user=request.user,
            defaults={"last_seen_comment": last_comment},
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        response = super().change_view(request, object_id, form_url, extra_context)
        if request.method == "GET" and request.GET.get("skip_read") != "1":
            obj = self.get_object(request, object_id)
            if obj is not None:
                self._mark_ticket_read(request, obj)
        return response

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/mark-unread/",
                self.admin_site.admin_view(self.mark_unread_view),
                name="tickets_ticket_mark_unread",
            ),
        ]
        return custom_urls + urls

    def mark_unread_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if obj is None:
            messages.error(request, "工单不存在")
            return redirect("admin:tickets_ticket_changelist")

        last_comment = self._get_last_comment(obj)
        if last_comment:
            TicketReadStatus.objects.update_or_create(
                ticket=obj,
                user=request.user,
                defaults={"last_seen_comment": None},
            )
            messages.success(request, "已标记为未读")
        else:
            messages.info(request, "该工单暂无回复")

        next_url = request.GET.get("next")
        if next_url:
            return redirect(next_url)
        return redirect("admin:tickets_ticket_changelist")

    def save_model(self, request, obj, form, change):
        if not change and hasattr(obj, "created_by_id") and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)

        for obj in getattr(formset, "deleted_objects", []):
            obj.delete()

        for obj in instances:
            if isinstance(obj, TicketComment):
                if hasattr(obj, "author_id") and not obj.author_id:
                    obj.author = request.user

            if isinstance(obj, TicketAttachment):
                if hasattr(obj, "uploaded_by_id") and not obj.uploaded_by_id:
                    obj.uploaded_by = request.user
                if hasattr(obj, "comment_id") and obj.comment_id:
                    obj.comment = None

            obj.save()

        formset.save_m2m()

    @admin.display(description="最后更新")
    def last_update_time(self, obj: Ticket):
        last_comment = self._get_last_comment(obj)
        return last_comment.created_at if last_comment else obj.created_at

    @admin.display(description="更新")
    def update_badge(self, obj: Ticket):
        if not hasattr(self, "request") or not getattr(self.request, "user", None):
            return "-"
        last_comment = self._get_last_comment(obj)
        if not last_comment:
            return "-"
        if getattr(last_comment, "author_id", None) == self.request.user.id:
            return "-"
        status = TicketReadStatus.objects.filter(ticket=obj, user=self.request.user).first()
        if status and status.last_seen_comment_id and status.last_seen_comment_id >= last_comment.id:
            return "-"
        return format_html("<span style='font-weight:700;color:#d9534f'>NEW</span>")

    @admin.display(description="待跟进")
    def pending_followup(self, obj: Ticket):
        if ticket_is_closed(obj):
            return format_html("<span style='color:#888'>-</span>")

        last_comment = self._get_last_comment(obj)

        # ✅ 优先检查管理员是否手动指定了待跟进人（只有明确指定时才使用）
        if last_comment is not None:
            pending_to = getattr(last_comment, "pending_followup_to", "").strip()
            if pending_to and pending_to == "ops":
                return format_html("<span style='font-weight:700;color:#f0ad4e'>待zhang-SupportOps回复</span>")
            elif pending_to and pending_to == "cs":
                return format_html("<span style='font-weight:700;color:#5cb85c'>待CustomerSupport回复客人</span>")
            elif pending_to and pending_to == "admin":
                return format_html("<span style='font-weight:700;color:#d9534f'>需admin来处理</span>")

        if (last_comment is None) and ticket_is_new(obj):
            # 如果工单创建者是 OPS，则等待 CustomerSupport 回复客人
            creator = getattr(obj, "created_by", None)
            if is_ops_user(creator):
                return format_html("<span style='font-weight:700;color:#5cb85c'>待CustomerSupport回复客人</span>")

            return format_html("<span style='font-weight:700;color:#f0ad4e'>待zhang-SupportOps回复</span>")

        if last_comment is not None:
            author = last_comment.author

            if is_ops_user(author):
                return format_html("<span style='font-weight:700;color:#5cb85c'>待CustomerSupport回复客人</span>")

            if is_customer_support_user(author):
                return format_html("<span style='font-weight:700;color:#f0ad4e'>待zhang-SupportOps回复</span>")

        return format_html("<span style='font-weight:700;color:#f0ad4e'>待zhang-SupportOps回复</span>")


# ==========
# TicketComment Admin（这里支持上传附件）
# ==========
@admin.register(TicketComment)
class TicketCommentAdmin(admin.ModelAdmin):
    list_display = ("id", "ticket", "ticket_status", "short_content", "author", "is_factory_reply", "pending_followup_to_display", "created_at")
    list_select_related = ("ticket", "author")
    ordering = ("-created_at",)

    list_filter = ("is_factory_reply", "created_at", "ticket__status", "pending_followup_to")
    search_fields = ("ticket__id", "ticket__order_no", "ticket__title", "content", "author__username")

    readonly_fields = ("author",)
    inlines = [TicketAttachmentInline]

    def get_fields(self, request, obj=None):
        """只有 superuser/staff 可以看到和编辑 pending_followup_to 字段"""
        if request.user.is_superuser or request.user.is_staff:
            return ("ticket", "author", "is_factory_reply", "content", "pending_followup_to")
        else:
            return ("ticket", "author", "is_factory_reply", "content")

    def get_list_display(self, request):
        """只有 superuser/staff 可以在列表中看到 pending_followup_to_display"""
        list_display = list(self.list_display)
        if not (request.user.is_superuser or request.user.is_staff):
            # 非管理员用户从列表移除 pending_followup_to_display
            if "pending_followup_to_display" in list_display:
                list_display.remove("pending_followup_to_display")
        return list_display

    def save_model(self, request, obj, form, change):
        if not change and hasattr(obj, "author_id") and not obj.author_id:
            obj.author = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="内容")
    def short_content(self, obj):
        return (obj.content or "")[:60]

    @admin.display(description="指定待跟进")
    def pending_followup_to_display(self, obj):
        if not obj.pending_followup_to:
            return "-"
        return dict(TicketComment.PendingFollowupTo.choices).get(obj.pending_followup_to, obj.pending_followup_to)

    @admin.display(description="工单状态", ordering="ticket__status")
    def ticket_status(self, obj):
        return obj.ticket.get_status_display() if hasattr(obj.ticket, "get_status_display") else obj.ticket.status

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)

        for obj in getattr(formset, "deleted_objects", []):
            obj.delete()

        for obj in instances:
            if isinstance(obj, TicketAttachment):
                if not obj.comment_id:
                    obj.comment = form.instance

                if not obj.ticket_id and getattr(form.instance, "ticket_id", None):
                    obj.ticket = form.instance.ticket

                if hasattr(obj, "uploaded_by_id") and not obj.uploaded_by_id:
                    obj.uploaded_by = request.user

            obj.save()

        formset.save_m2m()


# ==========
# TicketAttachment Admin（单独管理：uploaded_by 自动绑定）
# ==========
@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "ticket", "comment", "file", "uploaded_by", "created_at")
    list_select_related = ("ticket", "comment", "uploaded_by")
    search_fields = ("ticket__id", "ticket__order_no", "uploaded_by__username")
    ordering = ("-created_at",)

    readonly_fields = ("uploaded_by",)

    def save_model(self, request, obj, form, change):
        if not change and hasattr(obj, "uploaded_by_id") and not obj.uploaded_by_id:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)
