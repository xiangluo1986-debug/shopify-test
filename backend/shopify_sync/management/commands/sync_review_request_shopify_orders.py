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

REVIEW_REQUEST_TAG_ALIASES = {
    "1: review request",
    "1: reveiw request",
    "1:review request",
    "1:reveiw request",
    "1 : review request",
    "1 : reveiw request",
}
DELIVERED_TAG_ALIASES = {
    "Delivered",
    "delivered",
}


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
            "--skip-fulfillment-orders",
            action="store_true",
            help=(
                "Skip per-order fulfillment-order detail reads. This is the default "
                "for Review Request sync to avoid Shopify 429 rate limits."
            ),
        )
        parser.add_argument(
            "--include-fulfillment-orders",
            action="store_true",
            help=(
                "Fetch per-order fulfillment-order details for deeper local sync. "
                "Use with --fulfillment-request-delay and optionally --fulfillment-max-orders."
            ),
        )
        parser.add_argument(
            "--fulfillment-request-delay",
            type=float,
            default=2.0,
            help=(
                "Seconds to wait after successful fulfillment-order detail reads "
                "when --include-fulfillment-orders is used (default: 2.0)."
            ),
        )
        parser.add_argument(
            "--fulfillment-max-orders",
            type=int,
            default=None,
            help=(
                "Maximum number of orders to fetch fulfillment details for when "
                "--include-fulfillment-orders is used. Base order sync continues after this limit."
            ),
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
        include_fulfillment_orders = options["include_fulfillment_orders"]
        skip_fulfillment_orders = options["skip_fulfillment_orders"]
        if include_fulfillment_orders and skip_fulfillment_orders:
            raise CommandError(
                "Use either --skip-fulfillment-orders or --include-fulfillment-orders, not both."
            )
        fulfillment_request_delay = float(options["fulfillment_request_delay"])
        if fulfillment_request_delay < 0:
            raise CommandError("--fulfillment-request-delay must be zero or greater")
        if include_fulfillment_orders and fulfillment_request_delay < 2.0:
            raise CommandError(
                "--fulfillment-request-delay must be at least 2.0 when "
                "--include-fulfillment-orders is used."
            )
        fulfillment_max_orders = options["fulfillment_max_orders"]
        if fulfillment_max_orders is not None and fulfillment_max_orders <= 0:
            raise CommandError("--fulfillment-max-orders must be greater than 0 when provided")
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
                include_fulfillment_orders=include_fulfillment_orders,
                fulfillment_request_delay=fulfillment_request_delay,
                fulfillment_max_orders=fulfillment_max_orders,
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
        self.stdout.write(f"Base orders fetched: {result['base_orders_fetched']}")
        self.stdout.write(f"Request delay seconds: {result['request_delay_seconds']:.1f}")
        self.stdout.write(f"Fulfillment details: {result['fulfillment_detail_mode']}")
        self.stdout.write(
            f"Fulfillment request delay seconds: {result['fulfillment_request_delay_seconds']:.1f}"
        )
        self.stdout.write(f"Fulfillment max orders: {result['fulfillment_max_orders'] or 'none'}")
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
        self.stdout.write(f"Fulfillment orders skipped: {result['fulfillment_orders_skipped']}")
        self.stdout.write(
            f"Fulfillment max orders reached: {result['fulfillment_max_orders_reached']}"
        )
        self.stdout.write(_format_candidate_field_summary(result["candidate_relevant_fields_captured"]))
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
    include_fulfillment_orders=False,
    fulfillment_request_delay=2.0,
    fulfillment_max_orders=None,
    progress_callback=None,
):
    shop_domain = installation.shop
    access_token = installation.access_token
    request_delay = max(float(request_delay or 0), 0)
    fulfillment_request_delay = max(float(fulfillment_request_delay or 0), 0)
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
        "base_orders_fetched": 0,
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
        "include_fulfillment_orders": include_fulfillment_orders,
        "fulfillment_detail_mode": "included" if include_fulfillment_orders else "skipped",
        "fulfillment_request_delay_seconds": fulfillment_request_delay,
        "fulfillment_max_orders": fulfillment_max_orders,
        "fulfillment_max_orders_reached": False,
        "fulfillment_orders_checked": 0,
        "fulfillment_orders_skipped": 0,
        "line_items_seen": 0,
        "created_items": 0,
        "updated_items": 0,
        "candidate_relevant_fields_captured": {
            "orders_with_tags": 0,
            "orders_with_delivered_tag": 0,
            "orders_with_review_request_tag_alias": 0,
            "orders_with_fulfillment_status": 0,
            "orders_with_financial_status": 0,
            "orders_with_note": 0,
            "orders_with_note_attributes": 0,
        },
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
    if include_fulfillment_orders:
        emit_progress(
            "Including per-order fulfillment details for Review Request sync; "
            f"fulfillment_request_delay={fulfillment_request_delay:.1f}s; "
            f"fulfillment_max_orders={fulfillment_max_orders or 'none'}."
        )
    else:
        emit_progress(
            "Skipping per-order fulfillment details for Review Request sync. "
            "Delivered/tag-based candidate scan will use order tags/status first."
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
            result["base_orders_fetched"] += page_meta["orders_fetched"]
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
                _record_candidate_relevant_fields(result, order)
                fulfillment_orders = []
                fulfillment_details_available = False
                if _should_fetch_fulfillment_orders(
                    include_fulfillment_orders,
                    result["fulfillment_orders_checked"],
                    fulfillment_max_orders,
                ):
                    try:
                        fulfillment_orders = fetch_order_fulfillment_orders(
                            shop_domain,
                            order_id,
                            access_token,
                            request_delay=fulfillment_request_delay,
                            stop_on_429=stop_on_429,
                            retry_callback=record_retry,
                        )
                        result["fulfillment_orders_checked"] += 1
                        fulfillment_details_available = True
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
                else:
                    result["fulfillment_orders_skipped"] += 1
                    if include_fulfillment_orders and fulfillment_max_orders is not None:
                        result["fulfillment_max_orders_reached"] = True

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
                    update_fulfillment_location=fulfillment_details_available,
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
    update_fulfillment_location=True,
):
    now = timezone.now()
    order_id = order_data["id"]
    defaults = _review_request_order_defaults(
        order_data,
        current_location_normalized,
        current_location_raw,
        now,
        update_fulfillment_location=update_fulfillment_location,
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
    update_fulfillment_location=True,
):
    customer = order_data.get("customer") or {}
    customer_name = " ".join(
        filter(None, [customer.get("first_name", ""), customer.get("last_name", "")])
    ).strip() or customer.get("name", "")
    shipping_address = order_data.get("shipping_address") or {}
    defaults = {
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
        "shopify_tags": _shopify_tags_to_storage(order_data.get("tags"))
        if "tags" in order_data
        else None,
        "last_order_synced_at": synced_at,
    }
    if update_fulfillment_location:
        defaults.update(
            {
                "original_location_raw": current_location_raw,
                "current_location_raw": current_location_raw,
                "original_location": None,
                "current_location": current_location_normalized,
                "is_shenzhen_order": False,
            }
        )
    return defaults


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


