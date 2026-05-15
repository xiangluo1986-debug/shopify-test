from django.core.management.base import BaseCommand, CommandError

from shopify_sync.models import ShopifyInstallation
from shopify_sync.review_request_workbench import (
    run_trustpilot_auto_queue_refresh_after_shopify_order_sync,
)
from shopify_sync.sync_helpers import (
    ORDER_SYNC_TASK_NAMES,
    run_shopify_sync_task,
    sync_shenzhen_orders_for_installation,
)


class Command(BaseCommand):
    help = "Sync Shenzhen Shopify orders and update fulfillment tracking."

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
            help="Number of past days to fetch orders for sync.",
        )
        parser.add_argument(
            "--task-name",
            dest="task_name",
            default=None,
            help="Sync state task name. Defaults to orders_incremental for <=3 days, otherwise orders_manual.",
        )

    def handle(self, *args, **options):
        shop = options["shop"]
        days = options["days"]
        task_name = options["task_name"] or ("orders_incremental" if days <= 3 else "orders_manual")

        try:
            installation = ShopifyInstallation.objects.get(shop=shop)
        except ShopifyInstallation.DoesNotExist:
            raise CommandError(f"Shopify installation not found for {shop}")

        task_result = run_shopify_sync_task(
            task_name,
            lambda: sync_shenzhen_orders_for_installation(installation, days=days),
            conflict_task_names=ORDER_SYNC_TASK_NAMES,
        )
        if task_result.get("skipped"):
            self.stdout.write(self.style.WARNING("同步正在运行中，已跳过。"))
            self.stdout.write(task_result.get("reason", ""))
            return
        result = task_result["result"]
        try:
            refresh_result = run_trustpilot_auto_queue_refresh_after_shopify_order_sync()
        except Exception as exc:
            refresh_result = {
                "last_auto_refresh_status": "auto_refresh_failed_non_blocking",
                "last_auto_refresh_error": f"{exc.__class__.__name__}",
            }

        self.stdout.write(self.style.SUCCESS("Shenzhen order sync completed."))
        self.stdout.write(f"Checked orders: {result['checked_orders']}")
        self.stdout.write(f"Created orders: {result['created_orders']}")
        self.stdout.write(f"Updated orders: {result['updated_orders']}")
        self.stdout.write(f"Skipped missing ship from china tag: {result['skipped_missing_ship_from_china_tag']}")
        self.stdout.write(f"Skipped no Shenzhen items: {result['skipped_no_shenzhen_items']}")
        self.stdout.write(f"Created items: {result['created_items']}")
        self.stdout.write(f"Updated items: {result['updated_items']}")
        self.stdout.write(f"Updated tracking: {result['updated_tracking']}")
        self.stdout.write(f"Auto-marked warehouse fulfilled: {result['auto_marked_warehouse_fulfilled']}")
        self.stdout.write(f"Detected tracking count: {result['detected_tracking_count']}")
        self.stdout.write(
            "Trustpilot queue auto refresh: "
            f"{refresh_result.get('last_auto_refresh_status') or 'unknown'}"
        )

        if result["errors"]:
            self.stderr.write(self.style.WARNING("Errors encountered:"))
            for error in result["errors"]:
                self.stderr.write(f"- {error}")
