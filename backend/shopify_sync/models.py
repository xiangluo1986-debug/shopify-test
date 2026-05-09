from django.conf import settings
from django.db import models
from django.utils import timezone


class ShopifyInstallation(models.Model):
    shop = models.CharField(max_length=255, unique=True)
    access_token = models.CharField(max_length=255)
    scope = models.CharField(max_length=511, blank=True)
    installed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.shop


class ShopifyOrder(models.Model):
    SETTLEMENT_STATUS_CHOICES = [
        ('pending_warehouse', '待深圳仓确认'),
        ('warehouse_fulfilled', '深圳仓已发货'),
        ('cost_confirmed', '深圳仓已确认成本'),
        ('admin_confirmed', 'admin已确认'),
        ('pending_payment', '待支付'),
        ('paid', '已支付'),
        ('transferred', '已转其他仓'),
        ('cancelled', '已取消深圳仓履约'),
        ('exception', '异常待审核'),
    ]

    installation = models.ForeignKey(
        ShopifyInstallation, on_delete=models.CASCADE, related_name="orders"
    )
    shopify_order_id = models.BigIntegerField()
    order_number = models.CharField(max_length=255, blank=True, null=True)
    order_name = models.CharField(max_length=255)
    financial_status = models.CharField(max_length=50, blank=True, null=True)
    fulfillment_status = models.CharField(max_length=50, blank=True, null=True)
    
    # Customer information
    customer_name = models.CharField(max_length=255, blank=True, null=True)
    customer_email = models.EmailField(blank=True, null=True)
    
    # Shipping address
    shipping_name = models.CharField(max_length=255, blank=True, null=True)
    shipping_address1 = models.CharField(max_length=255, blank=True, null=True)
    shipping_address2 = models.CharField(max_length=255, blank=True, null=True)
    shipping_city = models.CharField(max_length=255, blank=True, null=True)
    shipping_province = models.CharField(max_length=255, blank=True, null=True)
    shipping_country = models.CharField(max_length=3, blank=True, null=True)  # ISO country code
    shipping_zip = models.CharField(max_length=20, blank=True, null=True)
    shipping_phone = models.CharField(max_length=50, blank=True, null=True)
    
    # Order details
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    order_created_at = models.DateTimeField()
    shopify_note = models.TextField(blank=True, null=True)
    shopify_note_attributes = models.JSONField(default=list, blank=True)
    
    # Location information (normalized)
    original_location_raw = models.CharField(max_length=255, blank=True, null=True)
    current_location_raw = models.CharField(max_length=255, blank=True, null=True)
    original_location = models.CharField(max_length=255, blank=True, null=True)
    current_location = models.CharField(max_length=255, blank=True, null=True)
    is_shenzhen_order = models.BooleanField(default=False)
    
    # Settlement status
    settlement_status = models.CharField(
        max_length=20,
        choices=SETTLEMENT_STATUS_CHOICES,
        default='pending_warehouse'
    )

    # Order-level cost fields
    total_actual_weight_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="订单实际总重量 kg"
    )
    total_volume_weight_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="订单体积重 kg"
    )
    chargeable_weight_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="订单计费重量 kg"
    )
    order_shipping_cost_rmb = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="订单运费 RMB"
    )
    order_handling_fee_rmb = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="订单下单费 RMB"
    )
    total_locked_cost_rmb = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="订单总锁定成本 RMB"
    )
    cost_calculated_at = models.DateTimeField(blank=True, null=True)
    cost_calculation_note = models.TextField(blank=True, null=True)

    # Shenzhen warehouse fields
    tracking_number = models.CharField(max_length=255, blank=True, null=True)
    tracking_company = models.CharField(max_length=255, blank=True, null=True)
    tracking_url = models.URLField(max_length=500, blank=True, null=True)
    fulfilled_at = models.DateTimeField(blank=True, null=True)
    fulfillment_status_raw = models.CharField(max_length=255, blank=True)
    last_order_synced_at = models.DateTimeField(blank=True, null=True)
    warehouse_note = models.TextField(blank=True, null=True)
    
    # Transfer fields (转仓)
    transferred_at = models.DateTimeField(blank=True, null=True, help_text="转仓时间")
    transfer_note = models.TextField(blank=True, null=True, help_text="转仓备注")
    
    # Settlement batch (结算批次)
    settlement_batch = models.ForeignKey(
        'SettlementBatch', on_delete=models.SET_NULL, null=True, blank=True,
        related_name="orders", help_text="所属结算批次"
    )
    
    # Timestamps
    synced_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("installation", "shopify_order_id")
        ordering = ["-order_created_at"]
        indexes = [
            models.Index(fields=["is_shenzhen_order", "settlement_status"], name="shopify_syn_is_shen_60811a_idx"),
            models.Index(fields=["order_created_at"], name="shopify_syn_order_c_d20b1a_idx"),
            models.Index(fields=["current_location"], name="shopify_syn_current_fec5a8_idx"),
        ]

    def __str__(self):
        return f"{self.order_name} ({self.customer_name})"

    @property
    def missing_product_data(self):
        """Returns list of SKUs with missing product data (cost, dimensions)"""
        missing_skus = []
        for item in self.order_items.filter(fulfillment_location="shenzhen"):
            if not item.matched_product:
                continue
            product = item.matched_product
            if (product.product_cost_rmb is None or
                product.weight_kg is None or
                product.length_cm is None or
                product.width_cm is None or
                product.height_cm is None):
                missing_skus.append(
                    item.sku or item.product_title or str(item.shopify_line_item_id)
                )
        return missing_skus


