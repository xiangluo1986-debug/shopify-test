from datetime import datetime, timedelta, timezone as datetime_timezone

import requests
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from shopify_sync.models import ShopifyInstallation, ShopifyOrder
from shopify_sync.review_request_workbench import (
    run_trustpilot_auto_queue_refresh_after_shopify_order_sync,
)
from shopify_sync.sync_helpers import (
    ORDER_SYNC_TASK_NAMES,
    ShopifyRateLimitError,
    _build_order_item_snapshots,
    _process_shenzhen_order_items,
    fetch_shopify_order_pages,
    fetch_order_fulfillment_orders,
    run_shopify_sync_task,
    summarize_current_locations,
)


REVIEW_REQUEST_ORDER_SYNC_TASK_NAMES = [
    "orders_review_request_3",
    "orders_review_request_60",
    "orders_review_request_manual",
]


class Command(BaseCommand):
    help = (
        "Sync all Shopify order rows needed by Review Request candidate scanning. "
        "Default mode is dry-run; use --apply-local to write local ShopifyOrder rows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--shop",
            dest="shop",
            default="kidstoylover.myshopify.com",
            help="Shop domain to sync (default: kidstoylover.myshopify.com)",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=60,
            help="Number of past days to fetch orders for Review Request coverage.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview only. This is also the default unless --apply-local is present.",
        )
        parser.add_argument(
            "--apply-local",
            action="store_true",
            help="Persist fetched Shopify order rows to the local database.",
        )
        parser.add_argument(
            "--request-delay",
            type=float,
            default=1.0,
            help="Seconds to wait after successful Shopify read requests (default: 1.0).",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            default=None,
            help="Stop after this many Shopify order pages. Useful for limited tests.",
        )
        parser.add_argument(
            "--stop-on-429",
            action="store_true",
            help="Stop on the first Shopify 429 instead of waiting through retries.",
        )
        parser.add_argument(
            "--sync-line-items",
            action="store_true",
            help="Also store local ShopifyOrderItem snapshots using the existing order-item model.",
        )
        parser.add_argument(
            "--skip-auto-refresh",
            action="store_true",
            help="Do not run the local Trustpilot queue refresh after a successful local apply.",
        )
        parser.add_argument(
            "--task-name",
            dest="task_name",
            default=None,
            help="Sync state task name. Defaults to orders_review_request_3, orders_review_request_60, or orders_review_request_manual.",
        )

    def handle(self, *args, **options):
        shop = options["shop"]
        days = int(options["days"])
        if days <= 0:
            raise CommandError("--days must be greater than 0")
        request_delay = float(options["request_delay"])
        if request_delay < 0:
            raise CommandError("--request-delay must be zero or greater")
        max_pages = options["max_pages"]
        if max_pages is not None and max_pages <= 0:
            raise CommandError("--max-pages must be greater than 0 when provided")
        dry_run = options["dry_run"] or not options["apply_local"]
        task_name = options["task_name"] or _default_task_name(days)

        try:
            installation = ShopifyInstallation.objects.get(shop=shop)
        except ShopifyInstallation.DoesNotExist:
            raise CommandError(f"Shopify installation not found for {shop}")

        def sync_func():
            return sync_review_request_orders_for_installation(
                installation,
                days=days,
                dry_run=dry_run,
                sync_line_items=options["sync_line_items"],
                request_delay=request_delay,
                max_pages=max_pages,
                stop_on_429=options["stop_on_429"],
                progress_callback=self.stdout.write,
            )

        if dry_run:
            result = sync_func()
        else:
            task_result = run_shopify_sync_task(
                task_name,
                sync_func,
                conflict_task_names=ORDER_SYNC_TASK_NAMES + REVIEW_REQUEST_ORDER_SYNC_TASK_NAMES,
            )
            if task_result.get("skipped"):
                self.stdout.write(self.style.WARNING("Review Request order sync skipped."))
                self.stdout.write(task_result.get("reason", ""))
                return
            result = task_result["result"]

        refresh_result = {}
        if not dry_run and not options["skip_auto_refresh"]:
            try:
                refresh_result = run_trustpilot_auto_queue_refresh_after_shopify_order_sync()
            except Exception as exc:
                refresh_result = {
                    "last_auto_refresh_status": "auto_refresh_failed_non_blocking",
                    "last_auto_refresh_error": f"{exc.__class__.__name__}",
                }

        self.stdout.write(self.style.SUCCESS("Review Request Shopify order sync completed."))
        self.stdout.write(f"Mode: {'dry-run' if dry_run else 'apply-local'}")
        self.stdout.write(f"Window days: {days}")
        self.stdout.write(f"Sync window start: {result['window_start']}")
        self.stdout.write(f"Sync window end: {result['window_end']}")
        self.stdout.write(f"Pages fetched: {result['pages_fetched']}")
        self.stdout.write(f"Max pages: {result['max_pages'] or 'none'}")
        self.stdout.write(f"Stopped by max pages: {result['stopped_by_max_pages']}")
        self.stdout.write(f"Request delay seconds: {result['request_delay_seconds']:.1f}")
        self.stdout.write(f"Rate-limit retry events: {result['rate_limit_retry_events']}")
        self.stdout.write(f"Temporary error retry events: {result['temporary_error_retry_events']}")
        self.stdout.write(f"Backoff sleep seconds: {result['backoff_sleep_seconds']:.1f}")
        self.stdout.write(f"Rate-limit stopped: {result['rate_limit_stopped']}")
        self.stdout.write(f"Checked orders: {result['checked_orders']}")
        self.stdout.write(f"Would create orders: {result['would_create_orders']}")
        self.stdout.write(f"Would update orders: {result['would_update_orders']}")
        self.stdout.write(f"Created orders: {result['created_orders']}")
        self.stdout.write(f"Updated orders: {result['updated_orders']}")
        self.stdout.write(f"Total saved/updated: {result['created_orders'] + result['updated_orders']}")
        self.stdout.write(f"Fulfillment orders checked: {result['fulfillment_orders_checked']}")
        self.stdout.write(f"Line items seen: {result['line_items_seen']}")
        self.stdout.write(f"Created items: {result['created_items']}")
        self.stdout.write(f"Updated items: {result['updated_items']}")
        self.stdout.write(f"Shopify writes performed: False")
        self.stdout.write(f"Gmail actions performed: False")
        if refresh_result:
            self.stdout.write(
                "Trustpilot queue auto refresh: "
                f"{refresh_result.get('last_auto_refresh_status') or 'unknown'}"
            )
        if result["errors"]:
            self.stderr.write(self.style.WARNING("Errors encountered:"))
            for error in result["errors"]:
                self.stderr.write(f"- {error}")


