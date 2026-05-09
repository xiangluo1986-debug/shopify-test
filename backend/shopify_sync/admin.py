import csv
import re
from decimal import Decimal
from urllib.parse import parse_qs, urlencode, urlparse

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.models import Group
from django.core.exceptions import FieldError, ValidationError
from django.db import models
from django.forms.models import BaseInlineFormSet
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    FinanceExchangeRate,
    ShopifyInstallation,
    ShopifyOrder,
    ShopifyOrderPackage,
    ShopifyProduct,
    ShopifyProductCostHistory,
    ShopifyOrderItem,
    ShippingCostRule,
    SettlementBatch,
    ShenzhenCountryShippingDefault,
    ShenzhenProductCountryShippingDefault,
)


SHENZHEN_ITEM_LOCATION = "shenzhen"
ZERO = Decimal("0.00")
SHENZHEN_COST_EDITABLE_STATUSES = {"pending_warehouse", "warehouse_fulfilled"}
FINANCE_LOCKED_STATUSES = {"pending_payment", "payment_submitted", "paid"}
SETTLEMENT_STATUS_ADMIN_LABELS = {
    "cost_confirmed": "深圳仓已确认成本，待 Admin 确认",
    "admin_confirmed": "Admin 已确认",
    "payment_submitted": "已提交支付，待深圳仓确认收款",
}
COUNTRY_NAME_ZH = {
    "AU": "澳大利亚",
    "US": "美国",
    "GB": "英国",
    "UK": "英国",
    "CA": "加拿大",
    "NZ": "新西兰",
    "DE": "德国",
    "FR": "法国",
    "IT": "意大利",
    "ES": "西班牙",
    "NL": "荷兰",
    "BE": "比利时",
    "SE": "瑞典",
    "NO": "挪威",
    "DK": "丹麦",
    "FI": "芬兰",
    "CH": "瑞士",
    "AT": "奥地利",
    "IE": "爱尔兰",
    "PT": "葡萄牙",
    "PL": "波兰",
    "CZ": "捷克",
    "JP": "日本",
    "KR": "韩国",
    "SG": "新加坡",
    "MY": "马来西亚",
    "TH": "泰国",
    "PH": "菲律宾",
    "ID": "印度尼西亚",
    "VN": "越南",
    "CN": "中国",
    "HK": "中国香港",
    "TW": "中国台湾",
    "MO": "中国澳门",
    "BR": "巴西",
    "MX": "墨西哥",
    "AE": "阿联酋",
    "SA": "沙特阿拉伯",
    "IN": "印度",
    "ZA": "南非",
}
PAYMENT_FEE_RATE = Decimal("0.02")
DEFAULT_SMALL_LINK_AUD_COST = Decimal("1.60")
PRODUCT_FALLBACK_FIELDS = {
    "locked_product_cost_rmb": "product_cost_rmb",
    "weight_kg": "weight_kg",
    "length_cm": "length_cm",
    "width_cm": "width_cm",
    "height_cm": "height_cm",
    "volume_weight_kg": "volume_weight_kg",
}
PRODUCT_FIELDS_AUTO_SYNC_TO_PRODUCT = {
    item_field: product_field
    for item_field, product_field in PRODUCT_FALLBACK_FIELDS.items()
    if item_field != "locked_product_cost_rmb"
}


