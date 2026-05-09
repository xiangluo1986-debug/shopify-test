from django.core.management.base import BaseCommand, CommandError

from shopify_sync.models import ShopifyInstallation
from shopify_sync.sync_helpers import (
    run_shopify_sync_task,
    update_shenzhen_tracking_for_installation,
)


class Command(BaseCommand):
    help = "Update fulfillment tracking and Shenzhen order tracking state for existing Shopify orders."

    def add_arguments(self, parser):
        parser.add_argument(
            "--shop",
            dest="shop",
            default="kidstoylover.myshopify.com",
            help="Shop domain to update tracking for (default: kidstoylover.myshopify.com)",
        )

    def handle(self, *args, **options):
        shop = options["shop"]

        try:
            installation = ShopifyInstallation.objects.get(shop=shop)
        except ShopifyInstallation.DoesNotExist:
            raise CommandError(f"Shopify installation not found for {shop}")

        task_result = run_shopify_sync_task(
            "tracking_update",
            lambda: update_shenzhen_tracking_for_installation(installation),
            conflict_task_names=["tracking_update"],
        )
        if task_result.get("skipped"):
            self.stdout.write(self.style.WARNING("同步正在运行中，已跳过。"))
            self.stdout.write(task_result.get("reason", ""))
            return
        result = task_result["result"]

        self.stdout.write(self.style.SUCCESS("Shenzhen tracking update completed."))
        self.stdout.write(f"Checked orders: {result['checked_orders']}")
        self.stdout.write(f"Updated tracking: {result['updated_tracking']}")
        self.stdout.write(f"Auto-marked warehouse fulfilled: {result['auto_marked_warehouse_fulfilled']}")
        self.stdout.write(f"Skipped paid orders: {result['skipped_paid_orders']}")
        self.stdout.write(f"Detected tracking count: {result['detected_tracking_count']}")

        if result["errors"]:
            self.stderr.write(self.style.WARNING("Errors encountered:"))
            for error in result["errors"]:
                self.stderr.write(f"- {error}")
