import csv

from django.contrib import admin, messages
from django.contrib.auth.models import Group
from django.db import models
from django.http import HttpResponse
from django.utils import timezone

from .models import (
    ShopifyInstallation,
    ShopifyOrder,
    ShopifyProduct,
    ShopifyOrderItem,
    ShippingCostRule,
    SettlementBatch,
)


class ShopifyRoleAdminMixin:
    SHENZHEN_GROUP = "Shenzhen Warehouse"
    FINANCE_GROUPS = {"Finance", "Admin"}

    def _user_groups(self, request):
        if not request.user.is_authenticated:
            return set()
        return set(request.user.groups.values_list("name", flat=True))

    def user_role(self, request):
        if request.user.is_superuser:
            return "super_admin"
        groups = self._user_groups(request)
        if self.SHENZHEN_GROUP in groups:
            return "shenzhen_warehouse"
        if groups & self.FINANCE_GROUPS:
            return "finance_admin"
        return "other"

    def is_shenzhen_user(self, request):
        return self.user_role(request) == "shenzhen_warehouse"

    def is_finance_user(self, request):
        return self.user_role(request) == "finance_admin"

    def is_super_admin(self, request):
        return request.user.is_superuser

    def is_role_allowed(self, request):
        return self.is_super_admin(request) or self.is_finance_user(request) or self.is_shenzhen_user(request)

    def has_module_permission(self, request):
        return self.is_role_allowed(request)

    def has_view_permission(self, request, obj=None):
        if not self.is_role_allowed(request):
            return False
        if self.is_shenzhen_user(request) and obj is not None:
            return obj.is_shenzhen_order or obj.current_location == "shenzhen"
        return True

    def has_change_permission(self, request, obj=None):
        if not self.is_role_allowed(request):
            return False
        if self.is_shenzhen_user(request) and obj is not None:
            return obj.is_shenzhen_order or obj.current_location == "shenzhen"
        return True

    def has_add_permission(self, request):
        return self.is_super_admin(request)

    def has_delete_permission(self, request, obj=None):
        return self.is_super_admin(request)


