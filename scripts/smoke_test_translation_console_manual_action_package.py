import argparse
import json
import os
import py_compile
import re
import subprocess
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
JSON_REPORT_PATH = ROOT / "logs" / "translation_console_manual_action_smoke_test.json"
HTML_REPORT_PATH = ROOT / "logs" / "translation_console_manual_action_smoke_test.html"
SUGGESTED_USE_DOCKER_COMMAND = (
    "python scripts\\smoke_test_translation_console_manual_action_package.py "
    "--live-dry-run --use-docker"
)
SUGGESTED_DOCKER_COMMAND = "docker compose exec -T web python manage.py smoke_test_translation_console_manual_action_package --live-dry-run"
DOCKER_WRAPPER_COMMAND = [
    "docker",
    "compose",
    "exec",
    "-T",
    "-e",
    "TRANSLATION_SMOKE_RUNNING_IN_DOCKER=1",
    "web",
    "python",
    "manage.py",
    "smoke_test_translation_console_manual_action_package",
    "--live-dry-run",
]

DEFAULT_PRODUCT_ID = "gid://shopify/Product/7655686799427"
DEFAULT_TARGET_LOCALES = ["ja", "de", "fr", "es", "it"]
DEFAULT_FIELDS = ["title", "meta_title", "meta_description"]
READY_PACKAGE_STATUS = (
    "selected_product_translation_real_write_manual_action_package_ready_for_manual_review"
)

COMPILE_FILES = [
    "backend/shopify_sync/views.py",
    "backend/shopify_sync/translation_drafts.py",
    "backend/shopify_sync/translation_apply_plan.py",
    "backend/shopify_sync/translation_final_review.py",
    "backend/shopify_sync/translation_real_write_readiness.py",
    "backend/shopify_sync/translation_locked_execution_plan.py",
    "backend/shopify_sync/translation_locked_executor.py",
    "backend/shopify_sync/translation_real_write_executor.py",
    "backend/shopify_sync/translation_real_write_manual_action_package.py",
    "backend/shopify_sync/management/commands/smoke_test_translation_console_manual_action_package.py",
]

STATIC_REQUIRED_TEXT = {
    "backend/shopify_sync/templates/admin/shopify_sync/translation_console.html": [
        "generate_translation_real_write_manual_action_package",
        "Generate real write manual action package",
        "No Shopify write",
        "Manual action package summary",
        "Planned translationsRegister payload preview",
        "Readback verification plan",
        "Rollback policy",
    ],
    "backend/shopify_sync/views.py": [
        "generate_translation_real_write_manual_action_package",
        "build_selected_product_translation_real_write_manual_action_package",
        "manual_action_package_result",
    ],
    "backend/shopify_sync/translation_real_write_manual_action_package.py": [
        "PACKAGE_READY_STATUS",
        "planned_graphql_variables_preview",
        "future_powershell_command_preview",
        "readback_verify_plan",
        "rollback_plan",
        "translations_register_called",
        "shopify_write_performed",
        "real_write_allowed",
        "manual_ack_effective",
    ],
}

FORBIDDEN_TRUE_FIELDS = [
    "real_write_allowed",
    "future_write_allowed",
    "dangerous_ack_effective",
    "manual_ack_effective",
    "translations_register_called",
    "shopify_write_performed",
    "mutation_performed",
    "real_apply_performed",
    "rollback_performed",
]

PHASE_FILES = [
    "backend/shopify_sync/views.py",
    "backend/shopify_sync/templates/admin/shopify_sync/translation_console.html",
    "backend/shopify_sync/translation_locked_executor.py",
    "backend/shopify_sync/translation_real_write_executor.py",
    "backend/shopify_sync/translation_real_write_manual_action_package.py",
]


