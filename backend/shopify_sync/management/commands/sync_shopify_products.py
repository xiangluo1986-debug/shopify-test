from django.core.management.base import BaseCommand, CommandError

from shopify_sync.models import ShopifyInstallation
from shopify_sync.sync_helpers import sync_products_for_installation


class Command(BaseCommand):
    help = "Sync Shopify products for the configured shop."

    def add_arguments(self, parser):
        parser.add_argument(
            "--shop",
            dest="shop",
            default="kidstoylover.myshopify.com",
            help="Shop domain to sync (default: kidstoylover.myshopify.com)",
        )

    def handle(self, *args, **options):
        shop = options["shop"]

        try:
            installation = ShopifyInstallation.objects.get(shop=shop)
        except ShopifyInstallation.DoesNotExist:
            raise CommandError(f"Shopify installation not found for {shop}")

        result = sync_products_for_installation(installation)

        self.stdout.write(self.style.SUCCESS("Shopify product sync completed."))
        self.stdout.write(f"Created variants: {result['created']}")
        self.stdout.write(f"Updated variants: {result['updated']}")
        self.stdout.write(f"Skipped no SKU variants: {result['skipped_no_sku']}")
        self.stdout.write(f"Total variants processed: {result['total_variants']}")
        self.stdout.write(f"Shop domain: {result['shop_domain']}")
