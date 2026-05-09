from django.core.management.base import BaseCommand, CommandError

from shopify_sync.models import ShopifyInstallation
from shopify_sync.sync_helpers import (
    run_shopify_sync_task,
    sync_products_for_installation,
    was_sync_successful_today,
)


class Command(BaseCommand):
    help = "Sync Shopify products for the configured shop."

    def add_arguments(self, parser):
        parser.add_argument(
            "--shop",
            dest="shop",
            default="kidstoylover.myshopify.com",
            help="Shop domain to sync (default: kidstoylover.myshopify.com)",
        )
        parser.add_argument(
            "--skip-if-success-today",
            action="store_true",
            help="Skip product sync if products_daily already succeeded today.",
        )

    def handle(self, *args, **options):
        shop = options["shop"]
        task_name = "products_daily"

        if options["skip_if_success_today"] and was_sync_successful_today(task_name):
            self.stdout.write(self.style.WARNING("Products already synced successfully today; skipped."))
            return

        try:
            installation = ShopifyInstallation.objects.get(shop=shop)
        except ShopifyInstallation.DoesNotExist:
            raise CommandError(f"Shopify installation not found for {shop}")

        task_result = run_shopify_sync_task(
            task_name,
            lambda: sync_products_for_installation(installation),
            conflict_task_names=[task_name],
        )
        if task_result.get("skipped"):
            self.stdout.write(self.style.WARNING("同步正在运行中，已跳过。"))
            self.stdout.write(task_result.get("reason", ""))
            return
        result = task_result["result"]

        self.stdout.write(self.style.SUCCESS("Shopify product sync completed."))
        self.stdout.write(f"Created variants: {result['created']}")
        self.stdout.write(f"Updated variants: {result['updated']}")
        self.stdout.write(f"Skipped no SKU variants: {result['skipped_no_sku']}")
        self.stdout.write(f"Total variants processed: {result['total_variants']}")
        self.stdout.write(f"Shop domain: {result['shop_domain']}")