def main():
    parser = argparse.ArgumentParser(
        description="Smoke test the Translation Console manual action package chain."
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--static-only",
        action="store_true",
        help="Only inspect local code and templates. This is the default.",
    )
    mode_group.add_argument(
        "--live-dry-run",
        action="store_true",
        help="Run the full helper chain. May call Shopify read-only and OpenAI, but never writes Shopify.",
    )
    parser.add_argument(
        "--use-docker",
        action="store_true",
        help="Run live-dry-run inside the Docker web container from the host.",
    )
    args = parser.parse_args()
    mode = "live-dry-run" if args.live_dry_run else "static-only"

    if args.use_docker and args.live_dry_run and not _running_in_docker():
        return _run_live_dry_run_via_docker()

    payload = _base_payload(mode)
    try:
        if mode == "static-only":
            _run_static_checks(payload)
        else:
            _run_live_dry_run(payload)
    except ModuleNotFoundError as exc:
        if exc.name == "django":
            _record_missing_django(payload)
        else:
            raise

    payload["blocking_conditions"] = _unique(payload["blocking_conditions"])
    payload["validation_status"] = (
        "passed" if not payload["blocking_conditions"] else "failed"
    )
    payload["checked_at"] = datetime.now(timezone.utc).isoformat()
    _write_reports(payload)
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if payload["validation_status"] == "passed" else 1


def _base_payload(mode):
    return {
        "validation_status": "failed",
        "mode": mode,
        "checked_at": "",
        "product_id": DEFAULT_PRODUCT_ID,
        "target_locales": DEFAULT_TARGET_LOCALES,
        "fields": DEFAULT_FIELDS,
        "package_status": "not_run_static_only" if mode == "static-only" else "",
        "entry_count": 0,
        "blocked_entry_count": 0,
        "compile_results": {},
        "static_checks": {},
        "live_chain_status": {},
        "manual_action_package_summary": {},
        "blocking_conditions": [],
        "failure_type": "",
        "suggested_command": "",
        "docker_return_code": None,
        "docker_stdout_tail": "",
        "docker_stderr_tail": "",
        "no_write_confirmed": False,
        "json_report_path": str(JSON_REPORT_PATH.relative_to(ROOT)),
        "html_report_path": str(HTML_REPORT_PATH.relative_to(ROOT)),
    }


