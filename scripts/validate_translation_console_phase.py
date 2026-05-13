import json
import py_compile
import re
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JSON_REPORT_PATH = ROOT / "logs" / "translation_console_local_validation.json"
HTML_REPORT_PATH = ROOT / "logs" / "translation_console_local_validation.html"

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

TEMPLATE_FILE = "backend/shopify_sync/templates/admin/shopify_sync/translation_console.html"
VIEW_FILE = "backend/shopify_sync/views.py"
SMOKE_TEST_FILE = "scripts/smoke_test_translation_console_manual_action_package.py"
SMOKE_TEST_MANAGEMENT_COMMAND_FILE = (
    "backend/shopify_sync/management/commands/"
    "smoke_test_translation_console_manual_action_package.py"
)
SMOKE_TEST_DOCKER_COMMAND = "docker compose exec -T web python manage.py smoke_test_translation_console_manual_action_package --live-dry-run"
SMOKE_TEST_MANAGE_COMMAND = (
    "python manage.py smoke_test_translation_console_manual_action_package --live-dry-run"
)

TEMPLATE_REQUIRED_TEXT = [
    "generate_translation_locked_executor_shell",
    "generate_translation_real_write_executor_dry_run",
    "generate_translation_real_write_manual_action_package",
    "Generate locked executor shell report",
    "Generate real write executor dry-run package",
    "Generate real write manual action package",
    "No Shopify write",
    "dry-run",
    "manual ACK",
    "future phase",
]

VIEW_REQUIRED_ACTIONS = [
    "generate_translation_locked_executor_shell",
    "generate_translation_real_write_executor_dry_run",
    "generate_translation_real_write_manual_action_package",
]

SMOKE_TEST_REQUIRED_TEXT = [
    "--static-only",
    "--live-dry-run",
    "--use-docker",
    "missing_django_on_host",
    SMOKE_TEST_DOCKER_COMMAND,
    SMOKE_TEST_MANAGE_COMMAND,
    "docker_management_command_failed",
    "management_command_not_available",
]

MANAGEMENT_COMMAND_REQUIRED_TEXT = [
    "class Command",
    "--live-dry-run",
    "generate_selected_product_missing_translation_draft_package",
    "build_selected_product_translation_real_write_manual_action_package",
    "shopify_write_performed",
    "translations_register_called",
    "no_new_shopify_writes_performed",
]

HELPER_FIELD_FILES = [
    "backend/shopify_sync/translation_locked_executor.py",
    "backend/shopify_sync/translation_real_write_executor.py",
    "backend/shopify_sync/translation_real_write_manual_action_package.py",
]

HELPER_REQUIRED_FIELDS = [
    "real_write_allowed",
    "future_write_allowed",
    "dangerous_ack_effective",
    "manual_ack_effective",
    "translations_register_called",
    "shopify_write_performed",
    "mutation_performed",
    "real_apply_performed",
    "rollback_performed",
    "no_new_shopify_writes_performed",
    "all_new_actions_no_write_confirmed",
]

DANGEROUS_SCAN_FILES = [
    "backend/shopify_sync/views.py",
    "backend/shopify_sync/translation_locked_executor.py",
    "backend/shopify_sync/translation_real_write_executor.py",
    "backend/shopify_sync/translation_real_write_manual_action_package.py",
    TEMPLATE_FILE,
    "AGENTS.md",
    "remote_approval/LOCAL_APPROVAL_WORKFLOW.md",
]

