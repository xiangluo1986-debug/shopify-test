from django.core.management.base import BaseCommand, CommandError

from shopify_sync.models import ShopifyInstallation
from shopify_sync.sync_helpers import sync_shenzhen_orders_for_installation


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

    def handle(self, *args, **options):
        shop = options["shop"]
        days = options["days"]

        try:
            installation = ShopifyInstallation.objects.get(shop=shop)
        except ShopifyInstallation.DoesNotExist:
            raise CommandError(f"Shopify installation not found for {shop}")

        result = sync_shenzhen_orders_for_installation(installation, days=days)

        self.stdout.write(self.style.SUCCESS("Shenzhen order sync completed."))
        self.stdout.write(f"Checked orders: {result['checked_orders']}")
        self.stdout.write(f"Created orders: {result['created_orders']}")
        self.stdout.write(f"Updated orders: {result['updated_orders']}")
        self.stdout.write(f"Created items: {result['created_items']}")
        self.stdout.write(f"Updated items: {result['updated_items']}")
        self.stdout.write(f"Updated tracking: {result['updated_tracking']}")
        self.stdout.write(f"Auto-marked warehouse fulfilled: {result['auto_marked_warehouse_fulfilled']}")
        self.stdout.write(f"Detected tracking count: {result['detected_tracking_count']}")

        if result["errors"]:
            self.stderr.write(self.style.WARNING("Errors encountered:"))
            for error in result["errors"]:
                self.stderr.write(f"- {error}")