def _run_live_dry_run_via_docker():
    completed = None
    try:
        completed = subprocess.run(
            DOCKER_WRAPPER_COMMAND,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        payload = _base_payload("live-dry-run")
        payload.update(
            {
                "validation_status": "failed",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "failure_type": "docker_command_not_available",
                "suggested_command": SUGGESTED_USE_DOCKER_COMMAND,
                "blocking_conditions": ["docker_command_not_available"],
                "no_write_confirmed": True,
            }
        )
        _write_reports(payload)
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        print(str(exc), file=sys.stderr)
        return 1

    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode != 0:
        combined_output = f"{completed.stdout}\n{completed.stderr}"
        output_lower = combined_output.lower()
        failure_type = (
            "management_command_not_available"
            if (
                "unknown command" in output_lower
                or (
                    "smoke_test_translation_console_manual_action_package"
                    in combined_output
                    and "can't open file" in output_lower
                )
            )
            else "docker_management_command_failed"
        )
        payload = _base_payload("live-dry-run")
        payload.update(
            {
                "validation_status": "failed",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "failure_type": failure_type,
                "suggested_command": SUGGESTED_USE_DOCKER_COMMAND,
                "docker_return_code": completed.returncode,
                "docker_stdout_tail": _tail(completed.stdout),
                "docker_stderr_tail": _tail(completed.stderr),
                "blocking_conditions": [failure_type],
                "no_write_confirmed": True,
            }
        )
        _write_reports(payload)
        print(json.dumps(payload, ensure_ascii=True, indent=2))
    return completed.returncode


def _record_missing_django(payload):
    payload["failure_type"] = "missing_django_on_host"
    payload["suggested_command"] = SUGGESTED_USE_DOCKER_COMMAND
    payload["blocking_conditions"].append("missing_django_on_host")
    payload["no_write_confirmed"] = True


def _run_static_checks(payload):
    payload["compile_results"] = _compile_files(payload["blocking_conditions"])
    payload["static_checks"]["required_text"] = _check_required_text(
        payload["blocking_conditions"]
    )
    payload["static_checks"]["dangerous_true_flags"] = _check_dangerous_true_flags(
        payload["blocking_conditions"]
    )
    payload["static_checks"]["no_real_shopify_call_markers"] = _check_no_real_call_markers(
        payload["blocking_conditions"]
    )
    payload["no_write_confirmed"] = not payload["blocking_conditions"]


def _run_live_dry_run(payload):
    _setup_django()
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

    installation = ShopifyInstallation.objects.first()
    if installation is None:
        payload["blocking_conditions"].append("missing_shopify_installation")
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


def _setup_django():
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


def _running_in_docker():
    return (
        os.getenv("TRANSLATION_SMOKE_RUNNING_IN_DOCKER") == "1"
        or Path("/.dockerenv").exists()
    )


def _tail(value, max_chars=4000):
    if not value:
        return ""
    return value[-max_chars:]


def _compile_files(blocking_conditions):
    results = {}
    for rel_path in COMPILE_FILES:
        path = ROOT / rel_path
        if not path.exists():
            results[rel_path] = {"status": "missing"}
            blocking_conditions.append(f"compile_missing:{rel_path}")
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            results[rel_path] = {"status": "failed", "error": str(exc)}
            blocking_conditions.append(f"compile_failed:{rel_path}")
        else:
            results[rel_path] = {"status": "passed"}
    return results


def _check_required_text(blocking_conditions):
    results = {}
    for rel_path, required_items in STATIC_REQUIRED_TEXT.items():
        text = _read_text(rel_path).lower()
        results[rel_path] = {}
        for item in required_items:
            present = item.lower() in text
            results[rel_path][item] = present
            if not present:
                blocking_conditions.append(f"missing_required_text:{rel_path}:{item}")
    return results


def _check_dangerous_true_flags(blocking_conditions):
    findings = []
    for rel_path in PHASE_FILES:
        text = _read_text(rel_path)
        for field in FORBIDDEN_TRUE_FIELDS:
            pattern = re.compile(
                rf"""(?ix)
                (?:
                    ["']?\s*{re.escape(field)}\s*["']?\s*[:=]\s*True\b
                )
                """
            )
            for match in pattern.finditer(text):
                findings.append(
                    {
                        "file": rel_path,
                        "field": field,
                        "line": _line_number(text, match.start()),
                        "match": match.group(0).strip(),
                    }
                )
    for finding in findings:
        blocking_conditions.append(
            f"dangerous_true_flag:{finding['file']}:{finding['field']}:{finding['line']}"
        )
    return {"status": "passed" if not findings else "failed", "findings": findings}


def _check_no_real_call_markers(blocking_conditions):
    patterns = [
        r"\brequests\.post\b",
        r"\brequests\.request\b",
        r"\burllib\b",
        r"\burlopen\b",
        r"\bexecute_graphql\b",
        r"\bshopify_graphql\b",
        r"\bclient\.execute\b",
        r"\btranslationsRegister\s*\(",
        r"\bmutation\s*\{",
    ]
    findings = []
    helper_files = [
        "backend/shopify_sync/translation_locked_executor.py",
        "backend/shopify_sync/translation_real_write_executor.py",
        "backend/shopify_sync/translation_real_write_manual_action_package.py",
    ]
    for rel_path in helper_files:
        text = _read_text(rel_path)
        for raw_pattern in patterns:
            pattern = re.compile(raw_pattern)
            for match in pattern.finditer(text):
                findings.append(
                    {
                        "file": rel_path,
                        "line": _line_number(text, match.start()),
                        "match": match.group(0),
                    }
                )
    for finding in findings:
        blocking_conditions.append(
            f"real_call_marker:{finding['file']}:{finding['line']}:{finding['match']}"
        )
    return {"status": "passed" if not findings else "failed", "findings": findings}


def _read_text(rel_path):
    path = ROOT / rel_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _line_number(text, index):
    return text.count("\n", 0, index) + 1


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
            ("Failure Type", "failure_type"),
            ("Suggested Command", "suggested_command"),
            ("Docker Return Code", "docker_return_code"),
            ("Docker Stdout Tail", "docker_stdout_tail"),
            ("Docker Stderr Tail", "docker_stderr_tail"),
            ("JSON Report Path", "json_report_path"),
            ("HTML Report Path", "html_report_path"),
        ]
    )
    details_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Compile Results", "compile_results"),
            ("Static Checks", "static_checks"),
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
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{details_rows}</tbody></table>
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


if __name__ == "__main__":
    sys.exit(main())