def _default_task_name(days):
    if days <= 3:
        return "orders_review_request_3"
    if days >= 60:
        return "orders_review_request_60"
    return "orders_review_request_manual"


def sync_review_request_orders_for_installation(
    installation,
    days=60,
    dry_run=True,
    sync_line_items=False,
    request_delay=1.0,
    max_pages=None,
    stop_on_429=False,
    progress_callback=None,
):
    shop_domain = installation.shop
    access_token = installation.access_token
    request_delay = max(float(request_delay or 0), 0)
    window_end = timezone.now()
    window_start = window_end - timedelta(days=days)
    start_date = window_start.strftime("%Y-%m-%d")
    result = {
        "success": True,
        "dry_run": dry_run,
        "window_days": days,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "pages_fetched": 0,
        "max_pages": max_pages,
        "stopped_by_max_pages": False,
        "request_delay_seconds": request_delay,
        "stop_on_429": stop_on_429,
        "rate_limit_stopped": False,
        "rate_limit_retry_events": 0,
        "temporary_error_retry_events": 0,
        "backoff_sleep_seconds": 0.0,
        "checked_orders": 0,
        "would_create_orders": 0,
        "would_update_orders": 0,
        "created_orders": 0,
        "updated_orders": 0,
        "fulfillment_orders_checked": 0,
        "line_items_seen": 0,
        "created_items": 0,
        "updated_items": 0,
        "shopify_api_read_only": True,
        "shopify_write_performed": False,
        "gmail_action_performed": False,
        "errors": [],
    }

    def emit_progress(message):
        if progress_callback:
            progress_callback(message)

    def record_retry(event):
        if event.get("status_code") == 429:
            result["rate_limit_retry_events"] += 1
        else:
            result["temporary_error_retry_events"] += 1
        result["backoff_sleep_seconds"] += float(event.get("delay_seconds") or 0)

    emit_progress(
        "Sync window: "
        f"{window_start.isoformat()} through {window_end.isoformat()}; "
        f"request_delay={request_delay:.1f}s; max_pages={max_pages or 'none'}; "
        f"mode={'dry-run' if dry_run else 'apply-local'}."
    )

    stop_requested = False
    try:
        page_iter = fetch_shopify_order_pages(
            shop_domain,
            access_token,
            start_date,
            request_delay=request_delay,
            max_pages=max_pages,
            stop_on_429=stop_on_429,
            retry_callback=record_retry,
        )
        for orders, _data, page_meta in page_iter:
            page_number = page_meta["page_number"]
            result["pages_fetched"] = page_number
            result["stopped_by_max_pages"] = (
                result["stopped_by_max_pages"] or page_meta["stopped_by_max_pages"]
            )
            emit_progress(
                f"Page {page_number}: fetched {page_meta['orders_fetched']} orders; "
                f"total fetched {page_meta['total_fetched']}; "
                f"request delay {'on' if request_delay else 'off'}."
            )

            for order in orders:
                result["checked_orders"] += 1
                order_id = order.get("id")
                if not order_id:
                    continue
                line_items = order.get("line_items") or []
                result["line_items_seen"] += len(line_items)
                try:
                    fulfillment_orders = fetch_order_fulfillment_orders(
                        shop_domain,
                        order_id,
                        access_token,
                        request_delay=request_delay,
                        stop_on_429=stop_on_429,
                        retry_callback=record_retry,
                    )
                    result["fulfillment_orders_checked"] += 1
                except ShopifyRateLimitError:
                    fulfillment_orders = []
                    result["success"] = False
                    result["rate_limit_stopped"] = True
                    result["errors"].append(f"rate_limit_stopped_order_{order_id}")
                    stop_requested = True
                    break
                except requests.exceptions.RequestException as exc:
                    fulfillment_orders = []
                    result["errors"].append(
                        f"fulfillment_orders_failed_{order_id}: {exc.__class__.__name__}"
                    )

                current_location_normalized, current_location_raw = summarize_current_locations(fulfillment_orders)
                existing_order = ShopifyOrder.objects.filter(
                    installation=installation,
                    shopify_order_id=order_id,
                ).first()
                if existing_order:
                    result["would_update_orders"] += 1
                else:
                    result["would_create_orders"] += 1
                if dry_run:
                    continue

                order_obj, created = _upsert_review_request_order(
                    installation,
                    order,
                    current_location_normalized,
                    current_location_raw,
                )
                if created:
                    result["created_orders"] += 1
                else:
                    result["updated_orders"] += 1

                if sync_line_items:
                    item_snapshots = _build_order_item_snapshots(line_items, fulfillment_orders)
                    created_items, updated_items = _process_shenzhen_order_items(order_obj, item_snapshots)
                    result["created_items"] += created_items
                    result["updated_items"] += updated_items

            emit_progress(
                f"Page {page_number} processed: checked {result['checked_orders']} orders; "
                f"total saved/updated {result['created_orders'] + result['updated_orders']}; "
                f"would create/update {result['would_create_orders'] + result['would_update_orders']}; "
                f"backoff retries {result['rate_limit_retry_events'] + result['temporary_error_retry_events']}."
            )
            if stop_requested:
                break
    except ShopifyRateLimitError:
        result["success"] = False
        result["rate_limit_stopped"] = True
        result["errors"].append("rate_limit_stopped_order_page")

    return result


