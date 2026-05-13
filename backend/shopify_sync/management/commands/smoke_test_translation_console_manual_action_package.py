import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from django.core.management.base import BaseCommand

from shopify_sync.models import ShopifyInstallation
from shopify_sync.translation_apply_plan import (
    build_selected_product_translation_apply_plan,
)
from shopify_sync.translation_drafts import (
    generate_selected_product_missing_translation_draft_package,
)
from shopify_sync.translation_final_review import (
    build_selected_product_translation_final_review,
)
from shopify_sync.translation_locked_execution_plan import (
    build_selected_product_translation_locked_execution_plan,
)
from shopify_sync.translation_locked_executor import (
    build_selected_product_translation_locked_executor_shell,
)
from shopify_sync.translation_real_write_executor import (
    build_selected_product_translation_real_write_executor_dry_run,
)
from shopify_sync.translation_real_write_manual_action_package import (
    build_selected_product_translation_real_write_manual_action_package,
)
from shopify_sync.translation_real_write_readiness import (
    build_selected_product_translation_real_write_readiness,
)


ROOT = Path(__file__).resolve().parents[3]
JSON_REPORT_PATH = ROOT / "logs" / "translation_console_manual_action_smoke_test.json"
HTML_REPORT_PATH = ROOT / "logs" / "translation_console_manual_action_smoke_test.html"

DEFAULT_PRODUCT_ID = "gid://shopify/Product/7655686799427"
DEFAULT_TARGET_LOCALES = ["ja", "de", "fr", "es", "it"]
DEFAULT_FIELDS = ["title", "meta_title", "meta_description"]
READY_PACKAGE_STATUS = (
    "selected_product_translation_real_write_manual_action_package_ready_for_manual_review"
)


class Command(BaseCommand):
    help = "Run a no-write live dry-run smoke test for the Translation Console manual action package."

    def add_arguments(self, parser):
        parser.add_argument(
            "--live-dry-run",
            action="store_true",
            help="Run the live dry-run helper chain. This may call Shopify read-only and OpenAI, but never writes Shopify.",
        )

    def handle(self, *args, **options):
        payload = _base_payload()
        if not options.get("live_dry_run"):
            payload["blocking_conditions"].append("missing_live_dry_run_flag")
        else:
            _run_live_dry_run(payload)

        payload["blocking_conditions"] = _unique(payload["blocking_conditions"])
        payload["validation_status"] = (
            "passed" if not payload["blocking_conditions"] else "failed"
        )
        payload["checked_at"] = datetime.now(timezone.utc).isoformat()
        _write_reports(payload)
        self.stdout.write(json.dumps(payload, ensure_ascii=True, indent=2))
        if payload["validation_status"] != "passed":
            raise SystemExit(1)


def _base_payload():
    return {
        "validation_status": "failed",
        "mode": "live-dry-run",
        "checked_at": "",
        "product_id": DEFAULT_PRODUCT_ID,
        "target_locales": DEFAULT_TARGET_LOCALES,
        "fields": DEFAULT_FIELDS,
        "package_status": "",
        "entry_count": 0,
        "blocked_entry_count": 0,
        "live_chain_status": {},
        "manual_action_package_summary": {},
        "blocking_conditions": [],
        "no_write_confirmed": False,
        "json_report_path": str(JSON_REPORT_PATH),
        "html_report_path": str(HTML_REPORT_PATH),
    }