DANGEROUS_TRUE_FIELDS = [
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

SHOPIFY_CALL_SCAN_FILES = [
    "backend/shopify_sync/translation_locked_execution_plan.py",
    "backend/shopify_sync/translation_locked_executor.py",
    "backend/shopify_sync/translation_real_write_executor.py",
    "backend/shopify_sync/translation_real_write_manual_action_package.py",
]

DISALLOWED_CALL_PATTERNS = [
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

SECRET_SCAN_FILES = [
    "backend/shopify_sync/translation_real_write_manual_action_package.py",
    "scripts/validate_translation_console_phase.py",
]


def main():
    blocking_conditions = []
    checked_files = sorted(
        {
            *COMPILE_FILES,
            TEMPLATE_FILE,
            VIEW_FILE,
            SMOKE_TEST_FILE,
            *HELPER_FIELD_FILES,
            *DANGEROUS_SCAN_FILES,
            *SHOPIFY_CALL_SCAN_FILES,
            *SECRET_SCAN_FILES,
        }
    )

    compile_results = _compile_files(blocking_conditions)
    template_checks = _check_required_text(TEMPLATE_FILE, TEMPLATE_REQUIRED_TEXT)
    _append_missing(blocking_conditions, "template_missing", template_checks)
    view_action_checks = _check_required_text(VIEW_FILE, VIEW_REQUIRED_ACTIONS)
    _append_missing(blocking_conditions, "view_action_missing", view_action_checks)
    smoke_test_script_checks = _check_required_text(
        SMOKE_TEST_FILE, SMOKE_TEST_REQUIRED_TEXT
    )
    _append_missing(
        blocking_conditions, "smoke_test_script_missing", smoke_test_script_checks
    )
    management_command_checks = _check_required_text(
        SMOKE_TEST_MANAGEMENT_COMMAND_FILE, MANAGEMENT_COMMAND_REQUIRED_TEXT
    )
    _append_missing(
        blocking_conditions, "management_command_missing", management_command_checks
    )
    helper_field_checks = _check_helper_fields()
    _append_missing(blocking_conditions, "helper_field_missing", helper_field_checks)
    dangerous_flag_checks = _check_dangerous_flags()
    blocking_conditions.extend(dangerous_flag_checks["blocking_conditions"])
    shopify_call_checks = _check_shopify_calls()
    blocking_conditions.extend(shopify_call_checks["blocking_conditions"])
    secret_safety_checks = _check_secret_safety()
    blocking_conditions.extend(secret_safety_checks["blocking_conditions"])

    blocking_conditions = _unique(blocking_conditions)
    validation_status = "passed" if not blocking_conditions else "failed"
    no_write_confirmed = not blocking_conditions
    payload = {
        "validation_status": validation_status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checked_files": checked_files,
        "compile_results": compile_results,
        "template_checks": template_checks,
        "view_action_checks": view_action_checks,
        "smoke_test_script_checks": smoke_test_script_checks,
        "management_command_checks": management_command_checks,
        "helper_field_checks": helper_field_checks,
        "dangerous_flag_checks": dangerous_flag_checks,
        "shopify_call_checks": shopify_call_checks,
        "secret_safety_checks": secret_safety_checks,
        "blocking_conditions": blocking_conditions,
        "no_write_confirmed": no_write_confirmed,
        "json_report_path": str(JSON_REPORT_PATH.relative_to(ROOT)),
        "html_report_path": str(HTML_REPORT_PATH.relative_to(ROOT)),
    }
    _write_reports(payload)
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if no_write_confirmed else 1


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
            results[rel_path] = {
                "status": "failed",
                "error": str(exc),
            }
            blocking_conditions.append(f"compile_failed:{rel_path}")
        else:
            results[rel_path] = {"status": "passed"}
    return results


def _check_required_text(rel_path, required_text):
    text = _read_text(rel_path)
    lowered = text.lower()
    checks = {}
    for item in required_text:
        checks[item] = {
            "present": item.lower() in lowered,
        }
    return checks


def _check_helper_fields():
    combined = "\n".join(_read_text(path) for path in HELPER_FIELD_FILES)
    return {
        field: {"present": field in combined}
        for field in HELPER_REQUIRED_FIELDS
    }


def _check_dangerous_flags():
    findings = []
    for rel_path in DANGEROUS_SCAN_FILES:
        text = _dangerous_scan_text(rel_path)
        for field in DANGEROUS_TRUE_FIELDS:
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
    return {
        "status": "passed" if not findings else "failed",
        "findings": findings,
        "blocking_conditions": [
            f"dangerous_true_flag:{item['file']}:{item['field']}:{item['line']}"
            for item in findings
        ],
    }


def _dangerous_scan_text(rel_path):
    text = _read_text(rel_path)
    if rel_path == "AGENTS.md":
        lines = [
            line
            for line in text.splitlines()
            if (
                "Phase 15.7" in line
                or "Phase 16.0" in line
                or "Phase 16.1" in line
            )
        ]
        return "\n".join(lines)
    if rel_path == "remote_approval/LOCAL_APPROVAL_WORKFLOW.md":
        start = text.find("### Selected Product Locked Executor Shell")
        end = text.find("### Shopify Review Request Automation Preparation")
        if start >= 0 and end > start:
            return text[start:end]
    return text


def _check_shopify_calls():
    findings = []
    for rel_path in SHOPIFY_CALL_SCAN_FILES:
        text = _read_text(rel_path)
        for raw_pattern in DISALLOWED_CALL_PATTERNS:
            pattern = re.compile(raw_pattern)
            for match in pattern.finditer(text):
                findings.append(
                    {
                        "file": rel_path,
                        "pattern": raw_pattern,
                        "line": _line_number(text, match.start()),
                        "match": match.group(0),
                    }
                )
    return {
        "status": "passed" if not findings else "failed",
        "allowed_preview_terms": [
            "planned_mutation_name",
            "planned_graphql_variables_preview",
            "planned_translation_inputs_preview",
            "future command preview",
            "manual command preview",
        ],
        "findings": findings,
        "blocking_conditions": [
            f"disallowed_shopify_call:{item['file']}:{item['line']}:{item['match']}"
            for item in findings
        ],
    }


def _check_secret_safety():
    # Build sensitive terms without embedding exact secret names in this validator.
    sensitive_terms = [
        "SHOPIFY_" + "ACCESS_TOKEN",
        "OPENAI_" + "API_KEY",
        "access" + "_token",
        "os." + "getenv",
        "." + "env",
        "print " + "token",
        "token " + "preview",
    ]
    findings = []
    for rel_path in SECRET_SCAN_FILES:
        text = _read_text(rel_path)
        for term in sensitive_terms:
            index = text.find(term)
            if index >= 0:
                findings.append(
                    {
                        "file": rel_path,
                        "line": _line_number(text, index),
                        "term_length": len(term),
                    }
                )
    return {
        "status": "passed" if not findings else "failed",
        "scope": SECRET_SCAN_FILES,
        "findings": findings,
        "blocking_conditions": [
            f"secret_safety_term_found:{item['file']}:{item['line']}"
            for item in findings
        ],
    }


def _append_missing(blocking_conditions, prefix, checks):
    for item, result in checks.items():
        if not result.get("present"):
            blocking_conditions.append(f"{prefix}:{item}")


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
            ("Checked At", "checked_at"),
            ("No Write Confirmed", "no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
            ("JSON Report Path", "json_report_path"),
            ("HTML Report Path", "html_report_path"),
        ]
    )
    section_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Compile Results", "compile_results"),
            ("Template Checks", "template_checks"),
            ("View Action Checks", "view_action_checks"),
            ("Smoke Test Script Checks", "smoke_test_script_checks"),
            ("Management Command Checks", "management_command_checks"),
            ("Helper Field Checks", "helper_field_checks"),
            ("Dangerous Flag Checks", "dangerous_flag_checks"),
            ("Shopify Call Checks", "shopify_call_checks"),
            ("Secret Safety Checks", "secret_safety_checks"),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Translation Console Local Validation</title></head>
<body>
  <h1>Translation Console Local Validation</h1>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Checks</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{section_rows}</tbody></table>
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