def _should_fetch_fulfillment_orders(include_fulfillment_orders, checked_count, max_orders):
    if not include_fulfillment_orders:
        return False
    if max_orders is None:
        return True
    return checked_count < max_orders


def _record_candidate_relevant_fields(result, order):
    counters = result["candidate_relevant_fields_captured"]
    tags = _split_shopify_tags(order.get("tags"))
    if tags:
        counters["orders_with_tags"] += 1
    if _has_alias_tag(tags, DELIVERED_TAG_ALIASES):
        counters["orders_with_delivered_tag"] += 1
    if _has_alias_tag(tags, REVIEW_REQUEST_TAG_ALIASES):
        counters["orders_with_review_request_tag_alias"] += 1
    if order.get("fulfillment_status"):
        counters["orders_with_fulfillment_status"] += 1
    if order.get("financial_status"):
        counters["orders_with_financial_status"] += 1
    if order.get("note"):
        counters["orders_with_note"] += 1
    if order.get("note_attributes"):
        counters["orders_with_note_attributes"] += 1


def _split_shopify_tags(value):
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _shopify_tags_to_storage(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value)


def _has_alias_tag(tags, aliases):
    normalized_aliases = {_normalize_tag_for_alias(alias) for alias in aliases}
    return any(_normalize_tag_for_alias(tag) in normalized_aliases for tag in tags)


def _normalize_tag_for_alias(value):
    return "".join(str(value or "").strip().lower().split())


def _format_candidate_field_summary(counters):
    return (
        "Candidate-relevant fields captured: "
        f"tags on {counters['orders_with_tags']} orders; "
        f"Delivered tag on {counters['orders_with_delivered_tag']} orders; "
        f"review-request tag alias on {counters['orders_with_review_request_tag_alias']} orders; "
        f"fulfillment_status on {counters['orders_with_fulfillment_status']} orders; "
        f"financial_status on {counters['orders_with_financial_status']} orders; "
        f"notes on {counters['orders_with_note']} orders; "
        f"note attributes on {counters['orders_with_note_attributes']} orders."
    )
