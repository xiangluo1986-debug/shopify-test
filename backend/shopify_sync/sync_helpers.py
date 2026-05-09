import re
import time
from decimal import Decimal
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import requests
from django.db import connection
from django.db import models
from django.db import transaction
from django.utils import timezone

from .models import (
    ShenzhenCountryShippingDefault,
    ShenzhenProductCountryShippingDefault,
    ShopifyInstallation,
    ShopifyOrder,
    ShopifyOrderItem,
    ShopifyProduct,
    ShopifySyncState,
    ShippingCostRule,
)


def get_next_page_info_from_link_header(link_header):
    if not link_header:
        return None

    for link in requests.utils.parse_header_links(link_header):
        if link.get("rel") != "next":
            continue
        parsed = urlparse(link.get("url", ""))
        page_info = parse_qs(parsed.query).get("page_info")
        if page_info:
            return page_info[0]
    return None


ORDER_SYNC_TASK_NAMES = [
    "orders_incremental",
    "orders_manual_1",
    "orders_manual_3",
    "orders_manual_7",
    "orders_manual_30",
    "orders_manual_60",
    "orders_manual",
]


def summarize_sync_result(result):
    if isinstance(result, dict):
        parts = []
        for key, value in result.items():
            if key == "errors":
                if value:
                    parts.append(f"errors={len(value)}")
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                parts.append(f"{key}={value}")
        return ", ".join(parts)[:1000]
    return str(result)[:1000]


def run_shopify_sync_task(task_name, func, stale_after_minutes=120, conflict_task_names=None):
    now = timezone.now()
    stale_before = now - timedelta(minutes=stale_after_minutes)
    conflict_task_names = list(conflict_task_names or [task_name])

    with transaction.atomic():
        state, _ = ShopifySyncState.objects.select_for_update().get_or_create(
            task_name=task_name
        )
        running_conflict = (
            ShopifySyncState.objects.select_for_update()
            .filter(
                task_name__in=conflict_task_names,
                is_running=True,
                started_at__gte=stale_before,
            )
            .exclude(task_name=task_name)
            .first()
        )
        if running_conflict:
            state.last_result = (
                f"Skipped because {running_conflict.task_name} is already running "
                f"since {running_conflict.started_at}."
            )
            state.save(update_fields=["last_result", "updated_at"])
            return {
                "skipped": True,
                "task_name": task_name,
                "reason": state.last_result,
            }

        stale_note = ""
        if state.is_running and state.started_at and state.started_at >= stale_before:
            return {
                "skipped": True,
                "task_name": task_name,
                "reason": f"Sync task {task_name} is already running since {state.started_at}.",
            }
        if state.is_running:
            stale_note = f"Stale lock takeover. Previous started_at={state.started_at}. "

        state.is_running = True
        state.started_at = now
        state.finished_at = None
        state.last_error = ""
        state.last_result = stale_note + "Started."
        state.save(update_fields=[
            "is_running",
            "started_at",
            "finished_at",
            "last_error",
            "last_result",
            "updated_at",
        ])

    try:
        result = func()
    except Exception as exc:
        finished_at = timezone.now()
        ShopifySyncState.objects.filter(task_name=task_name).update(
            is_running=False,
            finished_at=finished_at,
            last_error=f"{exc.__class__.__name__}: {exc}",
            last_result="Failed.",
            updated_at=finished_at,
        )
        raise

    finished_at = timezone.now()
    summary = summarize_sync_result(result)
    if stale_note:
        summary = (stale_note + summary)[:1000]
    ShopifySyncState.objects.filter(task_name=task_name).update(
        is_running=False,
        finished_at=finished_at,
        last_success_at=finished_at,
        last_error="",
        last_result=summary,
        updated_at=finished_at,
    )
    return {
        "skipped": False,
        "task_name": task_name,
        "result": result,
    }


def was_sync_successful_today(task_name):
    state = ShopifySyncState.objects.filter(task_name=task_name).first()
    if not state or not state.last_success_at:
        return False
    return timezone.localtime(state.last_success_at).date() == timezone.localdate()


def has_ship_from_china_tag(order):
    tags = order.get("tags") or ""
    if not isinstance(tags, str):
        return False
    normalized_tags = {
        tag.strip().lower()
        for tag in tags.split(",")
        if tag.strip()
    }
    return "ship from china" in normalized_tags


def _shopify_retry_delay(response, attempt):
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), 0)
        except ValueError:
            pass
    return min(2 + attempt, 5)


def shopify_get(url, access_token, params=None, timeout=30, max_retries=5):
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }

    for attempt in range(max_retries + 1):
        response = requests.get(url, params=params, headers=headers, timeout=timeout)
        if response.status_code == 429 or 500 <= response.status_code < 600:
            if attempt >= max_retries:
                response.raise_for_status()
            delay = _shopify_retry_delay(response, attempt)
            print(
                f"Warning: Shopify API returned {response.status_code}; "
                f"retrying in {delay:.1f}s ({attempt + 1}/{max_retries})."
            )
            time.sleep(delay)
            continue

        response.raise_for_status()
        return response

    response.raise_for_status()
    return response


def normalize_location_name(name):
    if not name:
        return "unknown"
    name_lower = name.lower()
    if "shenzhen" in name_lower:
        return "shenzhen"
    if any(keyword in name_lower for keyword in ["australia", "sydney", "mascot"]):
        return "australia_sydney"
    return name_lower.replace(" ", "_").replace("(", "").replace(")", "")


def summarize_current_locations(fulfillment_orders):
    normalized_locations = set()
    raw_names = set()
    for fo in fulfillment_orders:
        assigned_location = fo.get("assigned_location", {})
        location_name = assigned_location.get("name", "")
        if location_name:
            raw_names.add(location_name)
            normalized_locations.add(normalize_location_name(location_name))

    if not normalized_locations:
        return "unknown", ""
    if normalized_locations == {"shenzhen"}:
        return "shenzhen", ", ".join(sorted(raw_names))
    if "shenzhen" in normalized_locations and len(normalized_locations) > 1:
        return "mixed", ", ".join(sorted(raw_names))
    if len(normalized_locations) == 1:
        return next(iter(normalized_locations)), ", ".join(sorted(raw_names))
    return "mixed", ", ".join(sorted(raw_names))


def shopify_request_json(url, access_token, params=None, timeout=30):
    response = shopify_get(url, access_token, params=params, timeout=timeout)
    return response.json()