def _upsert_review_request_order(
    installation,
    order_data,
    current_location_normalized,
    current_location_raw,
):
    now = timezone.now()
    order_id = order_data["id"]
    defaults = _review_request_order_defaults(
        order_data,
        current_location_normalized,
        current_location_raw,
        now,
    )
    order_obj, created = ShopifyOrder.objects.get_or_create(
        installation=installation,
        shopify_order_id=order_id,
        defaults=defaults,
    )
    if created:
        return order_obj, True

    update_fields = {
        key: value
        for key, value in defaults.items()
        if key
        not in {
            "original_location",
            "original_location_raw",
            "is_shenzhen_order",
        }
    }
    changed_fields = []
    for field, value in update_fields.items():
        if getattr(order_obj, field) != value:
            setattr(order_obj, field, value)
            changed_fields.append(field)
    if changed_fields:
        order_obj.save(update_fields=changed_fields)
    return order_obj, False


def _review_request_order_defaults(
    order_data,
    current_location_normalized,
    current_location_raw,
    synced_at,
):
    customer = order_data.get("customer") or {}
    customer_name = " ".join(
        filter(None, [customer.get("first_name", ""), customer.get("last_name", "")])
    ).strip() or customer.get("name", "")
    shipping_address = order_data.get("shipping_address") or {}
    return {
        "order_number": order_data.get("order_number", ""),
        "order_name": order_data.get("name", ""),
        "financial_status": order_data.get("financial_status", ""),
        "fulfillment_status": order_data.get("fulfillment_status", ""),
        "customer_name": customer_name,
        "customer_email": customer.get("email") or order_data.get("email") or "",
        "shipping_name": shipping_address.get("name", ""),
        "shipping_address1": shipping_address.get("address1", ""),
        "shipping_address2": shipping_address.get("address2", ""),
        "shipping_city": shipping_address.get("city", ""),
        "shipping_province": shipping_address.get("province", ""),
        "shipping_country": shipping_address.get("country_code", ""),
        "shipping_zip": shipping_address.get("zip", ""),
        "shipping_phone": shipping_address.get("phone", ""),
        "total_price": order_data.get("total_price") or 0,
        "total_tip_received": order_data.get("total_tip_received") or 0,
        "currency": order_data.get("currency") or "USD",
        "order_created_at": _parse_shopify_datetime(order_data.get("created_at")) or synced_at,
        "shopify_note": order_data.get("note"),
        "shopify_note_attributes": order_data.get("note_attributes") or [],
        "original_location_raw": current_location_raw,
        "current_location_raw": current_location_raw,
        "original_location": None,
        "current_location": current_location_normalized,
        "is_shenzhen_order": False,
        "last_order_synced_at": synced_at,
    }


def _parse_shopify_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime_timezone.utc)
    return parsed