def parse_ordering_note(note_text):
    note = (note_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not note:
        return "订单 Note: -\n识别：无 Shopify order note，请人工填写拍单成本 RMB。"

    first_line, has_extra_notes = parse_ordering_note_first_line(note)
    display_note = first_line if len(first_line) <= 300 else f"{first_line[:300]}..."
    if not re.match(r"^PL(?:\s|$)", first_line, flags=re.IGNORECASE):
        return f"订单 Note: {display_note}\n识别：未识别到 PL 拍单信息，请人工确认拍单成本 RMB。"

    pl_payload = re.sub(r"^PL\b", "", first_line, flags=re.IGNORECASE).strip()
    lower_payload = pl_payload.lower()
    numbers = re.findall(r"\d+(?:\.\d+)?", pl_payload)
    small_match = re.search(r"\bsmall\b\s*x?\s*(\d+)?", lower_payload)
    big_match = re.search(r"\bbig\b\s*x?\s*(\d+)?", lower_payload)
    generic_x_match = re.search(r"\bx\s*(\d+)\b", lower_payload)
    small_count = None
    big_count = None

    if small_match:
        small_count = int(next((value for value in small_match.groups() if value), "1"))
    if big_match:
        big_count = int(next((value for value in big_match.groups() if value), "1"))
    if generic_x_match and not small_count and not big_count:
        small_count = int(generic_x_match.group(1))

    if not pl_payload:
        return (
            f"订单 Note 首行: {display_note}\n"
            f"识别：PL 后没有金额，按规则推断为拍了 1 个小金额链接（1 美金链接），利润统计暂按 A${DEFAULT_SMALL_LINK_AUD_COST} 扣除。\n"
            "提示：仅作参考，不自动写入拍单成本 RMB。"
        )

    aud_amount = Decimal(numbers[-1]) if numbers else None

    if len(numbers) >= 2 and numbers[0].isdigit() and not small_count and not big_count:
        small_count = int(numbers[0])

    if small_count or big_count:
        detail_parts = []
        if small_count:
            detail_parts.append(f"可能拍了 {small_count} 个小金额链接")
        if big_count:
            detail_parts.append(f"可能拍了 {big_count} 个大金额链接")
        if aud_amount:
            detail_parts.append(f"对应 A${aud_amount}")
        extra_note = "\n后续换行备注已忽略。" if has_extra_notes else ""
        return (
            f"订单 Note 首行: {display_note}\n"
            f"识别：{'，'.join(detail_parts)}。{extra_note}\n"
            "提示：请人工确认拍单成本 RMB；系统不会自动换算或写入。"
        )

    if aud_amount is not None:
        candidates = []
        min_aud_per_usd = Decimal("1.20")
        max_aud_per_usd = Decimal("1.90")
        target_aud_per_usd = Decimal("1.55")
        max_total_usd = int(aud_amount / min_aud_per_usd) + 3
        max_big_count = max(1, max_total_usd // 10 + 2)
        max_small_count = max(1, max_total_usd + 2)

        for candidate_big_count in range(max_big_count + 1):
            for candidate_small_count in range(max_small_count + 1):
                total_usd = candidate_big_count * 10 + candidate_small_count
                if total_usd <= 0:
                    continue
                implied_rate = aud_amount / Decimal(total_usd)
                if not (min_aud_per_usd <= implied_rate <= max_aud_per_usd):
                    continue
                link_count = candidate_big_count + candidate_small_count
                score = (
                    abs(implied_rate - target_aud_per_usd)
                    + Decimal(link_count) * Decimal("0.04")
                    - Decimal(candidate_big_count) * Decimal("0.02")
                )
                candidates.append((score, link_count, -candidate_big_count, candidate_small_count, candidate_big_count, implied_rate))

        if candidates:
            _, _, _, inferred_small, inferred_big, implied_rate = sorted(candidates)[0]
            inferred_parts = []
            if inferred_big:
                inferred_parts.append(f"{inferred_big} 个大金额链接（10 美金链接）")
            if inferred_small:
                inferred_parts.append(f"{inferred_small} 个小金额链接（1 美金链接）")
            extra_note = "\n后续换行备注已忽略。" if has_extra_notes else ""
            return (
                f"订单 Note 首行: {display_note}\n"
                f"识别：PL 后填写 A${aud_amount}。按常见汇率区间粗略推断，可能拍了 {' + '.join(inferred_parts)}。"
                f"\n估算汇率：A${implied_rate.quantize(Decimal('0.01'))}/USD。{extra_note}\n"
                "提示：仅作悬浮参考，不自动换算 RMB，也不自动写入拍单成本。"
            )

        extra_note = "\n后续换行备注已忽略。" if has_extra_notes else ""
        return (
            f"订单 Note 首行: {display_note}\n"
            f"识别：PL 后填写 A${aud_amount}，但金额不在常见 1/10 美金链接汇率推断范围内。{extra_note}\n"
            "提示：请人工判断是小金额还是大金额链接；系统不会自动写入拍单成本。"
        )

    extra_note = "\n后续换行备注已忽略。" if has_extra_notes else ""
    return (
        f"订单 Note 首行: {display_note}\n"
        f"识别：PL 后内容不是明确澳币金额，无法可靠推断链接数量。{extra_note}\n"
        "提示：请人工确认拍单成本 RMB。"
    )


def country_label_with_zh(country_code):
    code = (country_code or "").strip().upper()
    if not code:
        return "-"
    return f"{code} / {COUNTRY_NAME_ZH.get(code, '未配置中文名')}"


def settlement_status_admin_label(status):
    labels = dict(ShopifyOrder.SETTLEMENT_STATUS_CHOICES)
    labels.update(SETTLEMENT_STATUS_ADMIN_LABELS)
    return labels.get(status, status or "-")


def parse_ordering_note_first_line(note_text):
    note = (note_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not note:
        return "", False
    first_line = note.split("\n", 1)[0].strip()
    return first_line, "\n" in note


def ordering_note_aud_cost(note_text):
    first_line, _ = parse_ordering_note_first_line(note_text)
    if not re.match(r"^PL(?:\s|$)", first_line, flags=re.IGNORECASE):
        return None
    pl_payload = re.sub(r"^PL\b", "", first_line, flags=re.IGNORECASE).strip()
    numbers = re.findall(r"\d+(?:\.\d+)?", pl_payload)
    if not numbers:
        return money(DEFAULT_SMALL_LINK_AUD_COST)
    return money(Decimal(numbers[-1]))


def money(value):
    return Decimal(value or 0).quantize(Decimal("0.01"))


def get_aud_to_rmb_rate():
    exchange_rate = FinanceExchangeRate.objects.filter(
        base_currency="AUD",
        quote_currency="CNY",
        is_active=True,
    ).order_by("-effective_date", "-updated_at").first()
    if not exchange_rate:
        return {
            "rate": None,
            "date": "",
            "error": "请先在 Finance exchange rates 中设置有效的 AUD/CNY 汇率。",
        }
    return {
        "rate": exchange_rate.rate,
        "date": exchange_rate.effective_date,
        "error": "",
    }


def order_profit_totals(order):
    items = list(shenzhen_order_items(order))
    shenzhen_items_revenue_aud = sum((money(item.price) * item.quantity for item in items), ZERO)
    all_items_revenue_aud = sum(
        (money(item.price) * item.quantity for item in order.order_items.all()),
        ZERO,
    )
    order_total_aud = money(order.total_price)
    order_level_extra_aud = money(order_total_aud - all_items_revenue_aud)
    shenzhen_share = ZERO
    if all_items_revenue_aud > 0:
        shenzhen_share = shenzhen_items_revenue_aud / all_items_revenue_aud
    shenzhen_order_extra_aud = money(order_level_extra_aud * shenzhen_share)
    revenue_aud = money(shenzhen_items_revenue_aud + shenzhen_order_extra_aud)
    net_revenue_aud = money(revenue_aud * (Decimal("1.00") - PAYMENT_FEE_RATE))
    ordering_note_cost_aud = ordering_note_aud_cost(order.shopify_note)
    if ordering_note_cost_aud is None:
        ordering_note_cost_aud = ZERO
    cost_rmb = money(order_package_cost_totals(order)["total_cost"])
    rate_info = get_aud_to_rmb_rate()
    rate = rate_info.get("rate")
    if not rate:
        return {
            "items_count": len(items),
            "shenzhen_items_revenue_aud": money(shenzhen_items_revenue_aud),
            "order_level_extra_aud": order_level_extra_aud,
            "shenzhen_order_extra_aud": shenzhen_order_extra_aud,
            "revenue_aud": money(revenue_aud),
            "net_revenue_aud": net_revenue_aud,
            "ordering_note_cost_aud": ordering_note_cost_aud,
            "cost_rmb": cost_rmb,
            "cost_aud": None,
            "profit_aud": None,
            "profit_rate": None,
            "rate": None,
            "rate_date": "",
            "rate_error": rate_info.get("error", ""),
        }

    cost_aud = money(cost_rmb / rate)
    profit_aud = money(net_revenue_aud - ordering_note_cost_aud - cost_aud)
    profit_rate = None
    if net_revenue_aud:
        profit_rate = (profit_aud / net_revenue_aud * Decimal("100")).quantize(Decimal("0.01"))

    return {
        "items_count": len(items),
        "shenzhen_items_revenue_aud": money(shenzhen_items_revenue_aud),
        "order_level_extra_aud": order_level_extra_aud,
        "shenzhen_order_extra_aud": shenzhen_order_extra_aud,
        "revenue_aud": money(revenue_aud),
        "net_revenue_aud": net_revenue_aud,
        "ordering_note_cost_aud": ordering_note_cost_aud,
        "cost_rmb": cost_rmb,
        "cost_aud": cost_aud,
        "profit_aud": profit_aud,
        "profit_rate": profit_rate,
        "rate": rate,
        "rate_date": rate_info.get("date", ""),
        "rate_error": "",
    }


def shenzhen_order_items(order):
    return order.order_items.filter(fulfillment_location=SHENZHEN_ITEM_LOCATION)


def is_order_locked_for_shenzhen_cost_edit(order):
    if not order:
        return False
    return bool(
        order.settlement_batch_id
        or order.settlement_status in FINANCE_LOCKED_STATUSES
        or order.settlement_status not in SHENZHEN_COST_EDITABLE_STATUSES
    )


def decimal_or_zero(value):
    return value if value is not None else ZERO


def item_product_cost_total(item):
    return decimal_or_zero(item.locked_product_cost_rmb) * item.quantity


def item_full_cost_total(item):
    return (
        item_product_cost_total(item)
        + decimal_or_zero(item.locked_shipping_cost_rmb)
        - decimal_or_zero(item.handling_fee_rmb)
    )


def shenzhen_item_cost_totals(items):
    items = list(items)
    return {
        "items_count": len(items),
        "product_cost": sum((item_product_cost_total(item) for item in items), ZERO),
    }


def package_cost_totals(package):
    if not package or not package.pk:
        shipping_cost = decimal_or_zero(getattr(package, "shipping_cost_rmb", None))
        ordering_cost = decimal_or_zero(getattr(package, "ordering_cost_rmb", None))
        return {
            "items_count": 0,
            "product_cost": ZERO,
            "shipping_cost": shipping_cost,
            "ordering_cost": ordering_cost,
            "total_cost": shipping_cost - ordering_cost,
        }
    item_totals = shenzhen_item_cost_totals(
        package.items.filter(fulfillment_location=SHENZHEN_ITEM_LOCATION)
    )
    shipping_cost = decimal_or_zero(package.shipping_cost_rmb)
    ordering_cost = decimal_or_zero(package.ordering_cost_rmb)
    item_totals.update({
        "shipping_cost": shipping_cost,
        "ordering_cost": ordering_cost,
        "total_cost": item_totals["product_cost"] + shipping_cost - ordering_cost,
    })
    return item_totals


def order_package_cost_totals(order):
    items = list(shenzhen_order_items(order).select_related("package"))
    item_totals = shenzhen_item_cost_totals(items)
    package_ids = {item.package_id for item in items if item.package_id}
    packages = list(order.packages.filter(id__in=package_ids))
    unpackaged_items = [item for item in items if not item.package_id]
    shipping_cost = (
        sum((decimal_or_zero(package.shipping_cost_rmb) for package in packages), ZERO)
        + sum((decimal_or_zero(item.locked_shipping_cost_rmb) for item in unpackaged_items), ZERO)
    )
    ordering_cost = (
        sum((decimal_or_zero(package.ordering_cost_rmb) for package in packages), ZERO)
        + sum((decimal_or_zero(item.handling_fee_rmb) for item in unpackaged_items), ZERO)
    )
    package_total = sum((package_cost_totals(package)["total_cost"] for package in packages), ZERO)
    unpackaged_total = sum((item_full_cost_total(item) for item in unpackaged_items), ZERO)
    item_totals.update({
        "shipping_cost": shipping_cost,
        "ordering_cost": ordering_cost,
        "total_cost": package_total + unpackaged_total,
    })
    return item_totals


def shenzhen_item_costs_completed(order):
    items = list(shenzhen_order_items(order))
    if not items:
        return False
    for item in items:
        if item.locked_product_cost_rmb is None or item.locked_product_cost_rmb <= 0:
            return False
        if item.package_id:
            if item.package.shipping_cost_rmb is None or item.package.shipping_cost_rmb <= 0:
                return False
            if item.package.ordering_cost_rmb is None:
                return False
        else:
            if item.locked_shipping_cost_rmb is None or item.locked_shipping_cost_rmb <= 0:
                return False
            if item.handling_fee_rmb is None:
                return False
    return True


def positive_decimal(value):
    return value is not None and value > 0


def sync_order_item_product_fields_to_product(item):
    product = item.matched_product
    if not product:
        return False

    updates = {}
    for item_field, product_field in PRODUCT_FIELDS_AUTO_SYNC_TO_PRODUCT.items():
        value = getattr(item, item_field)
        if positive_decimal(value):
            updates[product_field] = value

    if not updates:
        return False
    if "volume_weight_kg" in updates:
        ShopifyProduct.objects.filter(pk=product.pk).update(**updates)
        return True

    for field, value in updates.items():
        setattr(product, field, value)
    update_fields = list(updates.keys())
    if all(positive_decimal(getattr(product, field)) for field in ("length_cm", "width_cm", "height_cm")):
        update_fields.append("volume_weight_kg")
    product.save(update_fields=update_fields)
    return True


def backfill_order_item_from_matched_product(item, save=False):
    if item.fulfillment_location != SHENZHEN_ITEM_LOCATION or not item.matched_product:
        return 0

    changed_fields = []
    for item_field, product_field in PRODUCT_FALLBACK_FIELDS.items():
        current_value = getattr(item, item_field)
        product_value = getattr(item.matched_product, product_field)
        if not positive_decimal(current_value) and positive_decimal(product_value):
            setattr(item, item_field, product_value)
            changed_fields.append(item_field)

    if save and changed_fields:
        item.save(update_fields=changed_fields)
    return len(changed_fields)


def decimal_values_equal(left, right):
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return Decimal(left) == Decimal(right)


def record_order_item_product_cost_history(
    item,
    old_item_cost,
    overwrite_requested,
    user,
    source="order_item_inline",
    note_override=None,
):
    new_item_cost = item.locked_product_cost_rmb
    if decimal_values_equal(old_item_cost, new_item_cost):
        return False, False, False

    product = item.matched_product
    old_product_cost = product.product_cost_rmb if product else None
    new_product_cost = old_product_cost
    overwrite_applied = False
    overwrite_skipped = False
    note = note_override or "Temporary item cost change; product default cost unchanged."

    if overwrite_requested:
        if product and positive_decimal(new_item_cost):
            product.product_cost_rmb = new_item_cost
            product.updated_at = timezone.now()
            product.save(update_fields=["product_cost_rmb", "updated_at"])
            new_product_cost = new_item_cost
            overwrite_applied = True
            note = note_override or "Product default cost overwritten from order item inline."
        else:
            overwrite_skipped = True
            if not product:
                note = note_override or "No matched product; overwrite skipped."
            else:
                note = note_override or "New item cost is empty or non-positive; overwrite skipped."

    ShopifyProductCostHistory.objects.create(
        order=item.order,
        order_item=item,
        product=product,
        shopify_product_id=item.shopify_product_id,
        shopify_variant_id=item.shopify_variant_id,
        sku=item.sku or "",
        product_title=item.product_title or "",
        old_item_cost_rmb=old_item_cost,
        new_item_cost_rmb=new_item_cost,
        old_product_cost_rmb=old_product_cost,
        new_product_cost_rmb=new_product_cost,
        overwrite_product_cost=overwrite_applied,
        changed_by=user if getattr(user, "is_authenticated", False) else None,
        source=source,
        note=note,
    )
    return True, overwrite_applied, overwrite_skipped


def can_apply_country_shipping_default(order):
    if not (order.is_shenzhen_order or order.current_location == "shenzhen"):
        return False
    if not order.shipping_country:
        return False
    if order.order_shipping_cost_rmb and order.order_shipping_cost_rmb > 0:
        return False
    if order.settlement_batch_id:
        return False
    return order.settlement_status not in {"pending_payment", "payment_submitted", "paid"}


def apply_country_shipping_default(order):
    if not can_apply_country_shipping_default(order):
        return False
    shipping_default = ShenzhenCountryShippingDefault.objects.filter(
        country_code__iexact=order.shipping_country
    ).first()
    if not shipping_default:
        return False
    order.order_shipping_cost_rmb = shipping_default.default_shipping_cost_rmb
    order.cost_calculation_note = (
        f"已自动带出 {order.shipping_country} 的深圳仓默认运费 "
        f"{shipping_default.default_shipping_cost_rmb} RMB。"
    )
    return True


class ShopifyOrderItemInlineForm(forms.ModelForm):
    update_product_default_cost = forms.BooleanField(
        label="更新为产品默认成本",
        required=False,
        help_text="默认只修改当前订单商品行；勾选后才会覆盖 ShopifyProduct.product_cost_rmb。",
    )

    class Meta:
        model = ShopifyOrderItem
        fields = "__all__"


class ShopifyOrderItemInlineFormSet(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            return

        for form in self.forms:
            item = form.instance
            if not getattr(item, "pk", None):
                continue
            backfill_order_item_from_matched_product(item, save=False)
            for field in PRODUCT_FALLBACK_FIELDS:
                if field not in form.fields:
                    continue
                value = getattr(item, field, None)
                if positive_decimal(value):
                    form.initial[field] = value
                    form.fields[field].initial = value

    def clean(self):
        super().clean()
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if self.can_delete and self._should_delete_form(form):
                continue
            if not form.cleaned_data:
                continue

            item = form.instance
            if item.fulfillment_location != SHENZHEN_ITEM_LOCATION:
                continue

            product_cost = form.cleaned_data.get("locked_product_cost_rmb")
            shipping_cost = form.cleaned_data.get("locked_shipping_cost_rmb")
            ordering_cost = form.cleaned_data.get("handling_fee_rmb")

            if product_cost is None or product_cost <= 0:
                form.add_error(
                    "locked_product_cost_rmb",
                    ValidationError("产品成本 RMB 为必填，且必须大于 0"),
                )
            if shipping_cost is None or shipping_cost <= 0:
                form.add_error(
                    "locked_shipping_cost_rmb",
                    ValidationError("运费 RMB 为必填，且必须大于 0"),
                )
            if ordering_cost is None:
                form.add_error(
                    "handling_fee_rmb",
                    ValidationError("拍单成本 RMB 为必填，可填写 0.00"),
                )

    def clean(self):
        super().clean()
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if self.can_delete and self._should_delete_form(form):
                continue
            if not form.cleaned_data:
                continue

            item = form.instance
            if item.fulfillment_location != SHENZHEN_ITEM_LOCATION:
                continue

            product_cost = form.cleaned_data.get("locked_product_cost_rmb")
            shipping_cost = form.cleaned_data.get("locked_shipping_cost_rmb")
            ordering_cost = form.cleaned_data.get("handling_fee_rmb")
            package = form.cleaned_data.get("package") or getattr(item, "package", None)
            has_package_shipping = bool(
                package and package.shipping_cost_rmb and package.shipping_cost_rmb > 0
            )
            has_package_ordering = bool(
                package and package.ordering_cost_rmb is not None
            )

            if product_cost is None or product_cost <= 0:
                form.add_error(
                    "locked_product_cost_rmb",
                    ValidationError("产品成本 RMB 为必填，且必须大于 0"),
                )
            if not has_package_shipping and (shipping_cost is None or shipping_cost <= 0):
                form.add_error(
                    "locked_shipping_cost_rmb",
                    ValidationError("运费 RMB 为必填，且必须大于 0。如已选择包裹并填写包裹运费，可先保存后执行包裹分摊。"),
                )
            if not has_package_ordering and ordering_cost is None:
                form.add_error(
                    "handling_fee_rmb",
                    ValidationError("拍单成本 RMB 为必填，可填写 0.00。如已选择包裹并填写包裹拍单成本，可先保存后执行包裹分摊。"),
                )

    def clean(self):
        super().clean()
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if self.can_delete and self._should_delete_form(form):
                continue
            if not form.cleaned_data:
                continue

            item = form.instance
            if item.fulfillment_location != SHENZHEN_ITEM_LOCATION:
                continue

            product_cost = form.cleaned_data.get("locked_product_cost_rmb")
            if product_cost is None or product_cost <= 0:
                form.add_error(
                    "locked_product_cost_rmb",
                    ValidationError("产品成本 RMB 为必填，且必须大于 0"),
                )

    def clean(self):
        # Cost completeness is enforced by settlement actions, not by ordinary order saves.
        super().clean()


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
        if request is None:
            return False
        return self.user_role(request) == "shenzhen_warehouse"

    def is_finance_user(self, request):
        if request is None:
            return False
        return self.user_role(request) == "finance_admin"

    def is_super_admin(self, request):
        if request is None:
            return False
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


class SettlementStatusCountFilter(admin.SimpleListFilter):
    title = "settlement status"
    parameter_name = "settlement_status"

    def _base_queryset_for_counts(self, request, model_admin):
        queryset = model_admin.get_queryset(request)
        search_term = request.GET.get("q", "")
        if search_term:
            queryset, _ = model_admin.get_search_results(request, queryset, search_term)

        skip_params = {
            self.parameter_name,
            f"{self.parameter_name}__exact",
            "p",
            "o",
            "q",
            "e",
            "is_facets",
            "_changelist_filters",
        }
        for key, values in request.GET.lists():
            if key in skip_params:
                continue
            values = [value for value in values if value != ""]
            if not values:
                continue
            try:
                queryset = queryset.filter(**{key: values[-1]})
            except (FieldError, ValueError):
                continue
        return queryset

    def lookups(self, request, model_admin):
        queryset = self._base_queryset_for_counts(request, model_admin)
        counts = {
            row["settlement_status"]: row["count"]
            for row in queryset.values("settlement_status").annotate(count=models.Count("id"))
        }
        return [
            (status, f"{settlement_status_admin_label(status)} ({counts.get(status, 0)})")
            for status, _label in ShopifyOrder.SETTLEMENT_STATUS_CHOICES
            if status != "admin_confirmed"
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(settlement_status=self.value())
        return queryset


class ShopifyOrderPackageInline(admin.TabularInline):
    model = ShopifyOrderPackage
    extra = 0
    verbose_name = "包裹"
    verbose_name_plural = (
        "Shopify Order Packages - 操作说明："
        "如果一个订单拆成多个包裹，请先在这里新增包裹，填写包裹编号、包裹运费 RMB、包裹拍单成本 RMB 并保存；"
        "保存后再到下方商品行的 package 下拉框选择对应包裹。"
        "有 package 的商品行按包裹运费/拍单成本结算；没有 package 的商品行继续使用商品行自己的运费/拍单成本。"
    )
    fields = (
        "package_no",
        "shipping_cost_rmb",
        "ordering_cost_rmb",
        "package_items_count",
        "package_product_cost_total_rmb",
        "package_current_total_cost_rmb",
        "note",
    )
    readonly_fields = (
        "package_items_count",
        "package_product_cost_total_rmb",
        "package_current_total_cost_rmb",
    )

    def _shenzhen_items(self, obj):
        if not obj or not obj.pk:
            return []
        return list(obj.items.filter(fulfillment_location=SHENZHEN_ITEM_LOCATION))

    def _package_totals(self, obj):
        return package_cost_totals(obj)

    def package_items_count(self, obj):
        return self._package_totals(obj)["items_count"]
    package_items_count.short_description = "深圳仓商品行"

    def package_product_cost_total_rmb(self, obj):
        return self._package_totals(obj)["product_cost"]
    package_product_cost_total_rmb.short_description = "产品成本合计 RMB"

    def package_current_total_cost_rmb(self, obj):
        return self._package_totals(obj)["total_cost"]
    package_current_total_cost_rmb.short_description = "当前总成本 RMB"

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if not formfield:
            return formfield
        labels = {
            "shipping_cost_rmb": "包裹运费 RMB",
            "ordering_cost_rmb": "包裹拍单成本 RMB",
        }
        if db_field.name in labels:
            formfield.label = labels[db_field.name]
        widths = {
            "package_no": "80px",
            "shipping_cost_rmb": "100px",
            "ordering_cost_rmb": "100px",
        }
        if db_field.name in widths:
            formfield.widget.attrs["style"] = f"width: {widths[db_field.name]};"
        return formfield

    def _can_edit_order_packages(self, request, obj=None):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        groups = set(request.user.groups.values_list("name", flat=True))
        if not (groups & {"Shenzhen Warehouse", "Finance", "Admin"}):
            return False
        if obj is None:
            return True
        return obj.is_shenzhen_order or obj.current_location == SHENZHEN_ITEM_LOCATION

    def _is_shenzhen_user(self, request):
        return request.user.is_authenticated and request.user.groups.filter(name="Shenzhen Warehouse").exists()

    def get_readonly_fields(self, request, obj=None):
        readonly = list(self.readonly_fields)
        if self._is_shenzhen_user(request) and is_order_locked_for_shenzhen_cost_edit(obj):
            readonly.extend([
                "package_no",
                "shipping_cost_rmb",
                "ordering_cost_rmb",
                "note",
            ])
        return tuple(dict.fromkeys(readonly))

    def has_view_permission(self, request, obj=None):
        return self._can_edit_order_packages(request, obj)

    def has_add_permission(self, request, obj=None):
        if self._is_shenzhen_user(request) and is_order_locked_for_shenzhen_cost_edit(obj):
            return False
        return self._can_edit_order_packages(request, obj)

    def has_change_permission(self, request, obj=None):
        return self._can_edit_order_packages(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False


class ShopifyOrderItemInline(admin.TabularInline):
    model = ShopifyOrderItem
    form = ShopifyOrderItemInlineForm
    formset = ShopifyOrderItemInlineFormSet
    extra = 0
    fields = (
        "sku",
        "product_title",
        "variant_title",
        "quantity",
        "shopify_product_id",
        "shopify_variant_id",
        "matched_product",
        "product_match_status",
        "product_image_preview",
        "edit_product_link",
        "package",
        "locked_product_cost_rmb",
        "update_product_default_cost",
        "locked_shipping_cost_rmb",
        "handling_fee_rmb",
        "ordering_note_hover",
        "total_cost_rmb",
        "weight_kg",
        "length_cm",
        "width_cm",
        "height_cm",
        "volume_weight_kg",
        "fallback_product_display",
        "product_cost_rmb_from_product",
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
        "product_image_preview",
        "edit_product_link",
        "product_cost_rmb_from_product",
        "ordering_note_hover",
    )
    show_change_link = False

    def get_queryset(self, request):
        return super().get_queryset(request).filter(
            fulfillment_location=SHENZHEN_ITEM_LOCATION
        ).select_related("matched_product")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "package":
            object_id = getattr(request.resolver_match, "kwargs", {}).get("object_id")
            if object_id:
                kwargs["queryset"] = ShopifyOrderPackage.objects.filter(order_id=object_id)
            else:
                kwargs["queryset"] = ShopifyOrderPackage.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if not formfield:
            return formfield

        required_cost_fields = {
            "locked_product_cost_rmb": "产品成本 RMB *",
            "locked_shipping_cost_rmb": "商品行运费 RMB（历史）",
            "handling_fee_rmb": "商品行拍单成本 RMB（历史）",
        }
        compact_fields = {
            "locked_product_cost_rmb": "100px",
            "locked_shipping_cost_rmb": "100px",
            "handling_fee_rmb": "100px",
            "weight_kg": "90px",
            "length_cm": "90px",
            "width_cm": "90px",
            "height_cm": "90px",
            "volume_weight_kg": "90px",
        }
        if db_field.name in required_cost_fields:
            formfield.label = required_cost_fields[db_field.name]
            formfield.required = False
        if db_field.name in compact_fields:
            formfield.widget.attrs["style"] = f"width: {compact_fields[db_field.name]};"
        if db_field.name == "handling_fee_rmb":
            object_id = getattr(request.resolver_match, "kwargs", {}).get("object_id")
            order_note = None
            if object_id:
                order_note = ShopifyOrder.objects.filter(pk=object_id).values_list("shopify_note", flat=True).first()
            formfield.widget.attrs["title"] = parse_ordering_note(order_note)
        return formfield

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

    def ordering_note_hover(self, obj):
        order = getattr(obj, "order", None)
        if not order:
            return "-"
        tooltip = parse_ordering_note(order.shopify_note)
        return format_html(
            '<style>'
            '.shopify-ordering-note-hover:hover .shopify-ordering-note-popover {{ display:block !important; }}'
            '</style>'
            '<span class="shopify-ordering-note-hover" style="position:relative;display:inline-block;">'
            '<span style="cursor:help;text-decoration:underline;color:#0c66e4;font-weight:600;">查看拍单提示</span>'
            '<span class="shopify-ordering-note-popover" '
            'style="display:none;position:absolute;z-index:9999;left:0;top:1.7em;'
            'width:360px;max-width:60vw;padding:10px 12px;background:#111827;color:#fff;'
            'border-radius:6px;box-shadow:0 8px 24px rgba(15,23,42,.25);'
            'white-space:pre-line;line-height:1.5;text-align:left;">{}</span>'
            '</span>',
            tooltip,
        )
    ordering_note_hover.short_description = "拍单提示"

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

    def product_image_preview(self, obj):
        product = obj.matched_product
        if not product and obj.shopify_variant_id:
            product = ShopifyProduct.objects.filter(
                installation=obj.order.installation,
                shopify_variant_id=obj.shopify_variant_id,
            ).first()
        if not product and obj.shopify_product_id:
            product = ShopifyProduct.objects.filter(
                installation=obj.order.installation,
                shopify_product_id=obj.shopify_product_id,
            ).first()

        if not product or not product.image_url:
            return "无图片"

        title = product.product_title or obj.product_title or ""
        variant = product.variant_title or obj.variant_title or ""
        label = " - ".join(part for part in (title, variant) if part)
        return format_html(
            '<style>'
            '.shopify-product-thumb-hover:hover .shopify-product-thumb-popover {{ display:block !important; }}'
            '</style>'
            '<span class="shopify-product-thumb-hover" style="position:relative;display:inline-block;cursor:zoom-in;">'
            '<span style="text-decoration:underline;">查看图片</span>'
            '<span class="shopify-product-thumb-popover" '
            'style="display:none;position:absolute;z-index:9999;left:0;bottom:1.6em;'
            'padding:8px;background:#fff;border:1px solid #ccc;box-shadow:0 4px 12px rgba(0,0,0,.2);'
            'width:240px;text-align:center;">'
            '<img src="{}" alt="{}" style="max-width:220px;max-height:220px;display:block;margin:0 auto 6px;">'
            '<span style="font-size:12px;color:#333;">{}</span>'
            '</span>'
            '</span>',
            product.image_url,
            label,
            label or "Product image",
        )
    product_image_preview.short_description = "产品图"

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
                ]
            )
            if is_order_locked_for_shenzhen_cost_edit(obj):
                readonly.extend(
                    [
                        "package",
                        "locked_product_cost_rmb",
                        "locked_shipping_cost_rmb",
                        "handling_fee_rmb",
                    ]
                )
        return tuple(dict.fromkeys(readonly))


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
    inlines = [ShopifyOrderPackageInline, ShopifyOrderItemInline]
    list_per_page = 25
    list_max_show_all = 25
    actions = [
        "recalculate_order_shipping_cost",
        "allocate_package_costs",
        "copy_product_cost_to_items",
        "backfill_items_from_matched_products",
        "add_to_settlement_batch",
        "save_order_item_shipping_as_product_country_default",
        "mark_cost_confirmed",
        "withdraw_cost_confirmation",
        "mark_pending_payment",
        "submit_payment",
        "mark_paid",
    ]
    list_display = (
        "order_name",
        "customer_name",
        "shipping_country",
        "original_location",
        "current_location",
        "settlement_status_display",
        "transferred_at",
        "items_count",
        "settlement_total_cost_display",
        "profit_aud_display",
        "is_cost_completed",
        "missing_product_data",
        "order_created_at",
    )
    readonly_fields = (
        "sticky_order_summary",
        "review_workflow_actions",
        "synced_at",
        "updated_at",
        "total_actual_weight_kg",
        "total_volume_weight_kg",
        "chargeable_weight_kg",
        "order_shipping_cost_rmb",
        "order_handling_fee_rmb",
        "total_locked_cost_rmb",
        "settlement_status_display",
        "shenzhen_items_total_cost_summary",
        "profit_summary_for_finance",
        "tracking_info_summary",
        "shopify_note_display",
        "cost_calculated_at",
        "transferred_at",
    )
    search_fields = ("order_name", "order_number", "customer_name", "customer_email")
    list_filter = (
        SettlementStatusCountFilter,
        "is_shenzhen_order",
        "current_location",
        "shipping_country",
        "order_created_at",
    )
    list_editable = ()
    fieldsets = (
        (
            "当前订单摘要",
            {
                "fields": ("sticky_order_summary",),
                "classes": ("shopify-sticky-order-summary",),
            },
        ),
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
                    "shopify_note_display",
                )
            },
        ),
        (
            "履约与成本",
            {
                "fields": (
                    "current_location",
                    "is_shenzhen_order",
                    "settlement_status_display",
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
                    "shenzhen_items_total_cost_summary",
                    "profit_summary_for_finance",
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
        (
            "审核操作",
            {"fields": ("review_workflow_actions",)},
        ),
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
                "settlement_status_display",
                "transferred_at",
                "items_count",
                "settlement_total_cost_display",
                "is_cost_completed",
                "tracking_number",
                "order_created_at",
            )
        return super().get_list_display(request)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/warehouse-review/",
                self.admin_site.admin_view(self.warehouse_review_order),
                name="shopify_sync_shopifyorder_warehouse_review",
            ),
            path(
                "<path:object_id>/finance-review/",
                self.admin_site.admin_view(self.finance_review_order),
                name="shopify_sync_shopifyorder_finance_review",
            ),
            path(
                "<path:object_id>/withdraw-warehouse-review/",
                self.admin_site.admin_view(self.withdraw_warehouse_review_order),
                name="shopify_sync_shopifyorder_withdraw_warehouse_review",
            ),
        ]
        return custom_urls + urls

    def _change_url(self, obj):
        return reverse("admin:shopify_sync_shopifyorder_change", args=[obj.pk])

    def _redirect_to_change(self, obj):
        return HttpResponseRedirect(self._change_url(obj))

    def _preserved_changelist_filters(self, request):
        filters = request.GET.get("_changelist_filters") or request.POST.get("_changelist_filters")
        if filters:
            return filters
        referer = request.META.get("HTTP_REFERER", "")
        if referer:
            query = parse_qs(urlparse(referer).query)
            values = query.get("_changelist_filters")
            if values:
                return values[0]
        return ""

    def _review_action_url(self, request, admin_url_name, obj):
        url = reverse(f"admin:{admin_url_name}", args=[obj.pk])
        filters = self._preserved_changelist_filters(request)
        if filters:
            return f"{url}?{urlencode({'_changelist_filters': filters})}"
        return url

    def _changelist_url_with_filters(self, request):
        url = reverse("admin:shopify_sync_shopifyorder_changelist")
        filters = self._preserved_changelist_filters(request)
        if filters:
            return f"{url}?{filters}"
        return url

    def _redirect_after_successful_review(self, request):
        return HttpResponseRedirect(self._changelist_url_with_filters(request))

    def warehouse_review_order(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            self.message_user(request, "订单不存在。", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:shopify_sync_shopifyorder_changelist"))
        if not self.is_shenzhen_user(request):
            self.message_user(request, "只有 Shenzhen Warehouse 可以执行深圳仓审核。", level=messages.WARNING)
            return self._redirect_to_change(obj)
        if obj.settlement_batch_id or obj.settlement_status in FINANCE_LOCKED_STATUSES:
            self.message_user(request, "订单已进入财务/结算阶段，不能重新提交深圳仓审核。", level=messages.WARNING)
            return self._redirect_to_change(obj)
        if obj.settlement_status not in SHENZHEN_COST_EDITABLE_STATUSES:
            self.message_user(request, "只有待深圳仓确认或深圳仓已发货状态可以提交深圳仓审核。", level=messages.WARNING)
            return self._redirect_to_change(obj)
        if not self.is_cost_completed(obj):
            self.message_user(request, "成本未完整，不能提交深圳仓审核。", level=messages.WARNING)
            return self._redirect_to_change(obj)
        ShopifyOrder.objects.filter(pk=obj.pk).update(settlement_status="cost_confirmed")
        self.message_user(request, "深圳仓已确认成本，订单已提交 Admin/Finance 审核。")
        return self._redirect_after_successful_review(request)

    def finance_review_order(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            self.message_user(request, "订单不存在。", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:shopify_sync_shopifyorder_changelist"))
        if not (self.is_finance_user(request) or self.is_super_admin(request)):
            self.message_user(request, "只有 Admin / Finance 可以执行最终审核。", level=messages.WARNING)
            return self._redirect_to_change(obj)
        if obj.settlement_status != "cost_confirmed":
            self.message_user(request, "必须先由深圳仓确认成本后，Admin / Finance 才能审核进入待结算。", level=messages.WARNING)
            return self._redirect_to_change(obj)
        if obj.settlement_batch_id:
            self.message_user(request, "订单已加入结算批次，不能重复审核。", level=messages.WARNING)
            return self._redirect_to_change(obj)
        if not self.is_cost_completed(obj):
            self.message_user(request, "成本未完整，不能进入待结算。", level=messages.WARNING)
            return self._redirect_to_change(obj)
        ShopifyOrder.objects.filter(pk=obj.pk).update(settlement_status="pending_payment")
        self.message_user(request, "Admin/Finance 已确认成本，订单已进入待结算状态。")
        return self._redirect_after_successful_review(request)

    def withdraw_warehouse_review_order(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            self.message_user(request, "订单不存在。", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:shopify_sync_shopifyorder_changelist"))
        if not self.is_shenzhen_user(request):
            self.message_user(request, "只有 Shenzhen Warehouse 可以撤回深圳仓确认。", level=messages.WARNING)
            return self._redirect_to_change(obj)
        if obj.settlement_batch_id or obj.settlement_status in FINANCE_LOCKED_STATUSES:
            self.message_user(request, "订单已进入财务/结算阶段，不能撤回。", level=messages.WARNING)
            return self._redirect_to_change(obj)
        if obj.settlement_status != "cost_confirmed":
            self.message_user(request, "只有已提交 Admin/Finance 审核的订单可以撤回。", level=messages.WARNING)
            return self._redirect_to_change(obj)
        ShopifyOrder.objects.filter(pk=obj.pk).update(settlement_status="pending_warehouse")
        self.message_user(request, "已撤回深圳仓确认，订单回到待深圳仓确认状态。")
        return self._redirect_to_change(obj)

    def review_workflow_actions(self, obj):
        request = getattr(self, "_current_request", None)
        if not obj or not obj.pk or request is None:
            return "-"

        status_label = settlement_status_admin_label(obj.settlement_status)
        cost_completed = self.is_cost_completed(obj)
        locked = obj.settlement_batch_id or obj.settlement_status in FINANCE_LOCKED_STATUSES
        button_style = (
            "display:inline-block;margin:4px 8px 4px 0;padding:7px 12px;"
            "border-radius:4px;background:#0c66e4;color:#fff;font-weight:600;"
            "text-decoration:none;"
        )
        muted_style = "display:inline-block;margin-top:4px;color:#667085;"
        warning_style = "display:inline-block;margin-top:4px;color:#b42318;font-weight:600;"

        if self.is_shenzhen_user(request):
            if locked:
                return format_html(
                    '<span style="{}">订单已进入 Admin/Finance 或结算阶段，深圳仓不能再审核或撤回。</span>',
                    warning_style,
                )
            if obj.settlement_status in SHENZHEN_COST_EDITABLE_STATUSES:
                if not cost_completed:
                    return format_html(
                        '<span style="{}">成本未完整，暂不能提交审核。请先维护深圳仓商品成本、运费或包裹费用。</span>',
                        warning_style,
                    )
                return format_html(
                    '<a href="{}" style="{}" onclick="return confirm(\'确认提交给 Admin/Finance 审核？\');">确认成本 / 提交 Admin-Finance 审核</a>'
                    '<br><span style="{}">当前状态：{}</span>',
                    self._review_action_url(request, "shopify_sync_shopifyorder_warehouse_review", obj),
                    button_style,
                    muted_style,
                    status_label,
                )
            if obj.settlement_status == "cost_confirmed":
                return format_html(
                    '<span style="{}">深圳仓已确认，等待 Admin/Finance 审核。</span><br>'
                    '<a href="{}" style="{}background:#667085;" onclick="return confirm(\'撤回后订单会回到待深圳仓确认，确定继续？\');">撤回确认 / 返回修改成本</a>',
                    muted_style,
                    self._review_action_url(request, "shopify_sync_shopifyorder_withdraw_warehouse_review", obj),
                    button_style,
                )
            return format_html('<span style="{}">当前状态：{}</span>', muted_style, status_label)

        if self.is_finance_user(request) or self.is_super_admin(request):
            if obj.settlement_status in SHENZHEN_COST_EDITABLE_STATUSES:
                return format_html(
                    '<span style="{}">等待深圳仓先确认成本。Admin/Finance 暂不能跳过深圳仓审核。</span>',
                    muted_style,
                )
            if obj.settlement_status == "cost_confirmed":
                if obj.settlement_batch_id:
                    return format_html(
                        '<span style="{}">订单已加入结算批次，不能重复审核。</span>',
                        warning_style,
                    )
                if not cost_completed:
                    return format_html(
                        '<span style="{}">成本未完整，不能进入待结算。</span>',
                        warning_style,
                    )
                return format_html(
                    '<a href="{}" style="{}" onclick="return confirm(\'确认 Admin/Finance 审核，并进入待结算状态？\');">Admin/Finance 确认成本 / 进入待结算</a>'
                    '<br><span style="{}">深圳仓已确认成本。</span>',
                    self._review_action_url(request, "shopify_sync_shopifyorder_finance_review", obj),
                    button_style,
                    muted_style,
                )
            if obj.settlement_status == "pending_payment":
                return format_html('<span style="{}">Admin/Finance 已确认，订单已进入待结算。</span>', muted_style)
            if obj.settlement_status == "paid":
                return format_html('<span style="{}">订单已支付完成。</span>', muted_style)
            return format_html('<span style="{}">当前状态：{}</span>', muted_style, status_label)

        return "-"
    review_workflow_actions.short_description = "审核操作"

    def settlement_status_display(self, obj):
        return settlement_status_admin_label(obj.settlement_status)
    settlement_status_display.short_description = "结算状态"
    settlement_status_display.admin_order_field = "settlement_status"

    def items_count(self, obj):
        items_qs = shenzhen_order_items(obj).select_related("package").order_by("id")
        item_count = items_qs.count()
        if item_count == 0:
            return format_html('<span title="{}">{}</span>', "No Shenzhen items", 0)

        tooltip_lines = []
        for item in items_qs[:8]:
            package_label = f"Package {item.package.package_no}" if item.package_id else "Unassigned"
            product_label = item.product_title or item.sku or f"Line item {item.shopify_line_item_id}"
            if item.variant_title:
                product_label = f"{product_label} - {item.variant_title}"
            tooltip_lines.append(f"{package_label} - {product_label} ×{item.quantity}")
        if item_count > 8:
            tooltip_lines.append(f"... and {item_count - 8} more")

        return format_html('<span title="{}">{}</span>', "\n".join(tooltip_lines), item_count)
    items_count.short_description = "Item Count"

    def total_locked_cost_rmb(self, obj):
        if not self.is_cost_completed(obj):
            return "未完成"
        return f'{order_package_cost_totals(obj)["total_cost"]} RMB'
    total_locked_cost_rmb.short_description = "结算总成本 RMB"

    @admin.display(description="结算总成本 RMB")
    def settlement_total_cost_display(self, obj):
        if not self.is_cost_completed(obj):
            return "未完成"
        return f'{order_package_cost_totals(obj)["total_cost"]} RMB'

    @admin.display(description="利润 AUD")
    def profit_aud_display(self, obj):
        if not self.is_cost_completed(obj):
            return "未完成"
        if (obj.currency or "AUD").upper() != "AUD":
            return f"币种 {obj.currency}"
        totals = order_profit_totals(obj)
        if totals["profit_aud"] is None:
            return "汇率不可用"
        color = "#0a7f32" if totals["profit_aud"] >= 0 else "#b42318"
        return format_html(
            '<span style="color:{};font-weight:600;">{} AUD</span><br><span style="color:#667085;">{}%</span>',
            color,
            totals["profit_aud"],
            totals["profit_rate"] if totals["profit_rate"] is not None else "-",
        )

    def is_cost_completed(self, obj):
        return shenzhen_item_costs_completed(obj)
    is_cost_completed.short_description = "Cost Completed"
    is_cost_completed.boolean = True

    def sticky_order_summary(self, obj):
        if not obj or not obj.pk:
            return "-"
        totals = order_package_cost_totals(obj)
        cost_completed = shenzhen_item_costs_completed(obj)
        total_cost = f'{totals["total_cost"]} RMB' if cost_completed else "未完成"
        profit_html = ""
        if not self.is_shenzhen_user(getattr(self, "_current_request", None)):
            if cost_completed and (obj.currency or "AUD").upper() == "AUD":
                profit_totals = order_profit_totals(obj)
                if profit_totals["profit_aud"] is not None:
                    profit_html = format_html(
                        "<span><strong>利润:</strong> {} AUD</span>"
                        "<span><strong>利润率:</strong> {}%</span>",
                        profit_totals["profit_aud"],
                        profit_totals["profit_rate"] if profit_totals["profit_rate"] is not None else "-",
                    )
                else:
                    profit_html = format_html("<span><strong>利润:</strong> 汇率未设置</span>")
            else:
                profit_html = format_html("<span><strong>利润:</strong> 未完成</span>")
        return format_html(
            "<style>"
            "fieldset.shopify-sticky-order-summary {{"
            "position: sticky; top: 0; z-index: 900; background: #e8f2ff;"
            "border: 2px solid #2f6fbb; box-shadow: 0 3px 12px rgba(31,81,153,.22);"
            "color: #17233c;"
            "}}"
            "fieldset.shopify-sticky-order-summary h2 {{ margin-bottom: 0; color: #0b3f7a; font-weight: 700; }}"
            ".shopify-sticky-order-summary .form-row {{ padding: 8px 10px; }}"
            ".shopify-sticky-order-summary .readonly {{ margin-left: 0; color: #17233c; }}"
            ".shopify-order-sticky-summary {{ display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; }}"
            ".shopify-order-sticky-summary span {{ display: inline-block; padding: 4px 9px; border: 1px solid #8db8e8; border-radius: 4px; background: #ffffff; color: #17233c; }}"
            ".shopify-order-sticky-summary strong {{ color: #0b3f7a; }}"
            "</style>"
            '<div class="shopify-order-sticky-summary">'
            "<span><strong>订单:</strong> {}</span>"
            "<span><strong>客户:</strong> {}</span>"
            "<span><strong>国家:</strong> {}</span>"
            "<span><strong>状态:</strong> {}</span>"
            "<span><strong>深圳仓产品行:</strong> {}</span>"
            "<span><strong>结算总成本:</strong> {}</span>"
            "{}"
            "<span><strong>Tracking:</strong> {}</span>"
            "</div>",
            obj.order_name or obj.order_number or obj.pk,
            obj.customer_name or "-",
            country_label_with_zh(obj.shipping_country),
            settlement_status_admin_label(obj.settlement_status),
            totals["items_count"],
            total_cost,
            profit_html,
            obj.tracking_number or "-",
        )
    sticky_order_summary.short_description = "当前订单"

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

    def shenzhen_items_total_cost_summary(self, obj):
        if not obj or not obj.pk:
            return "-"
        totals = order_package_cost_totals(obj)
        return format_html(
            "<div>"
            "Shenzhen 产品行数量：{}<br>"
            "产品成本合计：{} RMB<br>"
            "运费合计（包裹 + 商品行）：{} RMB<br>"
            "拍单成本合计（包裹 + 商品行）：{} RMB<br>"
            "<strong>当前订单总成本：{} RMB</strong>"
            "</div>",
            totals["items_count"],
            totals["product_cost"],
            totals["shipping_cost"],
            totals["ordering_cost"],
            totals["total_cost"],
        )
    shenzhen_items_total_cost_summary.short_description = "当前结算总成本"

    def profit_summary_for_finance(self, obj):
        if not obj or not obj.pk:
            return "-"
        if (obj.currency or "AUD").upper() != "AUD":
            return format_html(
                '<span style="color:#b42318;font-weight:600;">当前订单币种为 {}，利润统计暂只按澳币订单显示。</span>',
                obj.currency or "-",
            )
        if not self.is_cost_completed(obj):
            return "成本未完整，暂不计算利润。"

        totals = order_profit_totals(obj)
        if totals["profit_aud"] is None:
            return format_html(
                '<span style="color:#b42318;font-weight:600;">实时 AUD/CNY 汇率暂不可用，无法计算利润。</span><br>'
                '<span style="color:#667085;">{}</span>',
                totals["rate_error"] or "-",
            )
        color = "#0a7f32" if totals["profit_aud"] >= 0 else "#b42318"
        return format_html(
            "<div>"
            "深圳仓商品行收入合计：{} AUD<br>"
            "分摊订单级运费/差额：{} AUD<br>"
            "深圳仓收入合计：{} AUD<br>"
            "扣 2% 收款手续费后：{} AUD<br>"
            "PL note 拍单成本：{} AUD<br>"
            "深圳仓结算成本：{} RMB / {} AUD<br>"
            "实时汇率：1 AUD = {} RMB{}<br>"
            '<strong style="color:{};">利润：{} AUD</strong><br>'
            '<strong style="color:{};">利润率：{}%</strong>'
            "</div>",
            totals["shenzhen_items_revenue_aud"],
            totals["shenzhen_order_extra_aud"],
            totals["revenue_aud"],
            totals["net_revenue_aud"],
            totals["ordering_note_cost_aud"],
            totals["cost_rmb"],
            totals["cost_aud"],
            totals["rate"].quantize(Decimal("0.0001")),
            f'（{totals["rate_date"]}）' if totals["rate_date"] else "",
            color,
            totals["profit_aud"],
            color,
            totals["profit_rate"] if totals["profit_rate"] is not None else "-",
        )
    profit_summary_for_finance.short_description = "利润统计（Admin/Finance）"

    def tracking_info_summary(self, obj):
        if not obj or not obj.pk:
            return "-"
        return format_html(
            "<div>"
            "Tracking number：{}<br>"
            "Carrier：{}<br>"
            "Fulfillment status：{}<br>"
            "Fulfilled at：{}<br>"
            "Last synced at：{}"
            "</div>",
            obj.tracking_number or "-",
            obj.tracking_company or "-",
            obj.fulfillment_status_raw or "-",
            obj.fulfilled_at or "-",
            obj.last_order_synced_at or "-",
        )
    tracking_info_summary.short_description = "物流摘要"

    def shopify_note_display(self, obj):
        if not obj or not obj.pk:
            return "-"
        return format_html(
            "<div><strong>Order note:</strong><br>{}<br><strong>Note attributes:</strong><br>{}</div>",
            obj.shopify_note or "-",
            obj.shopify_note_attributes or "-",
        )
    shopify_note_display.short_description = "Shopify order note"

    def get_search_fields(self, request):
        if self.is_shenzhen_user(request):
            return ("order_name", "order_number", "customer_name", "shipping_country")
        return super().get_search_fields(request)

    def get_fieldsets(self, request, obj=None):
        self._current_request = request
        if self.is_shenzhen_user(request):
            return (
                (
                    "当前订单摘要",
                    {
                        "fields": ("sticky_order_summary",),
                        "classes": ("shopify-sticky-order-summary",),
                    },
                ),
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
                    "settlement_status_display",
                    "tracking_number",
                    "tracking_company",
                    "tracking_info_summary",
                    "shopify_note_display",
                    "fulfilled_at",
                    "fulfillment_status_raw",
                    "warehouse_note",
                            "shenzhen_items_total_cost_summary",
                        )
                    },
                ),
                ("时间戳", {"fields": ("synced_at", "updated_at", "last_order_synced_at")} ),
                (
                    "审核操作",
                    {"fields": ("review_workflow_actions",)},
                ),
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
                "tracking_info_summary",
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

    def save_formset(self, request, form, formset, change):
        cost_forms = []
        if formset.model is ShopifyOrderItem:
            for inline_form in formset.forms:
                if not hasattr(inline_form, "cleaned_data"):
                    continue
                if not inline_form.cleaned_data:
                    continue
                if formset.can_delete and inline_form.cleaned_data.get("DELETE"):
                    continue
                old_item_cost = None
                if inline_form.instance and inline_form.instance.pk:
                    old_item_cost = ShopifyOrderItem.objects.filter(
                        pk=inline_form.instance.pk
                    ).values_list("locked_product_cost_rmb", flat=True).first()
                cost_forms.append(
                    (
                        inline_form,
                        old_item_cost,
                        bool(inline_form.cleaned_data.get("update_product_default_cost")),
                    )
                )

        super().save_formset(request, form, formset, change)
        if formset.model is not ShopifyOrderItem:
            return
        history_count = 0
        overwritten_count = 0
        skipped_overwrite_count = 0
        for inline_form, old_item_cost, overwrite_requested in cost_forms:
            item = inline_form.instance
            if not item or not item.pk:
                continue
            item = ShopifyOrderItem.objects.select_related(
                "order", "matched_product"
            ).get(pk=item.pk)
            created, overwritten, overwrite_skipped = record_order_item_product_cost_history(
                item,
                old_item_cost,
                overwrite_requested,
                request.user,
            )
            if created:
                history_count += 1
            if overwritten:
                overwritten_count += 1
            if overwrite_skipped:
                skipped_overwrite_count += 1

        synced_count = 0
        for item in shenzhen_order_items(form.instance):
            if sync_order_item_product_fields_to_product(item):
                synced_count += 1
        if history_count:
            messages.info(
                request,
                f"已记录 {history_count} 条产品成本变动历史；其中 {overwritten_count} 条已更新为产品默认成本。",
            )
        if skipped_overwrite_count:
            messages.warning(
                request,
                f"有 {skipped_overwrite_count} 条产品成本勾选了更新默认成本，但因缺少匹配产品或成本无效而跳过覆盖。",
            )
        if synced_count:
            messages.info(request, f"已同步 {synced_count} 个订单产品行的资料到 ShopifyProduct。")

    def get_actions(self, request):
        actions = super().get_actions(request)
        if self.is_shenzhen_user(request):
            for action_name in ["add_to_settlement_batch", "mark_pending_payment", "submit_payment"]:
                if action_name in actions:
                    del actions[action_name]
        else:
            for action_name in ["mark_cost_confirmed", "withdraw_cost_confirmation", "mark_paid"]:
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

    def allocate_package_costs(self, request, queryset):
        from .sync_helpers import allocate_package_costs as allocate_helper

        processed_orders = 0
        processed_packages = 0
        skipped_packages = 0
        for order in queryset:
            result = allocate_helper(order)
            if result["packages_processed"] or result["skipped_packages"]:
                processed_orders += 1
            processed_packages += result["packages_processed"]
            skipped_packages += result["skipped_packages"]

        self.message_user(
            request,
            (
                f"已按包裹重算 {processed_orders} 个订单、{processed_packages} 个包裹；"
                f"跳过 {skipped_packages} 个无深圳仓商品行的包裹。"
            ),
        )
    allocate_package_costs.short_description = "按包裹重算订单总成本"

    def save_order_shipping_as_country_default(self, request, queryset):
        updated_countries = []
        skipped_missing_country = 0
        skipped_missing_shipping = 0
        for order in queryset:
            if not order.shipping_country:
                skipped_missing_country += 1
                continue
            if not order.order_shipping_cost_rmb or order.order_shipping_cost_rmb <= 0:
                skipped_missing_shipping += 1
                continue
            country_code = order.shipping_country.strip().upper()
            ShenzhenCountryShippingDefault.objects.update_or_create(
                country_code=country_code,
                defaults={
                    "country_name": country_code,
                    "default_shipping_cost_rmb": order.order_shipping_cost_rmb,
                    "updated_by": request.user,
                },
            )
            updated_countries.append(country_code)

        if updated_countries:
            self.message_user(
                request,
                f"已更新国家默认运费：{', '.join(updated_countries)}。同一国家多笔订单被选择时，后处理的订单会覆盖默认值。",
            )
        if skipped_missing_country:
            self.message_user(request, f"已跳过 {skipped_missing_country} 个缺少国家的订单。", level=messages.WARNING)
        if skipped_missing_shipping:
            self.message_user(request, f"已跳过 {skipped_missing_shipping} 个未填写有效运费的订单。", level=messages.WARNING)
        if not updated_countries and not skipped_missing_country and not skipped_missing_shipping:
            self.message_user(request, "没有可保存为国家默认运费的订单。", level=messages.WARNING)
    save_order_shipping_as_country_default.short_description = "将所选订单运费保存为国家默认运费"

    def save_order_item_shipping_as_product_country_default(self, request, queryset):
        saved_count = 0
        skipped_missing_country = 0
        skipped_missing_variant = 0
        skipped_missing_shipping = 0
        for order in queryset:
            if not order.shipping_country:
                skipped_missing_country += shenzhen_order_items(order).count()
                continue
            country_code = order.shipping_country.strip().upper()
            for item in shenzhen_order_items(order):
                if not item.shopify_variant_id:
                    skipped_missing_variant += 1
                    continue
                if not item.locked_shipping_cost_rmb or item.locked_shipping_cost_rmb <= 0:
                    skipped_missing_shipping += 1
                    continue
                ShenzhenProductCountryShippingDefault.objects.update_or_create(
                    country_code=country_code,
                    shopify_variant_id=item.shopify_variant_id,
                    defaults={
                        "country_name": country_code,
                        "shopify_product_id": item.shopify_product_id,
                        "sku": item.sku or "",
                        "product_title": item.product_title or "",
                        "variant_title": item.variant_title or "",
                        "matched_product": item.matched_product,
                        "default_shipping_cost_rmb": item.locked_shipping_cost_rmb,
                        "updated_by": request.user,
                    },
                )
                saved_count += 1

        self.message_user(
            request,
            (
                f"已保存 {saved_count} 条产品+国家默认运费；"
                f"跳过缺少国家 {skipped_missing_country} 条、缺少 variant_id {skipped_missing_variant} 条、"
                f"未填写有效运费 {skipped_missing_shipping} 条。"
            ),
        )
    save_order_item_shipping_as_product_country_default.short_description = "将所选订单商品运费保存为产品国家默认运费"

    def copy_product_cost_to_items(self, request, queryset):
        if not (self.is_shenzhen_user(request) or self.is_finance_user(request) or self.is_super_admin(request)):
            self.message_user(request, "只有深圳仓或 Finance 可以执行此操作。")
            return
        
        copied_count = 0
        history_count = 0
        for order in queryset:
            for item in shenzhen_order_items(order):
                if item.locked_product_cost_rmb is None and item.matched_product and item.matched_product.product_cost_rmb:
                    old_item_cost = item.locked_product_cost_rmb
                    item.locked_product_cost_rmb = item.matched_product.product_cost_rmb
                    item.save(update_fields=["locked_product_cost_rmb"])
                    created, _, _ = record_order_item_product_cost_history(
                        ShopifyOrderItem.objects.select_related("order", "matched_product").get(pk=item.pk),
                        old_item_cost,
                        False,
                        request.user,
                        source="copy_product_cost_to_items",
                        note_override="Product cost copied from matched ShopifyProduct.",
                    )
                    if created:
                        history_count += 1
                    copied_count += 1
        
        self.message_user(request, f"已复制 {copied_count} 个订单项目的产品成本，并记录 {history_count} 条成本历史。")
    copy_product_cost_to_items.short_description = "复制产品成本到订单项"

    def backfill_items_from_matched_products(self, request, queryset):
        processed_orders = queryset.count()
        processed_items = 0
        updated_fields = 0
        history_count = 0
        for order in queryset:
            for item in shenzhen_order_items(order).select_related("matched_product"):
                processed_items += 1
                old_item_cost = item.locked_product_cost_rmb
                updated_fields += backfill_order_item_from_matched_product(item, save=True)
                if item.pk:
                    item.refresh_from_db()
                    created, _, _ = record_order_item_product_cost_history(
                        item,
                        old_item_cost,
                        False,
                        request.user,
                        source="backfill_items_from_matched_products",
                        note_override="Product cost backfilled from matched ShopifyProduct.",
                    )
                    if created:
                        history_count += 1
        self.message_user(
            request,
            f"已处理 {processed_orders} 个订单、{processed_items} 个深圳仓商品行，实际回填 {updated_fields} 个字段，并记录 {history_count} 条成本历史。",
        )
    backfill_items_from_matched_products.short_description = "从匹配产品回填订单商品资料"

    def mark_cost_confirmed(self, request, queryset):
        if not self.is_shenzhen_user(request):
            self.message_user(request, "只有深圳仓用户可以执行此操作。")
            return
        valid_orders = queryset.filter(settlement_status__in=["pending_warehouse", "warehouse_fulfilled"])
        completed_orders = [order for order in valid_orders if self.is_cost_completed(order)]
        updated = ShopifyOrder.objects.filter(pk__in=[order.pk for order in completed_orders]).update(settlement_status="cost_confirmed")
        skipped = valid_orders.count() - len(completed_orders)
        if updated:
            self.message_user(request, f"深圳仓已审核 {updated} 个订单，状态已进入 Admin/Finance 待审核。")
        if skipped:
            self.message_user(request, f"有 {skipped} 个订单因成本未完整而未通过深圳仓审核。")

    mark_cost_confirmed.short_description = "深圳仓审核订单 / 提交 Admin-Finance 审核"

    def withdraw_cost_confirmation(self, request, queryset):
        if not self.is_shenzhen_user(request):
            self.message_user(request, "只有 Shenzhen Warehouse 用户可以撤回成本确认。", level=messages.WARNING)
            return

        blocked_count = queryset.filter(
            models.Q(settlement_status__in=FINANCE_LOCKED_STATUSES)
            | models.Q(settlement_batch__isnull=False)
        ).count()
        eligible_orders = queryset.filter(
            settlement_status="cost_confirmed",
            settlement_batch__isnull=True,
        )
        updated = eligible_orders.update(settlement_status="pending_warehouse")
        skipped_count = queryset.count() - updated - blocked_count

        if updated:
            self.message_user(
                request,
                f"已撤回 {updated} 个订单的成本确认，状态已回到 pending_warehouse，可继续修改成本。",
            )
        if blocked_count:
            self.message_user(
                request,
                "订单已进入待支付/已支付/结算批次阶段，不能撤回。",
                level=messages.WARNING,
            )
        if skipped_count:
            self.message_user(
                request,
                f"有 {skipped_count} 个订单不是 cost_confirmed 状态，未撤回。",
                level=messages.WARNING,
            )

    withdraw_cost_confirmation.short_description = "撤回成本确认 / 返回修改成本"

    def mark_pending_payment(self, request, queryset):
        if not (self.is_finance_user(request) or self.is_super_admin(request)):
            self.message_user(request, "只有 Finance 或超级管理员可以执行此操作。")
            return
        valid_orders = queryset.filter(settlement_status="cost_confirmed")
        updated = valid_orders.update(settlement_status="pending_payment")
        if updated != queryset.count():
            self.message_user(
                request,
                f"只有 {updated} 个订单通过 Admin/Finance 审核并进入待结算状态；订单必须先完成深圳仓审核。",
                level=messages.WARNING,
            )
        else:
            self.message_user(request, f"Admin/Finance 已审核 {updated} 个订单，状态已进入待结算。")

    mark_pending_payment.short_description = "Admin/Finance 审核订单 / 进入待结算"

    def submit_payment(self, request, queryset):
        if not (self.is_super_admin(request) or self.is_finance_user(request)):
            self.message_user(request, "只有 Finance 或超级管理员可以提交支付。", level=messages.WARNING)
            return

        eligible_orders = queryset.filter(
            settlement_status="pending_payment",
            settlement_batch__isnull=False,
        )
        skipped = queryset.count() - eligible_orders.count()
        order_ids = list(eligible_orders.values_list("pk", flat=True))
        updated = ShopifyOrder.objects.filter(pk__in=order_ids).update(settlement_status="payment_submitted")
        now = timezone.now()
        touched_batches = SettlementBatch.objects.filter(orders__pk__in=order_ids).distinct()
        batch_updated = 0
        for batch in touched_batches:
            if not batch.orders.exclude(settlement_status__in=["payment_submitted", "paid"]).exists():
                batch.status = "payment_submitted"
                batch.payment_submitted_at = now
                batch.payment_submitted_by = request.user.get_username()
                batch.save(update_fields=["status", "payment_submitted_at", "payment_submitted_by"])
                batch_updated += 1

        if updated:
            self.message_user(
                request,
                f"已提交支付 {updated} 个订单，状态已进入“已提交支付，待深圳仓确认收款”。"
                f" 同步更新 {batch_updated} 个结算批次。",
            )
        if skipped:
            self.message_user(
                request,
                f"有 {skipped} 个订单未提交支付：必须是待支付状态，并且已加入结算批次。",
                level=messages.WARNING,
            )

    submit_payment.short_description = "提交支付 / 等待深圳仓确认收款"

    def mark_paid(self, request, queryset):
        if not self.is_shenzhen_user(request):
            self.message_user(request, "只有 Shenzhen Warehouse 可以确认收款并标记已支付。", level=messages.WARNING)
            return

        eligible_orders = queryset.filter(settlement_status="payment_submitted")
        paid_order_ids = []
        skipped_missing_proof = 0
        skipped_invalid = queryset.count() - eligible_orders.count()
        for order in eligible_orders.select_related("settlement_batch"):
            if not order.settlement_batch_id or not order.settlement_batch.payment_proof:
                skipped_missing_proof += 1
                continue
            paid_order_ids.append(order.pk)

        updated = ShopifyOrder.objects.filter(pk__in=paid_order_ids).update(settlement_status="paid")
        touched_batches = SettlementBatch.objects.filter(orders__pk__in=paid_order_ids).distinct()
        batch_updated = 0
        for batch in touched_batches:
            if not batch.orders.exclude(settlement_status="paid").exists():
                batch.status = "paid"
                batch.paid_at = timezone.now()
                batch.save(update_fields=["status", "paid_at"])
                batch_updated += 1

        if updated:
            self.message_user(request, f"深圳仓已确认收到款，{updated} 个订单已标记为已支付。同步更新 {batch_updated} 个结算批次。")
        else:
            self.message_user(request, "没有订单被标记为已支付。", level=messages.WARNING)
        if skipped_missing_proof:
            self.message_user(request, f"有 {skipped_missing_proof} 个订单未标记：结算批次缺少付款凭证。", level=messages.WARNING)
        if skipped_invalid:
            self.message_user(request, f"有 {skipped_invalid} 个订单未标记：必须先处于“已提交支付，待深圳仓确认收款”状态。", level=messages.WARNING)

    mark_paid.short_description = "深圳仓确认收款 / 标记已支付"

    def add_to_settlement_batch(self, request, queryset):
        if not (self.is_finance_user(request) or self.is_super_admin(request)):
            self.message_user(request, "只有 Finance 或超级管理员可以执行此操作。")
            return

        eligible_orders = queryset.filter(
            settlement_status="pending_payment",
            is_shenzhen_order=True,
            settlement_batch__isnull=True,
        ).filter(order_items__fulfillment_location=SHENZHEN_ITEM_LOCATION).distinct()
        invalid_count = queryset.count() - eligible_orders.count()

        if eligible_orders.count() == 0:
            self.message_user(request, "没有符合条件的订单可加入新的结算批次。")
            return

        from .sync_helpers import allocate_package_costs as recalc_package_total

        complete_order_ids = [order.pk for order in eligible_orders if shenzhen_item_costs_completed(order)]
        eligible_orders = eligible_orders.filter(pk__in=complete_order_ids)
        if not complete_order_ids:
            self.message_user(request, "没有成本完整的订单可加入结算批次，请先填写产品成本，以及包裹费用或商品行费用。", level=messages.WARNING)
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
            recalc_package_total(order)
            order.settlement_batch = batch
            order.save(update_fields=["settlement_batch"])
        batch.total_amount_rmb = sum(
            (order.total_locked_cost_rmb or ZERO)
            for order in batch.orders.all()
        )
        batch.save(update_fields=["total_amount_rmb"])

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
        "payment_proof_link",
        "payment_submitted_at",
        "created_by",
        "created_at",
        "paid_at",
    )
    fields = (
        "batch_no",
        "status",
        "total_amount_rmb",
        "created_by",
        "created_at",
        "payment_proof",
        "payment_proof_link",
        "payment_submitted_at",
        "payment_submitted_by",
        "paid_at",
        "note",
    )
    readonly_fields = (
        "status",
        "total_amount_rmb",
        "created_by",
        "created_at",
        "payment_proof_link",
        "payment_submitted_at",
        "payment_submitted_by",
        "paid_at",
    )
    actions = ["submit_batch_payment", "mark_batch_paid", "export_batch_csv"]
    search_fields = ("batch_no", "created_by", "note")
    list_filter = ("status", "created_at")

    def get_actions(self, request):
        actions = super().get_actions(request)
        if self.is_shenzhen_user(request):
            for action_name in ["submit_batch_payment", "export_batch_csv"]:
                if action_name in actions:
                    del actions[action_name]
        else:
            if "mark_batch_paid" in actions:
                del actions["mark_batch_paid"]
        return actions

    def has_view_permission(self, request, obj=None):
        return self.is_role_allowed(request)

    def has_change_permission(self, request, obj=None):
        return self.is_role_allowed(request)

    def get_readonly_fields(self, request, obj=None):
        readonly = list(self.readonly_fields)
        if self.is_shenzhen_user(request):
            readonly.extend(field.name for field in self.model._meta.fields)
        return tuple(dict.fromkeys(readonly))

    def payment_proof_link(self, obj):
        if not obj or not obj.payment_proof:
            return "-"
        return format_html('<a href="{}" target="_blank">查看付款凭证</a>', obj.payment_proof.url)
    payment_proof_link.short_description = "付款凭证"

    def submit_batch_payment(self, request, queryset):
        if not (self.is_super_admin(request) or self.is_finance_user(request)):
            self.message_user(request, "只有 Finance 或超级管理员可以提交支付。", level=messages.WARNING)
            return
        updated = 0
        skipped = 0
        now = timezone.now()
        for batch in queryset:
            if batch.status != "pending_payment":
                skipped += 1
                continue
            batch.status = "payment_submitted"
            batch.payment_submitted_at = now
            batch.payment_submitted_by = request.user.get_username()
            batch.save(update_fields=["status", "payment_submitted_at", "payment_submitted_by"])
            batch.orders.filter(settlement_status="pending_payment").update(settlement_status="payment_submitted")
            updated += 1
        if updated:
            self.message_user(request, f"已提交支付 {updated} 个结算批次，相关订单进入“已提交支付，待深圳仓确认收款”。")
        if skipped:
            self.message_user(request, f"有 {skipped} 个结算批次未提交支付：必须是待支付状态。", level=messages.WARNING)
    submit_batch_payment.short_description = "提交支付 / 等待深圳仓确认收款"

    def mark_batch_paid(self, request, queryset):
        if not self.is_shenzhen_user(request):
            self.message_user(request, "只有 Shenzhen Warehouse 可以确认收款。", level=messages.WARNING)
            return
        updated = 0
        skipped_status = 0
        skipped_missing_proof = 0
        for batch in queryset:
            if batch.status != "payment_submitted":
                skipped_status += 1
                continue
            if not batch.payment_proof:
                skipped_missing_proof += 1
                continue
            batch.status = "paid"
            batch.paid_at = timezone.now()
            batch.save(update_fields=["status", "paid_at"])
            batch.orders.filter(settlement_status="payment_submitted").update(settlement_status="paid")
            updated += 1
        if updated:
            self.message_user(request, f"深圳仓已确认收款，{updated} 个结算批次和对应订单已标记为已支付。")
        if skipped_status:
            self.message_user(request, f"有 {skipped_status} 个结算批次未确认：必须先提交支付。", level=messages.WARNING)
        if skipped_missing_proof:
            self.message_user(request, f"有 {skipped_missing_proof} 个结算批次未确认：缺少付款凭证。", level=messages.WARNING)
    mark_batch_paid.short_description = "深圳仓确认收款 / 标记已支付"

    def export_batch_csv(self, request, queryset):
        incomplete_orders = [
            order.order_name
            for batch in queryset
            for order in batch.orders.all()
            if not shenzhen_item_costs_completed(order)
        ]
        if incomplete_orders:
            self.message_user(
                request,
                f"以下订单产品成本或包裹费用未完整，无法导出 CSV：{', '.join(incomplete_orders[:10])}",
                level=messages.WARNING,
            )
            return

        rows = []
        for batch in queryset:
            for order in batch.orders.all().select_related("settlement_batch"):
                for item in shenzhen_order_items(order):
                    package = item.package
                    product_line_total = item_product_cost_total(item)
                    package_totals = package_cost_totals(package) if package else None
                    rows.append([
                        batch.batch_no,
                        order.order_name,
                        order.shipping_country,
                        item.sku,
                        package.package_no if package else "",
                        package.tracking_number if package else "",
                        package.carrier if package else "",
                        package.shipping_cost_rmb if package else "",
                        package.ordering_cost_rmb if package else "",
                        package_totals["total_cost"] if package_totals else "",
                        item.quantity,
                        item.locked_product_cost_rmb,
                        product_line_total,
                        item.locked_shipping_cost_rmb,
                        item.handling_fee_rmb,
                        item.total_cost_rmb,
                        order.total_locked_cost_rmb,
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
            "package_no",
            "package_tracking_number",
            "package_carrier",
            "package_shipping_cost_rmb",
            "package_ordering_cost_rmb",
            "package_current_total_cost_rmb",
            "quantity",
            "unit_product_cost_rmb",
            "item_product_cost_total_rmb",
            "item_shipping_cost_rmb",
            "item_ordering_cost_rmb",
            "item_total_cost_rmb",
            "order_total_cost_rmb",
            "tracking_number",
        ])
        for row in rows:
            writer.writerow(row)
        return response
    export_batch_csv.short_description = "导出结算批次对账 CSV"


@admin.register(ShopifyProduct)
class ShopifyProductAdmin(ShopifyRoleAdminMixin, admin.ModelAdmin):
    change_list_template = "admin/shopify_sync_changelist.html"
    ordering = ("-shopify_published_at", "-shopify_product_created_at", "-id")
    list_display = (
        "product_title",
        "variant_title",
        "sku",
        "is_shenzhen_product",
        "product_cost_rmb",
        "weight_kg",
        "shopify_published_at",
        "shopify_product_created_at",
        "last_synced_at",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "last_synced_at",
        "shopify_product_created_at",
        "shopify_product_updated_at",
        "shopify_published_at",
        "volume_weight_kg",
    )
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
                    "shopify_product_created_at",
                    "shopify_product_updated_at",
                    "shopify_published_at",
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


@admin.register(ShopifyProductCostHistory)
class ShopifyProductCostHistoryAdmin(ShopifyRoleAdminMixin, admin.ModelAdmin):
    list_display = (
        "changed_at",
        "changed_by",
        "product_title",
        "sku",
        "shopify_variant_id",
        "old_item_cost_rmb",
        "new_item_cost_rmb",
        "old_product_cost_rmb",
        "new_product_cost_rmb",
        "overwrite_product_cost",
        "order",
    )
    search_fields = (
        "product_title",
        "sku",
        "=shopify_product_id",
        "=shopify_variant_id",
        "order__order_name",
        "order__order_number",
    )
    list_filter = ("overwrite_product_cost", "changed_at", "changed_by")
    readonly_fields = (
        "order",
        "order_item",
        "product",
        "shopify_product_id",
        "shopify_variant_id",
        "sku",
        "product_title",
        "old_item_cost_rmb",
        "new_item_cost_rmb",
        "old_product_cost_rmb",
        "new_product_cost_rmb",
        "overwrite_product_cost",
        "changed_by",
        "changed_at",
        "source",
        "note",
    )
    ordering = ("-changed_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return self.is_role_allowed(request)


@admin.register(FinanceExchangeRate)
class FinanceExchangeRateAdmin(ShopifyRoleAdminMixin, admin.ModelAdmin):
    list_display = (
        "base_currency",
        "quote_currency",
        "rate",
        "effective_date",
        "is_active",
        "updated_by",
        "updated_at",
    )
    search_fields = ("base_currency", "quote_currency", "note")
    list_filter = ("is_active", "base_currency", "quote_currency", "effective_date")
    ordering = ("-effective_date", "-updated_at")
    readonly_fields = ("updated_by", "updated_at")
    fields = (
        "base_currency",
        "quote_currency",
        "rate",
        "effective_date",
        "is_active",
        "note",
        "updated_by",
        "updated_at",
    )

    def _can_manage_exchange_rates(self, request):
        return self.is_super_admin(request) or self.is_finance_user(request)

    def has_module_permission(self, request):
        return self._can_manage_exchange_rates(request)

    def has_view_permission(self, request, obj=None):
        return self._can_manage_exchange_rates(request)

    def has_add_permission(self, request):
        return self._can_manage_exchange_rates(request)

    def has_change_permission(self, request, obj=None):
        return self._can_manage_exchange_rates(request)

    def has_delete_permission(self, request, obj=None):
        return self.is_super_admin(request)

    def save_model(self, request, obj, form, change):
        obj.base_currency = (obj.base_currency or "AUD").strip().upper()
        obj.quote_currency = (obj.quote_currency or "CNY").strip().upper()
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ShenzhenCountryShippingDefault)
class ShenzhenCountryShippingDefaultAdmin(ShopifyRoleAdminMixin, admin.ModelAdmin):
    list_display = (
        "country_code",
        "country_name",
        "default_shipping_cost_rmb",
        "updated_by",
        "updated_at",
    )
    search_fields = ("country_code", "country_name")
    ordering = ("country_code",)
    readonly_fields = ("updated_at",)

    def save_model(self, request, obj, form, change):
        obj.country_code = (obj.country_code or "").strip().upper()
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

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


    def get_fieldsets(self, request, obj=None):
        return super().get_fieldsets(request, obj)

    def get_list_display(self, request):
        return self.list_display

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields


@admin.register(ShenzhenProductCountryShippingDefault)
class ShenzhenProductCountryShippingDefaultAdmin(ShopifyRoleAdminMixin, admin.ModelAdmin):
    list_display = (
        "country_code",
        "product_title",
        "variant_title",
        "sku",
        "shopify_variant_id",
        "default_shipping_cost_rmb",
        "updated_by",
        "updated_at",
    )
    search_fields = (
        "country_code",
        "product_title",
        "variant_title",
        "sku",
        "shopify_product_id",
        "shopify_variant_id",
    )
    ordering = ("country_code", "product_title", "variant_title")
    readonly_fields = ("updated_at",)

    def save_model(self, request, obj, form, change):
        obj.country_code = (obj.country_code or "").strip().upper()
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


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