def fetch_shopify_orders(shop_domain, access_token, start_date_str):
    api_url = f"https://{shop_domain}/admin/api/2024-01/orders.json"
    page_info = None
    seen_page_info = set()
    while True:
        if page_info:
            params = {"limit": 250, "page_info": page_info}
        else:
            params = {
                "limit": 250,
                "created_at_min": start_date_str,
                "status": "any",
                "fields": "id,name,order_number,created_at,financial_status,fulfillment_status,total_price,currency,customer,shipping_address,line_items,tags,note,note_attributes"
            }

        response = shopify_get(api_url, access_token, params=params, timeout=30)
        data = response.json()
        orders = data.get("orders", [])
        for order in orders:
            yield order, data

        link_header = response.headers.get("Link", "")
        next_page_info = get_next_page_info_from_link_header(link_header)
        if next_page_info:
            if next_page_info in seen_page_info:
                print("Warning: repeated Shopify orders page_info detected; stopping pagination.")
                break
            seen_page_info.add(next_page_info)
            page_info = next_page_info
            continue
        break


def fetch_order_fulfillment_orders(shop_domain, order_id, access_token):
    api_url = f"https://{shop_domain}/admin/api/2024-01/orders/{order_id}/fulfillment_orders.json"
    data = shopify_request_json(api_url, access_token)
    return data.get("fulfillment_orders", [])


def fetch_order_fulfillments(shop_domain, order_id, access_token):
    api_url = f"https://{shop_domain}/admin/api/2024-01/orders/{order_id}/fulfillments.json"
    data = shopify_request_json(api_url, access_token)
    return data.get("fulfillments", [])


def fetch_location_name(shop_domain, location_id, access_token):
    api_url = f"https://{shop_domain}/admin/api/2024-01/locations/{location_id}.json"
    data = shopify_request_json(api_url, access_token)
    location = data.get("location", {})
    return location.get("name", "")


def _get_shenzhen_line_item_ids(fulfillment_orders):
    shenzhen_line_item_ids = set()
    for fo in fulfillment_orders:
        assigned_location = fo.get("assigned_location", {})
        normalized = normalize_location_name(assigned_location.get("name", ""))
        if normalized == "shenzhen":
            for item in fo.get("line_items", []):
                line_item_id = item.get("line_item_id")
                if line_item_id is not None:
                    shenzhen_line_item_ids.add(line_item_id)
    return shenzhen_line_item_ids


def _fulfillment_has_shenzhen_line_items(fulfillment, shenzhen_line_item_ids):
    for item in fulfillment.get("line_items", []):
        if item.get("line_item_id") in shenzhen_line_item_ids:
            return True
    return False


def _is_shenzhen_fulfillment(fulfillment, shenzhen_line_item_ids, shop_domain, access_token, location_cache):
    location_id = fulfillment.get("location_id")
    if location_id:
        normalized = location_cache.get(location_id)
        if normalized is None:
            location_name = fetch_location_name(shop_domain, location_id, access_token)
            normalized = normalize_location_name(location_name)
            location_cache[location_id] = normalized
        if normalized == "shenzhen":
            return True
    if _fulfillment_has_shenzhen_line_items(fulfillment, shenzhen_line_item_ids):
        return True
    return False


def _format_tracking_value(fulfillment, field_name):
    value = fulfillment.get(field_name)
    if value:
        return value
    plural = f"{field_name}s"
    values = fulfillment.get(plural)
    if isinstance(values, list) and values:
        return values[0]
    return ""


def _apply_fulfillment_updates(order_obj, fulfillment_orders, fulfillments, shop_domain, access_token):
    shenzhen_line_item_ids = _get_shenzhen_line_item_ids(fulfillment_orders)
    if not shenzhen_line_item_ids:
        return False, False, 0

    location_cache = {}
    tracking_number = None
    tracking_company = None
    tracking_url = None
    fulfilled_at = None
    statuses = set()
    updated_tracking = False
    auto_marked = False
    detected_tracking_count = 0

    for fulfillment in fulfillments:
        if not _is_shenzhen_fulfillment(fulfillment, shenzhen_line_item_ids, shop_domain, access_token, location_cache):
            continue

        status = fulfillment.get("status", "")
        if status:
            statuses.add(status)

        candidate_tracking_number = _format_tracking_value(fulfillment, "tracking_number")
        if candidate_tracking_number:
            detected_tracking_count += 1
            if not tracking_number:
                tracking_number = candidate_tracking_number
                tracking_company = _format_tracking_value(fulfillment, "tracking_company")
                tracking_url = _format_tracking_value(fulfillment, "tracking_url")
                if not tracking_url:
                    tracking_url = _format_tracking_value(fulfillment, "tracking_urls")
                created_at = fulfillment.get("created_at")
                if created_at:
                    try:
                        fulfilled_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    except ValueError:
                        fulfilled_at = None

        fulfillment_id = fulfillment.get("id")
        item_fulfilled_at = None
        if fulfillment.get("created_at"):
            try:
                item_fulfilled_at = datetime.fromisoformat(fulfillment["created_at"].replace("Z", "+00:00"))
            except ValueError:
                item_fulfilled_at = None

        for item in fulfillment.get("line_items", []):
            line_item_id = item.get("line_item_id")
            if line_item_id is None:
                continue
            order_item = ShopifyOrderItem.objects.filter(order=order_obj, shopify_line_item_id=line_item_id).first()
            if not order_item:
                continue
            update_fields = []
            if order_item.fulfilled_quantity != item.get("quantity"):
                order_item.fulfilled_quantity = item.get("quantity")
                update_fields.append("fulfilled_quantity")
            if order_item.fulfillment_id != fulfillment_id:
                order_item.fulfillment_id = fulfillment_id
                update_fields.append("fulfillment_id")
            if item_fulfilled_at and order_item.item_fulfilled_at != item_fulfilled_at:
                order_item.item_fulfilled_at = item_fulfilled_at
                update_fields.append("item_fulfilled_at")
            if update_fields:
                order_item.save(update_fields=update_fields)

    current_updates = {}
    if tracking_number and order_obj.tracking_number != tracking_number:
        current_updates["tracking_number"] = tracking_number
    if tracking_company and order_obj.tracking_company != tracking_company:
        current_updates["tracking_company"] = tracking_company
    if tracking_url and order_obj.tracking_url != tracking_url:
        current_updates["tracking_url"] = tracking_url
    if fulfilled_at and order_obj.fulfilled_at != fulfilled_at:
        current_updates["fulfilled_at"] = fulfilled_at
    if statuses:
        raw_statuses = ",".join(sorted(statuses))
        if order_obj.fulfillment_status_raw != raw_statuses:
            current_updates["fulfillment_status_raw"] = raw_statuses
    current_updates["last_order_synced_at"] = timezone.now()

    if tracking_number and order_obj.current_location == "shenzhen" and order_obj.settlement_status == "pending_warehouse":
        current_updates["settlement_status"] = "warehouse_fulfilled"
        auto_marked = True

    if current_updates:
        for field, value in current_updates.items():
            setattr(order_obj, field, value)
        update_fields = [k for k in current_updates.keys()]
        order_obj.save(update_fields=update_fields)
        updated_tracking = True

    return updated_tracking, auto_marked, detected_tracking_count