def _run_live_dry_run(payload):
    installation = ShopifyInstallation.objects.first()
    if installation is None:
        payload["blocking_conditions"].append("missing_shopify_installation")
        payload["no_write_confirmed"] = True
        return

    draft_result = generate_selected_product_missing_translation_draft_package(
        product_id=DEFAULT_PRODUCT_ID,
        target_locales=DEFAULT_TARGET_LOCALES,
        fields=DEFAULT_FIELDS,
        installation=installation,
    )
    apply_plan_result = build_selected_product_translation_apply_plan(draft_result)
    final_review_result = build_selected_product_translation_final_review(apply_plan_result)
    readiness_result = build_selected_product_translation_real_write_readiness(
        final_review_result
    )
    locked_execution_plan_result = build_selected_product_translation_locked_execution_plan(
        readiness_result
    )
    locked_executor_result = build_selected_product_translation_locked_executor_shell(
        locked_execution_plan_result
    )
    real_write_executor_result = build_selected_product_translation_real_write_executor_dry_run(
        locked_executor_result,
        selected_product_id=DEFAULT_PRODUCT_ID,
    )
    manual_action_package_result = (
        build_selected_product_translation_real_write_manual_action_package(
            real_write_executor_result,
            selected_product_id=DEFAULT_PRODUCT_ID,
        )
    )

    payload["live_chain_status"] = {
        "draft_status": draft_result.get("draft_status", ""),
        "apply_plan_status": apply_plan_result.get("apply_plan_status", ""),
        "final_review_status": final_review_result.get("final_review_status", ""),
        "readiness_status": readiness_result.get("readiness_status", ""),
        "execution_plan_status": locked_execution_plan_result.get(
            "execution_plan_status", ""
        ),
        "locked_executor_status": locked_executor_result.get("executor_status", ""),
        "real_write_executor_status": real_write_executor_result.get(
            "executor_status", ""
        ),
        "package_status": manual_action_package_result.get("package_status", ""),
    }
    _validate_manual_action_package(payload, manual_action_package_result)


def _validate_manual_action_package(payload, package_result):
    expected_false = [
        "real_write_allowed",
        "future_write_allowed",
        "manual_ack_effective",
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
        "real_apply_performed",
        "rollback_performed",
    ]
    expected_true = [
        "no_new_shopify_writes_performed",
        "all_new_actions_no_write_confirmed",
    ]
    payload["package_status"] = package_result.get("package_status", "")
    payload["entry_count"] = int(package_result.get("entry_count") or 0)
    payload["blocked_entry_count"] = int(package_result.get("blocked_entry_count") or 0)
    payload["manual_action_package_summary"] = {
        "mode": package_result.get("mode", ""),
        "product_id": package_result.get("product_id", ""),
        "entry_count": payload["entry_count"],
        "blocked_entry_count": payload["blocked_entry_count"],
        "planned_translation_inputs_count": package_result.get(
            "planned_translation_inputs_count", 0
        ),
        "blocking_conditions": package_result.get("blocking_conditions", []),
    }
    if package_result.get("package_status") != READY_PACKAGE_STATUS:
        payload["blocking_conditions"].append("package_status_not_ready")
    if package_result.get("mode") != "manual-action-package":
        payload["blocking_conditions"].append("mode_not_manual_action_package")
    if payload["entry_count"] <= 0:
        payload["blocking_conditions"].append("entry_count_not_positive")
    if payload["blocked_entry_count"] != 0:
        payload["blocking_conditions"].append("blocked_entry_count_not_zero")
    for key in expected_false:
        if package_result.get(key) is not False:
            payload["blocking_conditions"].append(f"{key}_not_false")
    for key in expected_true:
        if package_result.get(key) is not True:
            payload["blocking_conditions"].append(f"{key}_not_true")
    if package_result.get("blocking_conditions"):
        payload["blocking_conditions"].append("package_has_blocking_conditions")
    payload["no_write_confirmed"] = not payload["blocking_conditions"]


def _write_reports(payload):
    JSON_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    JSON_REPORT_PATH.write_text(text, encoding="utf-8")
    HTML_REPORT_PATH.write_text(_render_html(payload), encoding="utf-8")


def _render_html(payload):
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Validation Status", "validation_status"),
            ("Mode", "mode"),
            ("Checked At", "checked_at"),
            ("Product ID", "product_id"),
            ("Package Status", "package_status"),
            ("Entry Count", "entry_count"),
            ("Blocked Entry Count", "blocked_entry_count"),
            ("No Write Confirmed", "no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
            ("JSON Report Path", "json_report_path"),
            ("HTML Report Path", "html_report_path"),
        ]
    )
    detail_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Live Chain Status", "live_chain_status"),
            ("Manual Action Package Summary", "manual_action_package_summary"),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Translation Console Manual Action Smoke Test</title></head>
<body>
  <h1>Translation Console Manual Action Smoke Test</h1>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Details</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{detail_rows}</tbody></table>
</body>
</html>
"""


def _row(label, value):
    return f"<tr><th>{escape(str(label))}</th><td>{escape(str(value))}</td></tr>"


def _unique(values):
    output = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output