class ShopifyOrderItemInline(admin.TabularInline):
    model = ShopifyOrderItem
    extra = 0
    fields = (
        "sku",
        "product_title",
        "variant_title",
        "quantity",
        "shopify_product_id",
        "shopify_variant_id",
        "matched_product",
        "fallback_product_display",
        "product_match_status",
        "edit_product_link",
        "product_cost_rmb_from_product",
        "locked_product_cost_rmb",
        "weight_kg_from_product",
        "length_cm_from_product",
        "width_cm_from_product",
        "height_cm_from_product",
        "volume_weight_kg_from_product",
        "locked_shipping_cost_rmb",
        "handling_fee_rmb",
        "total_cost_rmb",
    )
    readonly_fields = (
        "total_cost_rmb",
        "sku",
        "product_title",
        "variant_title",
        "shopify_product_id",
        "shopify_variant_id",
        "fallback_product_display",
        "product_match_status",
        "edit_product_link",
        "product_cost_rmb_from_product",
        "weight_kg_from_product",
        "length_cm_from_product",
        "width_cm_from_product",
        "height_cm_from_product",
        "volume_weight_kg_from_product",
    )
    show_change_link = False

    def _is_shenzhen_user(self, request):
        return request.user.is_authenticated and request.user.groups.filter(name="Shenzhen Warehouse").exists()

    def _is_allowed_order_item_user(self, request):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        groups = set(request.user.groups.values_list("name", flat=True))
        return bool(groups & {"Shenzhen Warehouse", "Finance", "Admin"})

    def has_view_permission(self, request, obj=None):
        return self._is_allowed_order_item_user(request)

    def has_change_permission(self, request, obj=None):
        return self._is_allowed_order_item_user(request)

    def edit_product_link(self, obj):
        if obj.matched_product:
            from django.urls import reverse
            from django.utils.html import format_html
            url = reverse("admin:shopify_sync_shopifyproduct_change", args=[obj.matched_product.id])
            return format_html('<a class="button" href="{}" target="_blank">编辑产品资料</a>', url)
        return "无产品关联"
    edit_product_link.short_description = "产品编辑"

    def fallback_product_display(self, obj):
        if obj.matched_product:
            return ""
        if obj.shopify_product_id:
            fallback = ShopifyProduct.objects.filter(
                installation=obj.order.installation,
                shopify_product_id=obj.shopify_product_id,
            ).first()
            return fallback or "—"
        return "—"
    fallback_product_display.short_description = "Fallback Product"

    def product_match_status(self, obj):
        if obj.matched_product:
            return "Matched"
        if obj.shopify_product_id:
            exists = ShopifyProduct.objects.filter(
                installation=obj.order.installation,
                shopify_product_id=obj.shopify_product_id,
            ).exists()
            return "Fallback" if exists else "Missing product"
        return "No product id"
    product_match_status.short_description = "Product Match Status"

    def product_cost_rmb_from_product(self, obj):
        if obj.matched_product:
            return obj.matched_product.product_cost_rmb
        return "—"
    product_cost_rmb_from_product.short_description = "产品成本(¥)"

    def weight_kg_from_product(self, obj):
        if obj.matched_product:
            return obj.matched_product.weight_kg
        return "—"
    weight_kg_from_product.short_description = "重(kg)"

    def length_cm_from_product(self, obj):
        if obj.matched_product:
            return obj.matched_product.length_cm
        return "—"
    length_cm_from_product.short_description = "长(cm)"

    def width_cm_from_product(self, obj):
        if obj.matched_product:
            return obj.matched_product.width_cm
        return "—"
    width_cm_from_product.short_description = "宽(cm)"

    def height_cm_from_product(self, obj):
        if obj.matched_product:
            return obj.matched_product.height_cm
        return "—"
    height_cm_from_product.short_description = "高(cm)"

    def volume_weight_kg_from_product(self, obj):
        if obj.matched_product:
            return obj.matched_product.volume_weight_kg
        return "—"
    volume_weight_kg_from_product.short_description = "体积重(kg)"

    def get_readonly_fields(self, request, obj=None):
        readonly = list(self.readonly_fields)
        if self._is_shenzhen_user(request):
            readonly.extend(
                [
                    "quantity",
                    "fulfillment_location",
                    "matched_product",
                    "fulfilled_quantity",
                    "fulfillment_id",
                    "item_fulfilled_at",
                    "locked_shipping_cost_rmb",
                    "handling_fee_rmb",
                ]
            )
        return readonly