def _process_shenzhen_order(
    installation,
    order_data,
    shenzhen_items,
    current_location_normalized,
    current_location_raw,
):
    order_id = order_data["id"]
    customer = order_data.get("customer", {})
    customer_name = " ".join(filter(None, [customer.get("first_name", ""), customer.get("last_name", "")])).strip() or customer.get("name", "")
    customer_email = customer.get("email", "")
    shipping_address = order_data.get("shipping_address", {})
    shipping_name = shipping_address.get("name", "")
    shipping_address1 = shipping_address.get("address1", "")
    shipping_address2 = shipping_address.get("address2", "")
    shipping_city = shipping_address.get("city", "")
    shipping_province = shipping_address.get("province", "")
    shipping_country = shipping_address.get("country_code", "")
    shipping_zip = shipping_address.get("zip", "")
    shipping_phone = shipping_address.get("phone", "")
    is_shenzhen_order = bool(shenzhen_items)
    order_name = order_data.get("name", "")
    order_number = order_data.get("order_number", "")
    financial_status = order_data.get("financial_status", "")
    fulfillment_status = order_data.get("fulfillment_status", "")
    total_price = order_data.get("total_price", 0)
    currency = order_data.get("currency", "USD")
    shopify_note = order_data.get("note")
    shopify_note_attributes = order_data.get("note_attributes") or []
    created_at = order_data.get("created_at", "")
    if created_at:
        order_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    else:
        order_created_at = timezone.now()

    original_location = "shenzhen" if is_shenzhen_order else None
    original_location_raw = shenzhen_items[0]["fulfillment_location_raw"] if is_shenzhen_order and shenzhen_items else current_location_raw

    order_obj, created = ShopifyOrder.objects.get_or_create(
        installation=installation,
        shopify_order_id=order_id,
        defaults={
            "order_number": order_number,
            "order_name": order_name,
            "financial_status": financial_status,
            "fulfillment_status": fulfillment_status,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "shipping_name": shipping_name,
            "shipping_address1": shipping_address1,
            "shipping_address2": shipping_address2,
            "shipping_city": shipping_city,
            "shipping_province": shipping_province,
            "shipping_country": shipping_country,
            "shipping_zip": shipping_zip,
            "shipping_phone": shipping_phone,
            "total_price": total_price,
            "currency": currency,
            "order_created_at": order_created_at,
            "shopify_note": shopify_note,
            "shopify_note_attributes": shopify_note_attributes,
            "original_location_raw": original_location_raw,
            "current_location_raw": current_location_raw,
            "original_location": original_location,
            "current_location": current_location_normalized,
            "is_shenzhen_order": is_shenzhen_order,
            "last_order_synced_at": timezone.now(),
        },
    )

    if not created:
        protected_statuses = ["admin_confirmed", "pending_payment", "paid"]
        update_fields = {
            "current_location_raw": current_location_raw,
            "current_location": current_location_normalized,
            "financial_status": financial_status,
            "fulfillment_status": fulfillment_status,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "shipping_name": shipping_name,
            "shipping_address1": shipping_address1,
            "shipping_address2": shipping_address2,
            "shipping_city": shipping_city,
            "shipping_province": shipping_province,
            "shipping_country": shipping_country,
            "shipping_zip": shipping_zip,
            "shipping_phone": shipping_phone,
            "total_price": total_price,
            "currency": currency,
            "shopify_note": shopify_note,
            "shopify_note_attributes": shopify_note_attributes,
        }

        if order_obj.original_location == "shenzhen" and current_location_normalized not in {"shenzhen", "mixed"}:
            if order_obj.settlement_status not in protected_statuses:
                update_fields["settlement_status"] = "transferred"
                update_fields["is_shenzhen_order"] = False
                update_fields["transferred_at"] = timezone.now()
                update_fields["transfer_note"] = (
                    f"Order transferred from shenzhen to {current_location_normalized}."
                )
            else:
                update_fields["settlement_status"] = "exception"
                update_fields["is_shenzhen_order"] = False
                update_fields["transferred_at"] = timezone.now()
                update_fields["transfer_note"] = (
                    f"Order location changed from shenzhen to {current_location_normalized} after settlement confirmation."
                )
                exception_message = (
                    "Shopify location changed after settlement confirmation. Manual review required."
                )
                update_fields["warehouse_note"] = (
                    (order_obj.warehouse_note or "") + "\n" + exception_message
                ).strip()
                update_fields["cost_calculation_note"] = (
                    (order_obj.cost_calculation_note or "") + "\n" + exception_message
                ).strip()

        if order_obj.original_location is None and is_shenzhen_order:
            update_fields["original_location"] = "shenzhen"
            update_fields["original_location_raw"] = current_location_raw

        for field, value in update_fields.items():
            if getattr(order_obj, field) != value:
                setattr(order_obj, field, value)
        order_obj.last_order_synced_at = timezone.now()
        update_fields["last_order_synced_at"] = timezone.now()
        order_obj.save(update_fields=list(update_fields.keys()))

    return order_obj, created


def _match_shopify_product(order_obj, shopify_product_id, shopify_variant_id, sku):
    if shopify_variant_id:
        matched_product = ShopifyProduct.objects.filter(
            installation=order_obj.installation,
            shopify_variant_id=shopify_variant_id,
        ).first()
        if matched_product:
            return matched_product, "Matched by variant_id", "matched_by_variant_id"

    if shopify_product_id:
        matched_product = ShopifyProduct.objects.filter(
            installation=order_obj.installation,
            shopify_product_id=shopify_product_id,
        ).first()
        if matched_product:
            return matched_product, "Matched by product_id", "matched_by_product_id"

    if sku:
        matched_product = ShopifyProduct.objects.filter(
            installation=order_obj.installation,
            sku=sku,
        ).first()
        if matched_product:
            return matched_product, "Matched by sku", "matched_by_sku"

    return None, "No matched product; saved Shopify line item snapshot", "unmatched_variant_not_found"


def _order_item_has_model_field(field_name):
    return any(field.name == field_name for field in ShopifyOrderItem._meta.fields)


