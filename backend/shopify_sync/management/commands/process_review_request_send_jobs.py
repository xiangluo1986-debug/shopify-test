from django.core.management.base import BaseCommand, CommandError

from shopify_sync.review_request_workbench import process_review_request_send_jobs


class Command(BaseCommand):
    help = (
        "Process one queued Shopify Review Request send job. The web request "
        "only queues jobs; this command performs the slow Gmail/send/tag flow."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-jobs",
            type=int,
            default=1,
            help="Maximum jobs to process. Safety cap forces this to one.",
        )
        parser.add_argument(
            "--order",
            default="",
            help="Optional one order name, for example '#22562'.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show the next queued job without calling Gmail or Shopify.",
        )

    def handle(self, *args, **options):
        summary = process_review_request_send_jobs(
            max_jobs=options.get("max_jobs") or 1,
            order_name=options.get("order") or "",
            dry_run=options.get("dry_run") is True,
        )
        status = summary.get("status") or "unknown"
        if status == "failed_queue_unavailable":
            raise CommandError(
                "Review Request send-job queue could not be loaded: "
                f"{summary.get('queue_load_error') or 'unknown error'}"
            )

        self.stdout.write(f"status: {status}")
        self.stdout.write(f"dry_run: {summary.get('dry_run') is True}")
        self.stdout.write(f"queue_path: {summary.get('queue_path')}")
        self.stdout.write(f"canonical_queue_path: {summary.get('canonical_queue_path')}")
        self.stdout.write(
            f"queue_path_used_by_processor: {summary.get('queue_path_used_by_processor')}"
        )
        self.stdout.write(f"queue_file_exists: {summary.get('queue_file_exists') is True}")
        self.stdout.write(f"queue_file_missing: {summary.get('queue_file_missing') is True}")
        self.stdout.write(
            f"canonical_queue_file_missing: {summary.get('canonical_queue_file_missing') is True}"
        )
        self.stdout.write(f"job_count: {summary.get('job_count', 0)}")
        self.stdout.write(f"queued_job_count: {summary.get('queued_job_count', 0)}")
        self.stdout.write(f"queued_jobs_found: {summary.get('queued_jobs_found', 0)}")
        self.stdout.write(f"selected_job_count: {summary.get('selected_job_count', 0)}")
        self.stdout.write(f"processed_count: {summary.get('processed_count', 0)}")
        self.stdout.write(f"sent_count: {summary.get('sent_count', 0)}")
        self.stdout.write(f"tag_written_count: {summary.get('tag_written_count', 0)}")
        self.stdout.write(f"failed_count: {summary.get('failed_count', 0)}")
        self.stdout.write(f"skipped_count: {summary.get('skipped_count', 0)}")
        self.stdout.write(
            f"max_jobs_capped_to_one: {summary.get('max_jobs_capped_to_one') is True}"
        )
        self.stdout.write(
            f"dashboard_snapshot_refreshed: {summary.get('dashboard_snapshot_refreshed') is True}"
        )
        if summary.get("dashboard_snapshot_error"):
            self.stdout.write(f"dashboard_snapshot_error: {summary.get('dashboard_snapshot_error')}")

        self.stdout.write("paths_checked:")
        for item in summary.get("paths_checked") or []:
            if isinstance(item, dict):
                self.stdout.write(
                    "- "
                    f"{item.get('path')} "
                    f"present={item.get('present') is True} "
                    f"loaded={item.get('loaded') is True} "
                    f"selected={item.get('selected') is True} "
                    f"status={item.get('status') or '-'}"
                )
            else:
                self.stdout.write(f"- {item}")

        self.stdout.write("queued_orders:")
        queued_orders = summary.get("queued_orders") or []
        if queued_orders:
            for order_name in queued_orders:
                self.stdout.write(f"- {order_name}")
        else:
            self.stdout.write("- none")

        self.stdout.write("recent_completed_orders:")
        recent_completed_orders = summary.get("recent_completed_orders") or []
        if recent_completed_orders:
            for item in recent_completed_orders:
                self.stdout.write(
                    "- "
                    f"{item.get('order_name')} "
                    f"{item.get('status')} "
                    f"{item.get('updated_at') or ''}"
                )
        else:
            self.stdout.write("- none")

        if summary.get("dry_run") is True:
            self.stdout.write("recent_jobs:")
            for job in summary.get("recent_jobs") or []:
                self.stdout.write(
                    "- "
                    f"{job.get('job_id')} "
                    f"{job.get('order_name')} "
                    f"{job.get('status')} "
                    f"{job.get('message') or ''}"
                )

        for job in summary.get("jobs") or []:
            self.stdout.write(
                "job: "
                f"{job.get('job_id')} "
                f"{job.get('order_name')} "
                f"{job.get('status')} "
                f"{job.get('message') or job.get('last_error') or ''}"
            )

        self.stdout.write(
            f"gmail_api_call_performed: {summary.get('gmail_api_call_performed') is True}"
        )
        self.stdout.write(
            f"shopify_api_call_performed: {summary.get('shopify_api_call_performed') is True}"
        )
        self.stdout.write(
            f"shopify_write_performed: {summary.get('shopify_write_performed') is True}"
        )
        self.stdout.write(
            f"translations_register_called: {summary.get('translations_register_called') is True}"
        )