class ShopifyOrderPackage(models.Model):
    order = models.ForeignKey(
        ShopifyOrder, on_delete=models.CASCADE, related_name="packages"
    )
    package_no = models.PositiveIntegerField(default=1)
    tracking_number = models.CharField(max_length=255, blank=True, default="")
    carrier = models.CharField(max_length=100, blank=True, default="")
    country_code = models.CharField(max_length=10, blank=True, default="")
    shipping_cost_rmb = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    ordering_cost_rmb = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "package_no"]
        unique_together = ("order", "package_no")

    def __str__(self):
        return f"{self.order.order_name} Package {self.package_no}"


class ShopifyOrderItem(models.Model):
    order = models.ForeignKey(
        ShopifyOrder, on_delete=models.CASCADE, related_name="order_items"
    )
    package = models.ForeignKey(
        ShopifyOrderPackage,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="items",
    )
    shopify_line_item_id = models.BigIntegerField()
    shopify_product_id = models.BigIntegerField(null=True, blank=True)
    shopify_variant_id = models.BigIntegerField(null=True, blank=True)
    
    # Product information
    sku = models.CharField(max_length=255, blank=True, null=True)
    product_title = models.CharField(max_length=255, blank=True, null=True)
    variant_title = models.CharField(max_length=255, blank=True, null=True)
    
    # Order details
    quantity = models.IntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Fulfillment location
    fulfillment_location = models.CharField(max_length=255, blank=True, null=True)
    fulfilled_quantity = models.IntegerField(null=True, blank=True)
    fulfillment_id = models.BigIntegerField(null=True, blank=True)
    item_fulfilled_at = models.DateTimeField(blank=True, null=True)
    
    # Cost matching
    matched_product = models.ForeignKey(
        'ShopifyProduct', on_delete=models.SET_NULL, null=True, blank=True,
        related_name="order_items"
    )
    
    # Locked costs (don't change with product updates)
    locked_product_cost_rmb = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    locked_shipping_cost_rmb = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    handling_fee_rmb = models.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )
    total_cost_rmb = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    weight_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    length_cm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    width_cm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    volume_weight_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    match_note = models.TextField(blank=True, help_text="匹配备注")
    match_status = models.CharField(
        max_length=50,
        choices=[
            ("matched_by_variant_id", "通过 variant_id 匹配"),
            ("matched_by_sku", "通过 SKU 匹配"),
            ("matched_by_sku_normalized", "通过 SKU 标准化匹配"),
            ("unmatched_missing_variant_and_sku", "未匹配：缺少 variant_id 和 SKU"),
            ("unmatched_variant_not_found", "未匹配：variant_id 未找到"),
            ("unmatched_sku_not_found", "未匹配：SKU 未找到"),
            ("custom_item", "自定义商品"),
        ],
        default="unmatched_missing_variant_and_sku",
        help_text="产品匹配状态",
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("order", "shopify_line_item_id")
        indexes = [
            models.Index(fields=["shopify_variant_id"], name="shopify_syn_shopify_4a6263_idx"),
            models.Index(fields=["sku"], name="shopify_syn_sku_3a1627_idx"),
            models.Index(fields=["fulfillment_location"], name="shopify_syn_fulfill_8b0859_idx"),
        ]

    def __str__(self):
        return f"{self.product_title} - {self.variant_title} (x{self.quantity})"

    def save(self, *args, **kwargs):
        # Auto-fill product cost if empty
        if self.locked_product_cost_rmb is None and self.matched_product and self.matched_product.product_cost_rmb:
            self.locked_product_cost_rmb = self.matched_product.product_cost_rmb
        
        # Item total is still used for single-product / non-package settlement.
        if self.locked_product_cost_rmb is not None:
            self.total_cost_rmb = (
                (self.locked_product_cost_rmb * self.quantity) +
                (self.locked_shipping_cost_rmb or 0) -
                (self.handling_fee_rmb or 0)
            )
        super().save(*args, **kwargs)


class ShopifyProduct(models.Model):
    installation = models.ForeignKey(
        ShopifyInstallation, on_delete=models.CASCADE, related_name="products"
    )
    shopify_product_id = models.BigIntegerField()
    shopify_variant_id = models.BigIntegerField(unique=True)
    product_title = models.CharField(max_length=255)
    variant_title = models.CharField(max_length=255, blank=True)
    sku = models.CharField(max_length=255, blank=True, null=True)
    handle = models.CharField(max_length=255, blank=True)
    vendor = models.CharField(max_length=255, blank=True)
    product_type = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=50, default="active")
    image_url = models.URLField(max_length=500, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    inventory_quantity = models.IntegerField(default=0)
    shopify_product_created_at = models.DateTimeField(null=True, blank=True)
    shopify_product_updated_at = models.DateTimeField(null=True, blank=True)
    shopify_published_at = models.DateTimeField(null=True, blank=True)
    shopify_variant_created_at = models.DateTimeField(null=True, blank=True)
    shopify_variant_updated_at = models.DateTimeField(null=True, blank=True)

    # 人工填写字段（不被同步覆盖）
    is_shenzhen_product = models.BooleanField(default=False)
    product_cost_rmb = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    shipping_cost_rules = models.JSONField(default=dict, blank=True)

    # 尺寸和重量字段（人工填写）
    weight_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="实际重量 kg"
    )
    length_cm = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="长 cm"
    )
    width_cm = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="宽 cm"
    )
    height_cm = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="高 cm"
    )
    volume_weight_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="体积重 kg（自动计算）"
    )
    shipping_note = models.TextField(blank=True, help_text="运费备注")

    # 时间戳
    last_synced_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("installation", "shopify_variant_id")
        ordering = ["-shopify_published_at", "-shopify_product_created_at", "-id"]
        indexes = [
            models.Index(fields=["installation", "sku"], name="shopify_syn_install_92b439_idx"),
            models.Index(fields=["shopify_variant_id"], name="shopify_syn_shopify_7fbdde_idx"),
        ]

    def __str__(self):
        return f"{self.product_title} - {self.variant_title} ({self.sku})"

    def save(self, *args, **kwargs):
        # 自动计算体积重
        if self.length_cm and self.width_cm and self.height_cm:
            self.volume_weight_kg = (self.length_cm * self.width_cm * self.height_cm) / 6000
        super().save(*args, **kwargs)