def _create_shopify_order_item(order_obj, line_item_id, defaults):
    if _order_item_has_model_field("match_note") and _order_item_has_model_field("match_status"):
        return ShopifyOrderItem.objects.create(
            order=order_obj,
            shopify_line_item_id=line_item_id,
            **defaults,
        )

    now = timezone.now()
    locked_product_cost_rmb = defaults.get("locked_product_cost_rmb")
    locked_shipping_cost_rmb = defaults.get("locked_shipping_cost_rmb")
    handling_fee_rmb = defaults.get("handling_fee_rmb") or 0
    total_cost_rmb = None
    if locked_product_cost_rmb is not None:
        total_cost_rmb = (
            Decimal(locked_product_cost_rmb) * defaults.get("quantity", 1)
            + Decimal(locked_shipping_cost_rmb or 0)
            - Decimal(handling_fee_rmb or 0)
        )

    table_name = ShopifyOrderItem._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {table_name} (
                order_id,
                shopify_line_item_id,
                shopify_product_id,
                shopify_variant_id,
                sku,
                product_title,
                variant_title,
                quantity,
                price,
                fulfillment_location,
                matched_product_id,
                locked_product_cost_rmb,
                locked_shipping_cost_rmb,
                handling_fee_rmb,
                total_cost_rmb,
                created_at,
                updated_at,
                match_note,
                match_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                order_obj.id,
                line_item_id,
                defaults.get("shopify_product_id"),
                defaults.get("shopify_variant_id"),
                defaults.get("sku"),
                defaults.get("product_title"),
                defaults.get("variant_title"),
                defaults.get("quantity"),
                defaults.get("price"),
                defaults.get("fulfillment_location"),
                defaults.get("matched_product").id if defaults.get("matched_product") else None,
                locked_product_cost_rmb,
                locked_shipping_cost_rmb,
                handling_fee_rmb,
                total_cost_rmb,
                now,
                now,
                defaults.get("match_note") or "Saved from Shopify line_items snapshot",
                defaults.get("match_status") or "unmatched_variant_not_found",
            ],
        )
    return ShopifyOrderItem.objects.get(order=order_obj, shopify_line_item_id=line_item_id)


