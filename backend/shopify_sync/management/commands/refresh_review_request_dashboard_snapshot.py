from django.core.management.base import BaseCommand, CommandError

from shopify_sync.review_request_workbench import (
    build_review_request_dashboard_snapshot_payload,
    write_review_request_dashboard_snapshot_reports,
)


class Command(BaseCommand):
    help = (
        "Refresh the cached Review Request dashboard snapshot from local Django "
        "data and local reports only."
    )

    def handle(self, *args, **options):
        try:
            payload = build_review_request_dashboard_snapshot_payload(
                {},
                generated_by="refresh_review_request_dashboard_snapshot",
            )
            snapshot_paths = write_review_request_dashboard_snapshot_reports(payload)
        except Exception as exc:
            raise CommandError(
                "Review Request dashboard snapshot refresh failed: "
                f"{exc.__class__.__name__}: {exc}"
            ) from exc

        counters = payload.get("dashboard_counters") or {}
        paths_written = [
            snapshot_paths.get("snapshot_main_path") or snapshot_paths.get("json_path") or "",
            *snapshot_paths.get("snapshot_mirror_paths_written", []),
        ]
        html_paths_written = [
            snapshot_paths.get("snapshot_html_main_path") or snapshot_paths.get("html_path") or "",
            *snapshot_paths.get("snapshot_html_mirror_paths_written", []),
        ]
        paths_written = [path for path in paths_written if path]
        html_paths_written = [path for path in html_paths_written if path]

        self.stdout.write(self.style.SUCCESS("Review Request dashboard snapshot refreshed."))
        self.stdout.write(f"status: {payload.get('snapshot_status') or payload.get('report_status')}")
        self.stdout.write(f"eligible_total: {payload.get('eligible_total', 0)}")
        self.stdout.write(
            f"needs_review_visible_count: {counters.get('needs_review_visible_count', 0)}"
        )
        self.stdout.write(f"already_sent_total: {counters.get('already_sent_total', 0)}")
        self.stdout.write(f"snapshot_path: {snapshot_paths.get('json_path')}")
        self.stdout.write(f"generated_at: {payload.get('generated_at')}")
        self.stdout.write("json_paths_written:")
        for path in paths_written:
            self.stdout.write(f"- {path}")
        self.stdout.write("html_paths_written:")
        for path in html_paths_written:
            self.stdout.write(f"- {path}")
        self.stdout.write(
            "safety: no Shopify API call, Shopify write, translationsRegister call, "
            "Gmail API call, Gmail draft, or email send performed."
        )
        self.stdout.write("shopify_api_call_performed: False")
        self.stdout.write("shopify_write_performed: False")
        self.stdout.write("translations_register_called: False")
        self.stdout.write("gmail_api_call_performed: False")
        self.stdout.write("email_sent: False")