@admin.register(ShopifyInstallation)
class ShopifyInstallationAdmin(admin.ModelAdmin):
    list_display = ("shop", "scope", "installed_at", "updated_at")
    readonly_fields = ("installed_at", "updated_at")
    search_fields = ("shop", "scope")

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(ShopifyOrder)
class ShopifyOrderAdmin(ShopifyRoleAdminMixin, admin.ModelAdmin):
    change_list_template = "admin/shopify_sync_changelist.html"
    inlines = [ShopifyOrderItemInline]
    actions = [
        "recalculate_order_shipping_cost",
        "copy_product_cost_to_items",
        "add_to_settlement_batch",
        "mark_cost_confirmed",
        "mark_pending_payment",
        "mark_paid",
    ]
    list_display = (
        "order_name",
        "customer_name",
        "shipping_country",
        "original_location",
        "current_location",
        "settlement_status",
        "transferred_at",
        "items_count",
        "total_locked_cost_rmb",
        "is_cost_completed",
        "missing_product_data",
        "order_created_at",
    )
    readonly_fields = (
        "synced_at",
        "updated_at",
        "total_actual_weight_kg",
        "total_volume_weight_kg",
        "chargeable_weight_kg",
        "order_shipping_cost_rmb",
        "order_handling_fee_rmb",
        "total_locked_cost_rmb",
        "cost_calculated_at",
        "transferred_at",
    )
    search_fields = ("order_name", "order_number", "customer_name", "customer_email")
    list_filter = (
        "settlement_status",
        "is_shenzhen_order",
        "current_location",
        "shipping_country",
        "order_created_at",
    )
    list_editable = ("settlement_status",)
    fieldsets = (
        (
            "订单信息",
            {
                "fields": (
                    "shopify_order_id",
                    "order_number",
                    "order_name",
                    "customer_name",
                    "customer_email",
                    "shipping_name",
                    "shipping_address1",
                    "shipping_address2",
                    "shipping_city",
                    "shipping_province",
                    "shipping_country",
                    "shipping_zip",
                    "shipping_phone",
                    "currency",
                    "total_price",
                    "financial_status",
                    "fulfillment_status",
                    "order_created_at",
                )
            },
        ),
        (
            "履约与成本",
            {
                "fields": (
                    "current_location",
                    "is_shenzhen_order",
                    "settlement_status",
                    "settlement_batch",
                    "transferred_at",
                    "transfer_note",
                    "tracking_number",
                    "warehouse_note",
                    "total_actual_weight_kg",
                    "total_volume_weight_kg",
                    "chargeable_weight_kg",
                    "order_shipping_cost_rmb",
                    "order_handling_fee_rmb",
                    "total_locked_cost_rmb",
                    "cost_calculated_at",
                    "cost_calculation_note",
                )
            },
        ),
        (
            "原始仓库信息",
            {
                "fields": (
                    "original_location_raw",
                    "original_location",
                    "current_location_raw",
                )
            },
        ),
        ("时间戳", {"fields": ("synced_at", "updated_at")}),
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if self.is_shenzhen_user(request):
            return queryset.filter(models.Q(is_shenzhen_order=True) | models.Q(current_location="shenzhen"))
        return queryset

    def get_list_display(self, request):
        if self.is_shenzhen_user(request):
            return (
                "order_name",
                "customer_name",
                "shipping_country",
                "original_location",
                "current_location",
                "settlement_status",
                "transferred_at",
                "items_count",
                "total_locked_cost_rmb",
                "is_cost_completed",
                "tracking_number",
                "order_created_at",
            )
        return super().get_list_display(request)

    def items_count(self, obj):
        return obj.order_items.count()
    items_count.short_description = "Item Count"

    def total_locked_cost_rmb(self, obj):
        if obj.total_locked_cost_rmb is not None:
            return obj.total_locked_cost_rmb
        total = obj.order_items.aggregate(total=models.Sum("total_cost_rmb"))["total"]
        return total or 0
    total_locked_cost_rmb.short_description = "Total Locked Cost"

    def is_cost_completed(self, obj):
        for item in obj.order_items.all():
            if (item.locked_product_cost_rmb is None or
                item.locked_shipping_cost_rmb is None or
                item.handling_fee_rmb is None):
                return False
        return True
    is_cost_completed.short_description = "Cost Completed"
    is_cost_completed.boolean = True

    def missing_product_data(self, obj):
        missing_skus = [
            str(sku) for sku in (getattr(obj, "missing_product_data", []) or [])
            if sku is not None
        ]
        if missing_skus:
            from django.utils.html import format_html
            return format_html(
                '<span style="color: red; font-weight: bold;">⚠ {}</span>',
                ', '.join(missing_skus)
            )
        return "✓"
    missing_product_data.short_description = "产品资料缺失"

    def get_search_fields(self, request):
        if self.is_shenzhen_user(request):
            return ("order_name", "order_number", "customer_name", "shipping_country")
        return super().get_search_fields(request)

    def get_fieldsets(self, request, obj=None):
        if self.is_shenzhen_user(request):
            return (
                (
                    "深圳仓订单信息",
                    {
                        "fields": (
                            "shopify_order_id",
                            "order_number",
                            "order_name",
                            "customer_name",
                            "shipping_name",
                            "shipping_address1",
                            "shipping_address2",
                            "shipping_city",
                            "shipping_province",
                            "shipping_country",
                            "shipping_zip",
                            "current_location",
                            "is_shenzhen_order",
                            "settlement_status",
                            "tracking_number",
                            "tracking_company",
                            "tracking_url",
                            "fulfilled_at",
                            "fulfillment_status_raw",
                            "warehouse_note",
                        )
                    },
                ),
                ("时间戳", {"fields": ("synced_at", "updated_at", "last_order_synced_at")} ),
            )
        return super().get_fieldsets(request, obj)

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if self.is_shenzhen_user(request):
            readonly.extend([
                "shopify_order_id",
                "order_name",
                "order_number",
                "customer_name",
                "customer_email",
                "financial_status",
                "fulfillment_status",
                "currency",
                "shipping_phone",
                "total_price",
                "order_created_at",
                "original_location_raw",
                "original_location",
                "current_location_raw",
                "current_location",
                "settlement_batch",
                "transferred_at",
                "transfer_note",
                "is_shenzhen_order",
                "tracking_number",
                "tracking_company",
                "tracking_url",
                "fulfilled_at",
                "fulfillment_status_raw",
            ])
            if obj is None or obj.settlement_status != "pending_warehouse":
                readonly.append("settlement_status")
        return readonly

    def save_model(self, request, obj, form, change):
        if self.is_shenzhen_user(request) and change:
            old_obj = self.model.objects.filter(pk=obj.pk).first()
            if old_obj is not None:
                if old_obj.settlement_status != "pending_warehouse" and obj.settlement_status != old_obj.settlement_status:
                    obj.settlement_status = old_obj.settlement_status
                    messages.warning(request, "深圳仓只能在 pending_warehouse 状态下修改结算状态为 cost_confirmed。")
                elif old_obj.settlement_status == "pending_warehouse" and obj.settlement_status not in ["pending_warehouse", "cost_confirmed"]:
                    obj.settlement_status = old_obj.settlement_status
                    messages.warning(request, "深圳仓只能将结算状态从 pending_warehouse 修改为 cost_confirmed。")
        super().save_model(request, obj, form, change)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if self.is_shenzhen_user(request):
            for action_name in ["add_to_settlement_batch", "mark_pending_payment", "mark_paid"]:
                if action_name in actions:
                    del actions[action_name]
        return actions

    def recalculate_order_shipping_cost(self, request, queryset):
        from .sync_helpers import recalculate_order_shipping_cost as recalc_helper
        updated_count = 0
        error_count = 0
        for order in queryset:
            success = recalc_helper(order)
            if success:
                updated_count += 1
            else:
                error_count += 1
        self.message_user(
            request,
            f"重新计算完成：{updated_count} 个订单计算成功，{error_count} 个订单无法计算。"
        )
    recalculate_order_shipping_cost.short_description = "重新计算订单运费"

    def copy_product_cost_to_items(self, request, queryset):
        if not (self.is_shenzhen_user(request) or self.is_finance_user(request) or self.is_super_admin(request)):
            self.message_user(request, "只有深圳仓或 Finance 可以执行此操作。")
            return
        
        copied_count = 0
        for order in queryset:
            for item in order.order_items.all():
                if item.locked_product_cost_rmb is None and item.matched_product and item.matched_product.product_cost_rmb:
                    item.locked_product_cost_rmb = item.matched_product.product_cost_rmb
                    item.save(update_fields=["locked_product_cost_rmb"])
                    copied_count += 1
        
        self.message_user(request, f"已复制 {copied_count} 个订单项目的产品成本。")
    copy_product_cost_to_items.short_description = "复制产品成本到订单项"

    def mark_cost_confirmed(self, request, queryset):
        if not self.is_shenzhen_user(request):
            self.message_user(request, "只有深圳仓用户可以执行此操作。")
            return
        valid_orders = queryset.filter(settlement_status__in=["pending_warehouse", "warehouse_fulfilled"])
        completed_orders = [order for order in valid_orders if self.is_cost_completed(order)]
        updated = ShopifyOrder.objects.filter(pk__in=[order.pk for order in completed_orders]).update(settlement_status="cost_confirmed")
        skipped = valid_orders.count() - len(completed_orders)
        if updated:
            self.message_user(request, f"成功标记 {updated} 个订单为 cost_confirmed。")
        if skipped:
            self.message_user(request, f"有 {skipped} 个订单因成本未完整而未标记。")

    mark_cost_confirmed.short_description = "标记成本已确认"

    def mark_pending_payment(self, request, queryset):
        if not (self.is_finance_user(request) or self.is_super_admin(request)):
            self.message_user(request, "只有 Finance 或超级管理员可以执行此操作。")
            return
        valid_orders = queryset.filter(settlement_status="cost_confirmed")
        updated = valid_orders.update(settlement_status="pending_payment")
        if updated != queryset.count():
            self.message_user(request, f"只有 {updated} 个订单可以标记为 pending_payment（必须是 cost_confirmed 状态）。")
        else:
            self.message_user(request, f"成功标记 {updated} 个订单为 pending_payment。")

    mark_pending_payment.short_description = "标记待支付"

    def mark_paid(self, request, queryset):
        if not (self.is_super_admin(request) or self.is_finance_user(request)):
            self.message_user(request, "只有 Finance 或超级管理员可以执行此操作。")
            return
        valid_orders = queryset.filter(settlement_status="pending_payment")
        updated = valid_orders.update(settlement_status="paid")
        if updated != queryset.count():
            self.message_user(request, f"只有 {updated} 个订单可以标记为 paid（必须是 pending_payment 状态）。")
        else:
            self.message_user(request, f"成功标记 {updated} 个订单为 paid。")

    mark_paid.short_description = "标记已支付"

    def add_to_settlement_batch(self, request, queryset):
        if not (self.is_finance_user(request) or self.is_super_admin(request)):
            self.message_user(request, "只有 Finance 或超级管理员可以执行此操作。")
            return

        eligible_orders = queryset.filter(
            settlement_status="pending_payment",
            is_shenzhen_order=True,
            total_locked_cost_rmb__gt=0,
            settlement_batch__isnull=True,
        )
        invalid_count = queryset.count() - eligible_orders.count()

        if eligible_orders.count() == 0:
            self.message_user(request, "没有符合条件的订单可加入新的结算批次。")
            return

        from .models import SettlementBatch

        batch_no = self._generate_batch_no()
        batch = SettlementBatch.objects.create(
            batch_no=batch_no,
            status="pending_payment",
            total_amount_rmb=0,
            created_by=request.user.get_username(),
        )
        for order in eligible_orders:
            order.settlement_batch = batch
            order.save(update_fields=["settlement_batch"])
        batch.update_total_amount()

        self.message_user(
            request,
            f"已创建结算批次 {batch_no}，并将 {eligible_orders.count()} 个订单加入批次。"
        )
    add_to_settlement_batch.short_description = "添加所选订单到新结算批次"

    def _generate_batch_no(self):
        from .models import SettlementBatch
        now = timezone.now()
        prefix = now.strftime("%Y%m")
        latest = SettlementBatch.objects.filter(batch_no__startswith=prefix).order_by("-batch_no").first()
        next_seq = 1
        if latest and latest.batch_no:
            try:
                next_seq = int(latest.batch_no.split("-")[-1]) + 1
            except ValueError:
                next_seq = 1
        return f"{prefix}-{next_seq:03d}"


@admin.register(SettlementBatch)
class SettlementBatchAdmin(ShopifyRoleAdminMixin, admin.ModelAdmin):
    list_display = (
        "batch_no",
        "status",
        "total_amount_rmb",
        "created_by",
        "created_at",
        "paid_at",
    )
    readonly_fields = ("created_at", "paid_at")
    actions = ["mark_batch_paid", "export_batch_csv"]
    search_fields = ("batch_no", "created_by", "note")
    list_filter = ("status", "created_at")

    def get_actions(self, request):
        actions = super().get_actions(request)
        if self.is_shenzhen_user(request):
            for action_name in ["mark_batch_paid", "export_batch_csv"]:
                if action_name in actions:
                    del actions[action_name]
        return actions

    def mark_batch_paid(self, request, queryset):
        if not (self.is_super_admin(request) or self.is_finance_user(request)):
            self.message_user(request, "只有 Finance 或超级管理员可以执行此操作。")
            return
        updated = 0
        for batch in queryset:
            batch.status = "paid"
            batch.paid_at = timezone.now()
            batch.save(update_fields=["status", "paid_at"])
            batch.orders.update(settlement_status="paid")
            updated += 1
        self.message_user(request, f"已标记 {updated} 个结算批次为已支付。")
    mark_batch_paid.short_description = "标记结算批次已支付"

    def export_batch_csv(self, request, queryset):
        rows = []
        for batch in queryset:
            for order in batch.orders.all().select_related("settlement_batch"):
                for item in order.order_items.all():
                    rows.append([
                        batch.batch_no,
                        order.order_name,
                        order.shipping_country,
                        item.sku,
                        item.quantity,
                        item.locked_product_cost_rmb,
                        item.locked_shipping_cost_rmb,
                        item.handling_fee_rmb,
                        item.total_cost_rmb,
                        order.tracking_number,
                    ])
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=settlement_reconciliation.csv"
        writer = csv.writer(response)
        writer.writerow([
            "batch_no",
            "order_name",
            "shipping_country",
            "sku",
            "quantity",
            "product_cost_rmb",
            "shipping_cost_rmb",
            "handling_fee_rmb",
            "total_cost_rmb",
            "tracking_number",
        ])
        for row in rows:
            writer.writerow(row)
        return response
    export_batch_csv.short_description = "导出结算批次对账 CSV"


@admin.register(ShopifyProduct)
class ShopifyProductAdmin(ShopifyRoleAdminMixin, admin.ModelAdmin):
    change_list_template = "admin/shopify_sync_changelist.html"
    list_display = (
        "product_title",
        "variant_title",
        "sku",
        "is_shenzhen_product",
        "product_cost_rmb",
        "weight_kg",
        "last_synced_at",
    )
    readonly_fields = ("created_at", "updated_at", "last_synced_at", "volume_weight_kg")
    search_fields = (
        "product_title",
        "variant_title",
        "sku",
        "shopify_product_id",
        "shopify_variant_id",
    )
    list_filter = ("is_shenzhen_product", "status", "vendor", "product_type")
    fieldsets = (
        (
            "Shopify 来源字段（自动同步）",
            {
                "fields": (
                    "shopify_product_id",
                    "shopify_variant_id",
                    "product_title",
                    "variant_title",
                    "sku",
                    "handle",
                    "vendor",
                    "product_type",
                    "status",
                    "image_url",
                    "inventory_quantity",
                    "last_synced_at",
                ),
                "description": "这些字段由 Shopify 自动同步，不建议手动修改。"
            },
        ),
        (
            "销售价格（仅管理员可见）",
            {
                "fields": ("price",),
                "classes": ("collapse",),
            },
        ),
        (
            "人工填写字段（后台编辑）",
            {
                "fields": (
                    "is_shenzhen_product",
                    "product_cost_rmb",
                    "weight_kg",
                    "length_cm",
                    "width_cm",
                    "height_cm",
                    "volume_weight_kg",
                    "shipping_note",
                ),
                "description": "这些字段用于成本计算和运费规则匹配。深圳仓可以编辑这些字段。"
            },
        ),
        ("时间戳", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return self.is_role_allowed(request)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return self.is_role_allowed(request)

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if self.is_shenzhen_user(request):
            # Remove price field for Shenzhen users
            return tuple(
                (name, data) for name, data in fieldsets
                if name != "销售价格（仅管理员可见）"
            )
        return fieldsets

    def get_list_display(self, request):
        if self.is_shenzhen_user(request):
            # Don't show price for Shenzhen users
            return (
                "product_title",
                "variant_title",
                "sku",
                "is_shenzhen_product",
                "product_cost_rmb",
                "weight_kg",
                "last_synced_at",
            )
        return super().get_list_display(request)

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if self.is_shenzhen_user(request):
            # Shenzhen users can edit cost and dimensions, but not price
            readonly.extend([
                "shopify_product_id",
                "shopify_variant_id",
                "product_title",
                "variant_title",
                "sku",
                "handle",
                "vendor",
                "product_type",
                "status",
                "image_url",
                "price",
                "inventory_quantity",
                "shipping_cost_rules",
                "last_synced_at",
            ])
        return readonly


@admin.register(ShippingCostRule)
class ShippingCostRuleAdmin(ShopifyRoleAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "country_code",
        "priority",
        "country_name",
        "min_weight_kg",
        "max_weight_kg",
        "price_per_kg_rmb",
        "base_fee_rmb",
        "handling_fee_rmb",
        "use_volume_weight",
        "is_active",
    )
    search_fields = ("country_code", "country_name", "name")
    list_filter = ("is_active", "country_code", "use_volume_weight")
    fieldsets = (
        (
            "基本信息",
            {
                "fields": ("name", "country_code", "country_name", "priority", "is_active", "note")
            },
        ),
        (
            "重量和尺寸限制",
            {
                "fields": (
                    "min_weight_kg",
                    "max_weight_kg",
                    "max_length_cm",
                    "max_width_cm",
                    "max_height_cm",
                    "use_volume_weight",
                    "volume_divisor",
                )
            },
        ),
        (
            "费用设置",
            {
                "fields": ("price_per_kg_rmb", "base_fee_rmb", "handling_fee_rmb")
            },
        ),
    )

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return self.is_role_allowed(request)