def _update_order_item_match_note_if_empty(item_obj, match_note):
    if _order_item_has_model_field("match_note"):
        if not getattr(item_obj, "match_note", ""):
            item_obj.match_note = match_note
            item_obj.save(update_fields=["match_note"])
        return

    table_name = ShopifyOrderItem._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {table_name}
            SET match_note = %s
            WHERE id = %s AND (match_note IS NULL OR match_note = '')
            """,
            [match_note, item_obj.id],
        )


def _find_product_country_shipping_default(order_obj, shopify_variant_id):
    if not order_obj.shipping_country or not shopify_variant_id:
        return None
    shipping_default = ShenzhenProductCountryShippingDefault.objects.filter(
        country_code__iexact=order_obj.shipping_country,
        shopify_variant_id=shopify_variant_id,
    ).first()
    return shipping_default.default_shipping_cost_rmb if shipping_default else None


def _decimal_or_zero(value):
    return Decimal(value or 0)


def _item_product_cost_total(item):
    return _decimal_or_zero(item.locked_product_cost_rmb) * item.quantity


def _item_full_cost_total(item):
    return (
        _item_product_cost_total(item)
        + _decimal_or_zero(item.locked_shipping_cost_rmb)
        - _decimal_or_zero(item.handling_fee_rmb)
    )


def _package_total_cost(package):
    package_items = package.items.filter(fulfillment_location="shenzhen")
    product_cost = sum((_item_product_cost_total(item) for item in package_items), Decimal("0.00"))
    return product_cost + _decimal_or_zero(package.shipping_cost_rmb) - _decimal_or_zero(package.ordering_cost_rmb)


def _package_level_order_totals(order_obj):
    shenzhen_items = list(order_obj.order_items.select_related("package").filter(fulfillment_location="shenzhen"))
    package_ids = {item.package_id for item in shenzhen_items if item.package_id}
    packages = list(order_obj.packages.filter(id__in=package_ids))
    unpackaged_items = [item for item in shenzhen_items if not item.package_id]
    product_cost = sum((_item_product_cost_total(item) for item in shenzhen_items), Decimal("0.00"))
    shipping_cost = (
        sum((_decimal_or_zero(package.shipping_cost_rmb) for package in packages), Decimal("0.00"))
        + sum((_decimal_or_zero(item.locked_shipping_cost_rmb) for item in unpackaged_items), Decimal("0.00"))
    )
    ordering_cost = (
        sum((_decimal_or_zero(package.ordering_cost_rmb) for package in packages), Decimal("0.00"))
        + sum((_decimal_or_zero(item.handling_fee_rmb) for item in unpackaged_items), Decimal("0.00"))
    )
    package_total = sum((_package_total_cost(package) for package in packages), Decimal("0.00"))
    unpackaged_total = sum((_item_full_cost_total(item) for item in unpackaged_items), Decimal("0.00"))
    return {
        "product_cost": product_cost,
        "shipping_cost": shipping_cost,
        "ordering_cost": ordering_cost,
        "total_cost": package_total + unpackaged_total,
    }


def allocate_package_costs(order_obj):
    packages_processed = 0
    skipped_packages = 0

    packages = list(order_obj.packages.all().order_by("package_no"))

    for package in packages:
        package_items = list(
            package.items.filter(fulfillment_location="shenzhen").order_by("id")
        )
        if not package_items:
            skipped_packages += 1
            continue

        packages_processed += 1

    totals = _package_level_order_totals(order_obj)
    order_obj.order_shipping_cost_rmb = totals["shipping_cost"]
    order_obj.order_handling_fee_rmb = totals["ordering_cost"]
    order_obj.total_locked_cost_rmb = totals["total_cost"]
    order_obj.cost_calculated_at = timezone.now()
    order_obj.cost_calculation_note = (
        "使用混合结算重算订单总成本：有包裹的商品按包裹费用计算，未分配包裹的商品按商品行费用计算。"
    )
    order_obj.save(update_fields=[
        "order_shipping_cost_rmb",
        "order_handling_fee_rmb",
        "total_locked_cost_rmb",
        "cost_calculated_at",
        "cost_calculation_note",
    ])
    return {
        "packages_processed": packages_processed,
        "skipped_packages": skipped_packages,
    }


def _process_shenzhen_order_items(order_obj, order_items):
    created_count = 0
    updated_count = 0
    for item_data in order_items:
        line_item = item_data["line_item"]
        fulfillment_location = item_data.get("fulfillment_location")
        line_item_id = line_item.get("id")
        if not line_item_id:
            continue
        shopify_product_id = line_item.get("product_id")
        shopify_variant_id = line_item.get("variant_id")
        sku = line_item.get("sku", "")
        product_title = line_item.get("name", "")
        variant_title = line_item.get("variant_title", "")
        quantity = line_item.get("quantity", 1)
        price = line_item.get("price", 0)
        locked_product_cost_rmb = None
        locked_shipping_cost_rmb = None
        matched_product, match_note, match_status = _match_shopify_product(
            order_obj,
            shopify_product_id,
            shopify_variant_id,
            sku,
        )

        if matched_product:
            locked_product_cost_rmb = matched_product.product_cost_rmb
        weight_kg = matched_product.weight_kg if matched_product else None
        length_cm = matched_product.length_cm if matched_product else None
        width_cm = matched_product.width_cm if matched_product else None
        height_cm = matched_product.height_cm if matched_product else None
        volume_weight_kg = matched_product.volume_weight_kg if matched_product else None
        default_shipping_cost = _find_product_country_shipping_default(
            order_obj,
            shopify_variant_id,
        )
        if default_shipping_cost is not None:
            locked_shipping_cost_rmb = default_shipping_cost

        defaults = {
            "shopify_product_id": shopify_product_id,
            "shopify_variant_id": shopify_variant_id,
            "sku": sku,
            "product_title": product_title,
            "variant_title": variant_title,
            "quantity": quantity,
            "price": price,
            "fulfillment_location": fulfillment_location,
            "matched_product": matched_product,
            "locked_product_cost_rmb": locked_product_cost_rmb,
            "locked_shipping_cost_rmb": locked_shipping_cost_rmb,
            "handling_fee_rmb": 0,
            "weight_kg": weight_kg,
            "length_cm": length_cm,
            "width_cm": width_cm,
            "height_cm": height_cm,
            "volume_weight_kg": volume_weight_kg,
            "match_note": match_note,
            "match_status": match_status,
        }

        item_obj = ShopifyOrderItem.objects.filter(
            order=order_obj,
            shopify_line_item_id=line_item_id,
        ).first()
        if item_obj is None:
            item_obj = _create_shopify_order_item(order_obj, line_item_id, defaults)
            created = True
        else:
            created = False

        if created:
            created_count += 1
        else:
            _update_order_item_match_note_if_empty(item_obj, match_note)
            protected_statuses = ["cost_confirmed", "admin_confirmed", "pending_payment", "paid"]
            update_fields = {
                "shopify_product_id": shopify_product_id,
                "shopify_variant_id": shopify_variant_id,
                "sku": sku,
                "product_title": product_title,
                "variant_title": variant_title,
                "price": price,
                "fulfillment_location": fulfillment_location,
            }
            if order_obj.settlement_status not in protected_statuses:
                update_fields["quantity"] = quantity
            if matched_product and not item_obj.matched_product:
                update_fields["matched_product"] = matched_product
                if order_obj.settlement_status not in protected_statuses:
                    update_fields["locked_product_cost_rmb"] = locked_product_cost_rmb
            if matched_product:
                for field, value in {
                    "locked_product_cost_rmb": locked_product_cost_rmb,
                    "weight_kg": weight_kg,
                    "length_cm": length_cm,
                    "width_cm": width_cm,
                    "height_cm": height_cm,
                    "volume_weight_kg": volume_weight_kg,
                }.items():
                    current_value = getattr(item_obj, field)
                    if value is not None and (current_value is None or current_value == 0):
                        update_fields[field] = value
            if (
                order_obj.settlement_status not in protected_statuses
                and default_shipping_cost is not None
                and (not item_obj.locked_shipping_cost_rmb or item_obj.locked_shipping_cost_rmb <= 0)
            ):
                update_fields["locked_shipping_cost_rmb"] = default_shipping_cost

            changed_fields = []
            for field, value in update_fields.items():
                if getattr(item_obj, field) != value:
                    setattr(item_obj, field, value)
                    changed_fields.append(field)
            if changed_fields:
                item_obj.save(update_fields=changed_fields)
                updated_count += 1
    return created_count, updated_count


def _build_order_item_snapshots(line_items, fulfillment_orders):
    fulfillment_locations = {}
    fulfillment_location_raws = {}

    for fulfillment_order in fulfillment_orders:
        assigned_location = fulfillment_order.get("assigned_location", {})
        location_name = assigned_location.get("name", "")
        normalized = normalize_location_name(location_name)
        for fulfillment_item in fulfillment_order.get("line_items", []):
            line_item_id = fulfillment_item.get("line_item_id")
            if line_item_id is None:
                continue
            fulfillment_locations[line_item_id] = normalized
            fulfillment_location_raws[line_item_id] = location_name

    snapshots = []
    for line_item in line_items:
        line_item_id = line_item.get("id")
        snapshots.append(
            {
                "line_item": line_item,
                "fulfillment_location": fulfillment_locations.get(line_item_id),
                "fulfillment_location_raw": fulfillment_location_raws.get(line_item_id, ""),
            }
        )
    return snapshots


def _parse_shopify_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def sync_products_for_installation(installation):
    shop_domain = installation.shop
    access_token = installation.access_token
    api_url = f"https://{shop_domain}/admin/api/2024-01/products.json"
    page_info = None
    seen_page_info = set()
    created_count = 0
    updated_count = 0
    skipped_no_sku = 0
    total_variants = 0
    api_status_code = None
    api_response_preview = None
    product_count_first_page = 0
    is_first_page = True

    while True:
        params = {"limit": 250}
        if page_info:
            params["page_info"] = page_info

        response = shopify_get(api_url, access_token, params=params, timeout=30)
        api_status_code = response.status_code
        api_response_preview = response.text[:1000]
        data = response.json()
        products = data.get("products", [])
        if is_first_page:
            product_count_first_page = len(products)
            is_first_page = False

        for product in products:
            product_id = product.get("id")
            product_title = product.get("title", "")
            handle = product.get("handle", "")
            vendor = product.get("vendor", "")
            product_type = product.get("product_type", "")
            status = product.get("status", "active")
            shopify_product_created_at = _parse_shopify_datetime(product.get("created_at"))
            shopify_product_updated_at = _parse_shopify_datetime(product.get("updated_at"))
            shopify_published_at = _parse_shopify_datetime(product.get("published_at"))
            image = product.get("image")
            image_url = image.get("src", "") if image else ""
            variants = product.get("variants", [])
            for variant in variants:
                total_variants += 1
                variant_id = variant.get("id")
                if not variant_id:
                    continue
                sku = variant.get("sku", "")
                variant_title = variant.get("title", "")
                price = variant.get("price", 0)
                inventory_quantity = variant.get("inventory_quantity", 0)
                if not sku:
                    skipped_no_sku += 1
                obj, created = ShopifyProduct.objects.update_or_create(
                    installation=installation,
                    shopify_variant_id=variant_id,
                    defaults={
                        "shopify_product_id": product_id,
                        "product_title": product_title,
                        "variant_title": variant_title,
                        "sku": sku,
                        "handle": handle,
                        "vendor": vendor,
                        "product_type": product_type,
                        "status": status,
                        "image_url": image_url,
                        "price": price,
                        "inventory_quantity": inventory_quantity,
                        "shopify_product_created_at": shopify_product_created_at,
                        "shopify_product_updated_at": shopify_product_updated_at,
                        "shopify_published_at": shopify_published_at,
                    },
                )
                if created:
                    created_count += 1
                else:
                    # 只更新非人工字段
                    update_fields = []
                    if obj.shopify_product_id != product_id:
                        obj.shopify_product_id = product_id
                        update_fields.append("shopify_product_id")
                    if obj.product_title != product_title:
                        obj.product_title = product_title
                        update_fields.append("product_title")
                    if obj.variant_title != variant_title:
                        obj.variant_title = variant_title
                        update_fields.append("variant_title")
                    if obj.sku != sku:
                        obj.sku = sku
                        update_fields.append("sku")
                    if obj.handle != handle:
                        obj.handle = handle
                        update_fields.append("handle")
                    if obj.vendor != vendor:
                        obj.vendor = vendor
                        update_fields.append("vendor")
                    if obj.product_type != product_type:
                        obj.product_type = product_type
                        update_fields.append("product_type")
                    if obj.status != status:
                        obj.status = status
                        update_fields.append("status")
                    if obj.image_url != image_url:
                        obj.image_url = image_url
                        update_fields.append("image_url")
                    if obj.price != price:
                        obj.price = price
                        update_fields.append("price")
                    if obj.inventory_quantity != inventory_quantity:
                        obj.inventory_quantity = inventory_quantity
                        update_fields.append("inventory_quantity")
                    if obj.shopify_product_created_at != shopify_product_created_at:
                        obj.shopify_product_created_at = shopify_product_created_at
                        update_fields.append("shopify_product_created_at")
                    if obj.shopify_product_updated_at != shopify_product_updated_at:
                        obj.shopify_product_updated_at = shopify_product_updated_at
                        update_fields.append("shopify_product_updated_at")
                    if obj.shopify_published_at != shopify_published_at:
                        obj.shopify_published_at = shopify_published_at
                        update_fields.append("shopify_published_at")
                    if update_fields:
                        obj.save(update_fields=update_fields)
                        updated_count += 1

        link_header = response.headers.get("Link", "")
        next_page_info = get_next_page_info_from_link_header(link_header)
        if next_page_info:
            if next_page_info in seen_page_info:
                print("Warning: repeated Shopify products page_info detected; stopping pagination.")
                break
            seen_page_info.add(next_page_info)
            page_info = next_page_info
            continue
        break

    return {
        "success": True,
        "created": created_count,
        "updated": updated_count,
        "skipped_no_sku": skipped_no_sku,
        "total_variants": total_variants,
        "api_status_code": api_status_code,
        "api_response_preview": api_response_preview,
        "product_count_first_page": product_count_first_page,
        "shop_domain": shop_domain,
    }


def sync_shenzhen_orders_for_installation(installation, days=60):
    shop_domain = installation.shop
    access_token = installation.access_token
    start_date = (timezone.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    result = {
        "success": True,
        "created_orders": 0,
        "updated_orders": 0,
        "created_items": 0,
        "updated_items": 0,
        "skipped_non_shenzhen": 0,
        "transferred_orders": 0,
        "updated_tracking": 0,
        "auto_marked_warehouse_fulfilled": 0,
        "detected_tracking_count": 0,
        "errors": [],
        "checked_orders": 0,
        "skipped_missing_ship_from_china_tag": 0,
        "skipped_no_shenzhen_items": 0,
    }

    for order, data in fetch_shopify_orders(shop_domain, access_token, start_date):
        result["checked_orders"] += 1
        order_id = order.get("id")
        if not order_id:
            continue
        has_china_tag = has_ship_from_china_tag(order)
        try:
            fulfillment_orders = fetch_order_fulfillment_orders(shop_domain, order_id, access_token)
        except requests.exceptions.RequestException as exc:
            result["errors"].append(f"fulfillment_orders_failed_{order_id}: {exc}")
            continue

        shenzhen_items = []
        line_items = order.get("line_items", [])

        for fo in fulfillment_orders:
            assigned_location = fo.get("assigned_location", {})
            location_name = assigned_location.get("name", "")
            normalized = normalize_location_name(location_name)
            if normalized == "shenzhen":
                for fo_item in fo.get("line_items", []):
                    line_item_id = fo_item.get("line_item_id")
                    for item in line_items:
                        if item.get("id") == line_item_id:
                            shenzhen_items.append(
                                {
                                    "line_item": item,
                                    "fulfillment_location": normalized,
                                    "fulfillment_location_raw": location_name,
                                }
                            )
                            break

        current_location_normalized, current_location_raw = summarize_current_locations(fulfillment_orders)
        existing_order = ShopifyOrder.objects.filter(
            installation=installation,
            shopify_order_id=order_id,
        ).first()

        if not has_china_tag:
            result["skipped_missing_ship_from_china_tag"] += 1
            if not existing_order:
                result["skipped_non_shenzhen"] += 1
            continue

        if not shenzhen_items:
            result["skipped_no_shenzhen_items"] += 1
            if not existing_order:
                result["skipped_non_shenzhen"] += 1
            continue

        order_obj, created = _process_shenzhen_order(
            installation,
            order,
            shenzhen_items,
            current_location_normalized,
            current_location_raw,
        )
        if created:
            result["created_orders"] += 1
        else:
            if order_obj.settlement_status == "transferred":
                result["transferred_orders"] += 1
            else:
                result["updated_orders"] += 1

        items_created, items_updated = _process_shenzhen_order_items(order_obj, shenzhen_items)
        result["created_items"] += items_created
        result["updated_items"] += items_updated

        try:
            fulfillments = fetch_order_fulfillments(shop_domain, order_id, access_token)
            updated_tracking, auto_marked, detected_count = _apply_fulfillment_updates(
                order_obj, fulfillment_orders, fulfillments, shop_domain, access_token
            )
            if updated_tracking:
                result["updated_tracking"] += 1
            if auto_marked:
                result["auto_marked_warehouse_fulfilled"] += 1
            result["detected_tracking_count"] += detected_count
        except requests.exceptions.RequestException as exc:
            result["errors"].append(f"fulfillments_failed_{order_id}: {exc}")

    return result


def _find_applicable_shipping_rule(country_code, total_actual_weight_kg, max_length_cm, max_width_cm, max_height_cm):
    rules = ShippingCostRule.objects.filter(
        country_code__iexact=country_code,
        is_active=True,
    ).order_by("priority")

    for rule in rules:
        if rule.min_weight_kg is not None and total_actual_weight_kg < rule.min_weight_kg:
            continue
        if rule.max_weight_kg is not None and total_actual_weight_kg > rule.max_weight_kg:
            continue
        if rule.max_length_cm is not None and max_length_cm is not None and max_length_cm > rule.max_length_cm:
            continue
        if rule.max_width_cm is not None and max_width_cm is not None and max_width_cm > rule.max_width_cm:
            continue
        if rule.max_height_cm is not None and max_height_cm is not None and max_height_cm > rule.max_height_cm:
            continue
        return rule
    return None


def _legacy_recalculate_order_shipping_cost_by_rule(order_obj, force=False):
    order_items = list(
        order_obj.order_items.select_related('matched_product').filter(
            fulfillment_location="shenzhen"
        )
    )
    if not order_items:
        order_obj.cost_calculation_note = "订单无 item，无法计算运费。"
        order_obj.save(update_fields=["cost_calculation_note"])
        return False
    if not order_obj.shipping_country:
        order_obj.cost_calculation_note = "缺少收件国家，无法计算运费。"
        order_obj.save(update_fields=["cost_calculation_note"])
        return False

    total_actual_weight = 0
    total_volume = 0
    max_length = 0
    max_width = 0
    max_height = 0
    missing_products = []
    missing_costs = []

    for item in order_items:
        product = item.matched_product
        if not product:
            continue
        if product.product_cost_rmb is None:
            missing_costs.append(item.sku or item.product_title)
        if product.weight_kg is None or product.length_cm is None or product.width_cm is None or product.height_cm is None:
            missing_products.append(item.sku or item.product_title)
            continue
        item_weight = float(product.weight_kg) * item.quantity
        total_actual_weight += item_weight
        total_volume += float(product.length_cm) * float(product.width_cm) * float(product.height_cm) * item.quantity
        max_length = max(max_length, float(product.length_cm))
        max_width = max(max_width, float(product.width_cm))
        max_height = max(max_height, float(product.height_cm))

    if missing_products or missing_costs:
        note_parts = []
        if missing_costs:
            note_parts.append(f"以下商品缺少成本：{', '.join(missing_costs)}")
        if missing_products:
            note_parts.append(f"以下商品缺少重量/尺寸：{', '.join(missing_products)}")
        order_obj.cost_calculation_note = "; ".join(note_parts)
        order_obj.save(update_fields=["cost_calculation_note"])
        return False

    rule = _find_applicable_shipping_rule(
        order_obj.shipping_country,
        total_actual_weight,
        max_length,
        max_width,
        max_height,
    )
    if not rule:
        order_obj.cost_calculation_note = "未找到可用运费规则。"
        order_obj.save(update_fields=["cost_calculation_note"])
        return False

    total_volume_weight = total_volume / float(rule.volume_divisor)
    chargeable_weight = max(total_actual_weight, total_volume_weight)
    order_shipping_cost = chargeable_weight * float(rule.price_per_kg_rmb) + float(rule.base_fee_rmb)
    order_handling_fee = float(rule.handling_fee_rmb)

    order_obj.total_actual_weight_kg = total_actual_weight
    order_obj.total_volume_weight_kg = total_volume_weight
    order_obj.chargeable_weight_kg = chargeable_weight
    order_obj.order_shipping_cost_rmb = order_shipping_cost
    order_obj.order_handling_fee_rmb = order_handling_fee
    order_obj.cost_calculated_at = timezone.now()
    order_obj.cost_calculation_note = f"使用规则 {rule.name}({rule.country_code}) 计算。"

    total_weight = total_actual_weight if total_actual_weight > 0 else sum(item.quantity for item in order_items)
    order_shipping_cost = float(order_shipping_cost)
    order_handling_fee = float(order_handling_fee)

    allocated_shipping = 0
    allocated_handling = 0

    for item in order_items:
        product = item.matched_product
        item_weight = float(product.weight_kg) * item.quantity
        share = item_weight / total_weight if total_weight > 0 else 1 / len(order_items)
        item_locked_shipping = order_shipping_cost * share
        item_locked_handling = order_handling_fee * share
        item.locked_shipping_cost_rmb = item_locked_shipping
        item.handling_fee_rmb = item_locked_handling
        item.save()
        allocated_shipping += item_locked_shipping
        allocated_handling += item_locked_handling

    # 修正分配误差
    shipping_diff = order_shipping_cost - allocated_shipping
    handling_diff = order_handling_fee - allocated_handling
    if order_items:
        first_item = order_items[0]
        first_item.locked_shipping_cost_rmb = float(first_item.locked_shipping_cost_rmb or 0) + shipping_diff
        first_item.handling_fee_rmb = float(first_item.handling_fee_rmb or 0) + handling_diff
        first_item.save()

    total_product_cost = sum((float(item.locked_product_cost_rmb or 0) * item.quantity) for item in order_items)
    order_obj.total_locked_cost_rmb = total_product_cost + order_shipping_cost - order_handling_fee
    order_obj.save(update_fields=[
        "total_actual_weight_kg",
        "total_volume_weight_kg",
        "chargeable_weight_kg",
        "order_shipping_cost_rmb",
        "order_handling_fee_rmb",
        "total_locked_cost_rmb",
        "cost_calculated_at",
        "cost_calculation_note",
    ])
    return True


def _legacy_recalculate_order_shipping_cost_by_order_default(order_obj, force=False):
    order_items = list(
        order_obj.order_items.select_related("matched_product").filter(
            fulfillment_location="shenzhen"
        )
    )
    if not order_items:
        order_obj.cost_calculation_note = "订单无深圳仓 item，无法计算运费。"
        order_obj.save(update_fields=["cost_calculation_note"])
        return False

    shipping_cost = Decimal(order_obj.order_shipping_cost_rmb or 0)
    if shipping_cost <= 0 and order_obj.shipping_country:
        shipping_default = ShenzhenCountryShippingDefault.objects.filter(
            country_code__iexact=order_obj.shipping_country
        ).first()
        if shipping_default:
            shipping_cost = shipping_default.default_shipping_cost_rmb
            order_obj.order_shipping_cost_rmb = shipping_cost

    handling_fee = Decimal(order_obj.order_handling_fee_rmb or 0)
    missing_costs = []
    missing_package_costs = []
    for item in order_items:
        product = item.matched_product
        if not product:
            missing_costs.append(item.sku or item.product_title)
            continue
        if item.locked_product_cost_rmb is None and product.product_cost_rmb is not None:
            item.locked_product_cost_rmb = product.product_cost_rmb
        if item.locked_product_cost_rmb is None:
            missing_costs.append(item.sku or item.product_title)

    order_obj.total_actual_weight_kg = None
    order_obj.total_volume_weight_kg = None
    order_obj.chargeable_weight_kg = None
    order_obj.order_shipping_cost_rmb = shipping_cost
    order_obj.order_handling_fee_rmb = handling_fee
    order_obj.cost_calculated_at = timezone.now()
    if shipping_cost > 0:
        order_obj.cost_calculation_note = "使用人工输入或国家默认深圳仓国际运费计算。"
    else:
        order_obj.cost_calculation_note = "未填写深圳仓国际运费，也未找到该国家默认运费；本次按 0 RMB 运费计算。"
    if missing_costs:
        order_obj.cost_calculation_note += f" 以下商品缺少产品成本：{', '.join(missing_costs)}。"

    item_count = len(order_items)
    shipping_share = (shipping_cost / item_count).quantize(Decimal("0.01"))
    handling_share = (handling_fee / item_count).quantize(Decimal("0.01"))
    allocated_shipping = Decimal("0.00")
    allocated_handling = Decimal("0.00")

    for index, item in enumerate(order_items):
        if index == item_count - 1:
            item_shipping = shipping_cost - allocated_shipping
            item_handling = handling_fee - allocated_handling
        else:
            item_shipping = shipping_share
            item_handling = handling_share
        item.locked_shipping_cost_rmb = item_shipping
        item.handling_fee_rmb = item_handling
        item.save()
        allocated_shipping += item_shipping
        allocated_handling += item_handling

    total_product_cost = sum(
        (Decimal(item.locked_product_cost_rmb or 0) * item.quantity)
        for item in order_items
    )
    order_obj.total_locked_cost_rmb = total_product_cost + shipping_cost - handling_fee
    order_obj.save(update_fields=[
        "total_actual_weight_kg",
        "total_volume_weight_kg",
        "chargeable_weight_kg",
        "order_shipping_cost_rmb",
        "order_handling_fee_rmb",
        "total_locked_cost_rmb",
        "cost_calculated_at",
        "cost_calculation_note",
    ])
    return not missing_costs


def recalculate_order_shipping_cost(order_obj, force=False):
    order_items = list(
        order_obj.order_items.select_related("matched_product", "package").filter(
            fulfillment_location="shenzhen"
        )
    )
    if not order_items:
        order_obj.cost_calculation_note = "订单无深圳仓 item，无法计算运费。"
        order_obj.save(update_fields=["cost_calculation_note"])
        return False

    missing_costs = []
    missing_package_costs = []
    for item in order_items:
        product = item.matched_product
        if product and item.locked_product_cost_rmb is None and product.product_cost_rmb is not None:
            item.locked_product_cost_rmb = product.product_cost_rmb
        if item.locked_product_cost_rmb is None:
            missing_costs.append(item.sku or item.product_title)
        if item.package_id:
            if item.package.shipping_cost_rmb is None or item.package.shipping_cost_rmb <= 0:
                missing_package_costs.append(f"Package {item.package.package_no} 缺少包裹运费")
            if item.package.ordering_cost_rmb is None:
                missing_package_costs.append(f"Package {item.package.package_no} 缺少包裹拍单成本")
        else:
            if item.locked_shipping_cost_rmb is None or item.locked_shipping_cost_rmb <= 0:
                missing_package_costs.append(f"{item.sku or item.product_title} 缺少商品行运费")
            if item.handling_fee_rmb is None:
                missing_package_costs.append(f"{item.sku or item.product_title} 缺少商品行拍单成本")

        item.save()

    totals = _package_level_order_totals(order_obj)
    order_obj.total_actual_weight_kg = None
    order_obj.total_volume_weight_kg = None
    order_obj.chargeable_weight_kg = None
    order_obj.order_shipping_cost_rmb = totals["shipping_cost"]
    order_obj.order_handling_fee_rmb = totals["ordering_cost"]
    order_obj.total_locked_cost_rmb = totals["total_cost"]
    order_obj.cost_calculated_at = timezone.now()

    notes = ["使用混合结算重算：有包裹的商品按包裹费用计算，未分配包裹的商品按商品行费用计算。"]
    if missing_costs:
        notes.append(f"以下商品缺少产品成本：{', '.join(missing_costs)}。")
    if missing_package_costs:
        notes.append(f"以下包裹信息不完整：{'; '.join(missing_package_costs)}。")
    order_obj.cost_calculation_note = " ".join(notes)
    order_obj.save(update_fields=[
        "total_actual_weight_kg",
        "total_volume_weight_kg",
        "chargeable_weight_kg",
        "order_shipping_cost_rmb",
        "order_handling_fee_rmb",
        "total_locked_cost_rmb",
        "cost_calculated_at",
        "cost_calculation_note",
    ])
    return not missing_costs and not missing_package_costs


def update_shenzhen_tracking_for_installation(installation):
    shop_domain = installation.shop
    access_token = installation.access_token
    orders = ShopifyOrder.objects.filter(
        models.Q(current_location="shenzhen") | models.Q(is_shenzhen_order=True)
    ).exclude(settlement_status="paid")

    result = {
        "success": True,
        "updated_tracking": 0,
        "auto_marked_warehouse_fulfilled": 0,
        "skipped_paid_orders": ShopifyOrder.objects.filter(
            models.Q(current_location="shenzhen") | models.Q(is_shenzhen_order=True),
            settlement_status="paid",
        ).count(),
        "detected_tracking_count": 0,
        "errors": [],
        "checked_orders": orders.count(),
    }

    for order_obj in orders:
        try:
            fulfillment_orders = fetch_order_fulfillment_orders(shop_domain, order_obj.shopify_order_id, access_token)
            fulfillments = fetch_order_fulfillments(shop_domain, order_obj.shopify_order_id, access_token)
            updated_tracking, auto_marked, detected_count = _apply_fulfillment_updates(
                order_obj, fulfillment_orders, fulfillments, shop_domain, access_token
            )
            if updated_tracking:
                result["updated_tracking"] += 1
            if auto_marked:
                result["auto_marked_warehouse_fulfilled"] += 1
            result["detected_tracking_count"] += detected_count
        except requests.exceptions.RequestException as exc:
            result["errors"].append(f"order_{order_obj.shopify_order_id}: {exc}")

    return result
