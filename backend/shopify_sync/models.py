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
            models.Index(fields=["is_shenzhen_order", "settlement_status"]),
            models.Index(fields=["order_created_at"]),
            models.Index(fields=["current_location"]),
        ]

    def __str__(self):
        return f"{self.order_name} ({self.customer_name})"

    @property
    def missing_product_data(self):
        """Returns list of SKUs with missing product data (cost, dimensions)"""
        missing_skus = []
        for item in self.order_items.all():
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


class ShopifyOrderItem(models.Model):
    order = models.ForeignKey(
        ShopifyOrder, on_delete=models.CASCADE, related_name="order_items"
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
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("order", "shopify_line_item_id")
        indexes = [
            models.Index(fields=["shopify_variant_id"]),
            models.Index(fields=["sku"]),
            models.Index(fields=["fulfillment_location"]),
        ]

    def __str__(self):
        return f"{self.product_title} - {self.variant_title} (x{self.quantity})"

    def save(self, *args, **kwargs):
        # Auto-fill product cost if empty
        if self.locked_product_cost_rmb is None and self.matched_product and self.matched_product.product_cost_rmb:
            self.locked_product_cost_rmb = self.matched_product.product_cost_rmb
        
        # Calculate total cost when saving
        if self.locked_product_cost_rmb is not None and self.locked_shipping_cost_rmb is not None:
            self.total_cost_rmb = (
                (self.locked_product_cost_rmb * self.quantity) +
                self.locked_shipping_cost_rmb +
                self.handling_fee_rmb
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
    sku = models.CharField(max_length=255, blank=True)
    handle = models.CharField(max_length=255, blank=True)
    vendor = models.CharField(max_length=255, blank=True)
    product_type = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=50, default="active")
    image_url = models.URLField(max_length=500, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    inventory_quantity = models.IntegerField(default=0)

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
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["installation", "sku"]),
            models.Index(fields=["shopify_variant_id"]),
        ]

    def __str__(self):
        return f"{self.product_title} - {self.variant_title} ({self.sku})"

    def save(self, *args, **kwargs):
        # 自动计算体积重
        if self.length_cm and self.width_cm and self.height_cm:
            self.volume_weight_kg = (self.length_cm * self.width_cm * self.height_cm) / 6000
        super().save(*args, **kwargs)

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
            models.Index(fields=["country_code", "is_active"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.country_code})"


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
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["batch_no"]),
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