class ShopifyProductCostHistory(models.Model):
    order = models.ForeignKey(
        ShopifyOrder,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="product_cost_histories",
    )
    order_item = models.ForeignKey(
        ShopifyOrderItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="product_cost_histories",
    )
    product = models.ForeignKey(
        ShopifyProduct,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cost_histories",
    )
    shopify_product_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    shopify_variant_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    sku = models.CharField(max_length=255, blank=True, default="")
    product_title = models.CharField(max_length=500, blank=True, default="")
    old_item_cost_rmb = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_item_cost_rmb = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    old_product_cost_rmb = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_product_cost_rmb = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    overwrite_product_cost = models.BooleanField(default=False)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shopify_product_cost_changes",
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=100, blank=True, default="order_item_inline")
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        label = self.product_title or self.sku or self.shopify_variant_id or "Product cost"
        return f"{label}: {self.old_item_cost_rmb} -> {self.new_item_cost_rmb}"


class FinanceExchangeRate(models.Model):
    base_currency = models.CharField(max_length=3, default="AUD", db_index=True)
    quote_currency = models.CharField(max_length=3, default="CNY", db_index=True)
    rate = models.DecimalField(max_digits=10, decimal_places=4)
    effective_date = models.DateField(default=timezone.localdate, db_index=True)
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_finance_exchange_rates",
    )
    updated_at = models.DateTimeField(auto_now=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-effective_date", "-updated_at"]
        indexes = [
            models.Index(fields=["base_currency", "quote_currency", "is_active"], name="shopify_syn_fx_pair_active_idx"),
        ]

    def save(self, *args, **kwargs):
        self.base_currency = (self.base_currency or "AUD").strip().upper()
        self.quote_currency = (self.quote_currency or "CNY").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"1 {self.base_currency} = {self.rate} {self.quote_currency}"


class ShippingCostRule(models.Model):
    name = models.CharField(max_length=255, help_text="规则名称")
    country_code = models.CharField(max_length=3, help_text="国家代码，例如 AU, US, DE, FR")
    country_name = models.CharField(max_length=255, help_text="国家名称")
    priority = models.IntegerField(default=100, help_text="优先级，数字越小优先")
    min_weight_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    max_weight_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    max_length_cm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    max_width_cm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    max_height_cm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    use_volume_weight = models.BooleanField(default=False, help_text="是否启用体积重")
    volume_divisor = models.DecimalField(max_digits=10, decimal_places=2, default=6000, help_text="体积重除数，默认 6000")
    price_per_kg_rmb = models.DecimalField(max_digits=10, decimal_places=2, help_text="每 kg 运费 RMB")
    base_fee_rmb = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="基础费用 RMB")
    handling_fee_rmb = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="下单费 / 操作费 RMB")
    is_active = models.BooleanField(default=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["country_code", "name"]
        indexes = [
            models.Index(fields=["country_code", "is_active"], name="shopify_syn_country_e13938_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.country_code})"


class ShenzhenCountryShippingDefault(models.Model):
    country_code = models.CharField(max_length=10, unique=True, db_index=True)
    country_name = models.CharField(max_length=100, blank=True, default="")
    default_shipping_cost_rmb = models.DecimalField(max_digits=10, decimal_places=2)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_shenzhen_shipping_defaults",
    )
    updated_at = models.DateTimeField(auto_now=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["country_code"]

    def __str__(self):
        return f"{self.country_code}: {self.default_shipping_cost_rmb} RMB"


class ShenzhenProductCountryShippingDefault(models.Model):
    country_code = models.CharField(max_length=10, db_index=True)
    country_name = models.CharField(max_length=100, blank=True, default="")
    shopify_product_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    shopify_variant_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    sku = models.CharField(max_length=255, blank=True, default="")
    product_title = models.CharField(max_length=500, blank=True, default="")
    variant_title = models.CharField(max_length=255, blank=True, default="")
    matched_product = models.ForeignKey(
        ShopifyProduct,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shipping_defaults",
    )
    default_shipping_cost_rmb = models.DecimalField(max_digits=10, decimal_places=2)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_shenzhen_product_shipping_defaults",
    )
    updated_at = models.DateTimeField(auto_now=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["country_code", "product_title", "variant_title"]
        unique_together = ("country_code", "shopify_variant_id")
        indexes = [
            models.Index(fields=["country_code", "shopify_variant_id"], name="shopify_syn_country_dba550_idx"),
            models.Index(fields=["country_code", "shopify_product_id"], name="shopify_syn_country_9eb8b8_idx"),
        ]

    def __str__(self):
        label = self.variant_title or self.sku or self.shopify_variant_id
        return f"{self.country_code}: {label} - {self.default_shipping_cost_rmb} RMB"


class ShopifySyncState(models.Model):
    task_name = models.CharField(max_length=100, unique=True, db_index=True)
    is_running = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    last_result = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["task_name"]

    def __str__(self):
        return self.task_name


class SettlementBatch(models.Model):
    """
    结算批次模型 - 用于管理订单结算和支付
    """
    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('pending_payment', '待支付'),
        ('paid', '已支付'),
        ('cancelled', '已取消'),
    ]

    batch_no = models.CharField(
        max_length=50, unique=True, help_text="批次号，格式: YYYYMM-001"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft',
        help_text="批次状态"
    )
    total_amount_rmb = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="批次总金额 RMB"
    )
    created_by = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="创建人"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(blank=True, null=True, help_text="支付时间")
    note = models.TextField(blank=True, null=True, help_text="批次备注")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="shopify_syn_status_4d8e10_idx"),
            models.Index(fields=["batch_no"], name="shopify_syn_batch_n_9b6ebd_idx"),
        ]

    def __str__(self):
        return f"{self.batch_no} ({self.get_status_display()})"

    def update_total_amount(self):
        """重新计算批次总金额"""
        total = sum(
            order.total_locked_cost_rmb or 0
            for order in self.orders.all()
        )
        self.total_amount_rmb = total
        self.save(update_fields=['total_amount_rmb'])
