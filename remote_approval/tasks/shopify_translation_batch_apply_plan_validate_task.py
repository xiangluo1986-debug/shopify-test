import json
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_translation_batch_apply_plan_validate"
COMMAND_LABEL = "shopify_translation_batch_apply_plan_manual_decision_validation"
APPLY_PLAN_JSON_PATH = LOG_DIR / "shopify_translation_batch_apply_plan.json"
VALIDATION_JSON_PATH = LOG_DIR / "shopify_translation_batch_apply_plan_validation.json"
VALIDATION_HTML_PATH = LOG_DIR / "shopify_translation_batch_apply_plan_validation.html"
EXPECTED_PLAN_TASK = "shopify_translation_batch_apply_plan"
REQUIRED_MODE = "dry-run"
MAX_PRODUCTS = 3
MAX_LOCALES = 5
MAX_PLAN_ITEMS = MAX_PRODUCTS * MAX_LOCALES
ALLOWED_MANUAL_DECISIONS = ["pending", "approve", "revise", "block"]
APPROVABLE_RECOMMENDATIONS = {"ready_for_human_approval", "ready_for_apply"}
REQUIRED_ITEM_FIELDS = ["product_id", "locale", "recommendation", "qa_status", "manual_decision"]


def run_shopify_translation_batch_apply_plan_validate_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    plan_parse_error = ""
    apply_plan = {}

    try:
        apply_plan = _read_apply_plan(APPLY_PLAN_JSON_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        plan_parse_error = f"Could not parse apply plan JSON: {exc}"
        validation_errors.append("apply_plan_json_invalid")

    if apply_plan:
        validation_errors.extend(_validate_plan_safety(apply_plan))

    plan_items = apply_plan.get("plan_items", []) if isinstance(apply_plan.get("plan_items"), list) else []
    item_results = _validate_plan_items(plan_items, validation_errors) if apply_plan else []
    status_counts = _status_counts(item_results)
    validation_warning_count = sum(len(item.get("validation_warnings", [])) for item in item_results)
    validation_failure_count = sum(len(item.get("validation_failures", [])) for item in item_results)
    success = not validation_errors
    end_time = utc_now_iso()

    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "mode": mode,
        "command_label": COMMAND_LABEL,
        "source_apply_plan_path": str(APPLY_PLAN_JSON_PATH),
        "json_validation_path": str(VALIDATION_JSON_PATH),
        "html_validation_path": str(VALIDATION_HTML_PATH),
        "success": success,
        "validation_only": True,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": bool(apply_plan.get("all_no_write_confirmed")) if apply_plan else False,
        "apply_performed": False,
        "publish_performed": False,
        "update_performed": False,
        "mutation_performed": False,
        "translations_register_performed": False,
        "source_plan_task": apply_plan.get("task", "") if apply_plan else "",
        "source_plan_mode": apply_plan.get("mode", "") if apply_plan else "",
        "source_plan_success": bool(apply_plan.get("success")) if apply_plan else False,
        "product_count": _product_count(apply_plan, plan_items) if apply_plan else 0,
        "locale_count": _locale_count(apply_plan, plan_items) if apply_plan else 0,
        "total_plan_items": len(plan_items),
        "manual_decision_allowed_values": ALLOWED_MANUAL_DECISIONS,
        "validation_errors": validation_errors,
        "plan_parse_error": plan_parse_error,
        "validation_status_counts": status_counts,
        "validated_for_future_apply_count": status_counts.get("validated_for_future_apply", 0),
        "needs_revision_count": status_counts.get("needs_revision", 0),
        "blocked_count": status_counts.get("blocked", 0),
        "pending_count": status_counts.get("pending", 0),
        "validation_warning_count": validation_warning_count,
        "validation_failure_count": validation_failure_count,
        "items": item_results,
        "detected_issue_summary": _issue_summary(success, validation_errors, status_counts),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
        "safety": {
            "validation_only": True,
            "plan_only": True,
            "dry_run_only": True,
            "shopify_writes_allowed": False,
            "register_translations_allowed": False,
            "publish_allowed": False,
            "apply_allowed": False,
            "update_allowed": False,
            "mutation_allowed": False,
            "database_writes_allowed": False,
            "git_push_allowed": False,
            "auto_scan_all_products_allowed": False,
            "max_products": MAX_PRODUCTS,
            "max_locales": MAX_LOCALES,
            "max_plan_items": MAX_PLAN_ITEMS,
        },
    }
    json_validation_path = _write_json_validation(payload)
    html_validation_path = _write_html_validation(payload)
    return {
        "task_type": TASK_NAME,
        "success": success,
        "exit_code": 0 if success else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_validation_path),
        "json_validation_path": str(json_validation_path),
        "html_validation_path": str(html_validation_path),
        "source_apply_plan_path": str(APPLY_PLAN_JSON_PATH),
        "validation_only": True,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": payload["all_no_write_confirmed"],
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
        "total_plan_items": len(plan_items),
        "validated_for_future_apply_count": payload["validated_for_future_apply_count"],
        "needs_revision_count": payload["needs_revision_count"],
        "blocked_count": payload["blocked_count"],
        "pending_count": payload["pending_count"],
        "validation_errors_count": len(validation_errors),
        "validation_warning_count": validation_warning_count,
        "validation_failure_count": validation_failure_count,
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_validation_path, html_validation_path),
    }


def _read_apply_plan(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_plan_safety(plan: dict) -> list[str]:
    errors = []
    unsafe_checks = [
        ("task", plan.get("task") == EXPECTED_PLAN_TASK),
        ("mode", plan.get("mode") == REQUIRED_MODE),
        ("apply_performed", plan.get("apply_performed") is False),
        ("publish_performed", plan.get("publish_performed") is False),
        ("translations_register_performed", plan.get("translations_register_performed") is False),
        ("no_shopify_writes_performed", plan.get("no_shopify_writes_performed") is True),
        ("all_no_write_confirmed", plan.get("all_no_write_confirmed") is True),
    ]
    for name, passed in unsafe_checks:
        if not passed:
            if name in {"no_shopify_writes_performed", "all_no_write_confirmed"}:
                errors.append("no_write_not_confirmed")
            else:
                errors.append(f"unsafe_apply_plan_{name}")

    plan_items = plan.get("plan_items")
    if not isinstance(plan_items, list):
        errors.append("unsafe_apply_plan_plan_items")
        plan_items = []

    product_count = _product_count(plan, plan_items)
    locale_count = _locale_count(plan, plan_items)
    if product_count > MAX_PRODUCTS or locale_count > MAX_LOCALES or len(plan_items) > MAX_PLAN_ITEMS:
        errors.append("product_or_locale_limit_exceeded")
    return _unique(errors)


def _validate_plan_items(plan_items: list[dict], validation_errors: list[str]) -> list[dict]:
    results = []
    for index, item in enumerate(plan_items):
        item_result = _validate_plan_item(item, index)
        results.append(item_result)
        if item_result.get("invalid_manual_decision"):
            validation_errors.append("invalid_manual_decision")
        if item_result.get("missing_required_fields"):
            validation_errors.append("unsafe_apply_plan_item_missing_fields")
    return results


def _validate_plan_item(item: dict, index: int) -> dict:
    missing_fields = [field for field in REQUIRED_ITEM_FIELDS if not item.get(field)]
    manual_decision = str(item.get("manual_decision", "")).strip()
    validation_warnings = []
    validation_failures = []
    invalid_manual_decision = False

    if manual_decision not in ALLOWED_MANUAL_DECISIONS:
        invalid_manual_decision = True
        validation_failures.append(f"Invalid manual_decision: {manual_decision or '<empty>'}")

    recommendation = str(item.get("recommendation", ""))
    qa_status = str(item.get("qa_status", ""))
    eligible_for_apply = bool(item.get("eligible_for_apply"))
    qa_failures = [str(value) for value in item.get("qa_failures") or []]
    no_write_confirmed = bool(item.get("no_shopify_writes_confirmed"))
    manual_reviewer = str(item.get("manual_reviewer", "") or "").strip()
    manual_review_notes = str(item.get("manual_review_notes", "") or "").strip()

    validation_status = "blocked"
    eligible_for_future_apply = False
    if invalid_manual_decision:
        validation_status = "blocked"
    elif manual_decision == "approve":
        validation_failures.extend(
            _approve_failures(
                recommendation=recommendation,
                qa_status=qa_status,
                eligible_for_apply=eligible_for_apply,
                qa_failures=qa_failures,
                no_write_confirmed=no_write_confirmed,
            )
        )
        if validation_failures:
            validation_status = "blocked"
        else:
            validation_status = "validated_for_future_apply"
            eligible_for_future_apply = True
            if not manual_reviewer:
                validation_warnings.append("manual_reviewer is recommended before any future apply task")
    elif manual_decision == "revise":
        validation_status = "needs_revision"
    elif manual_decision == "block":
        validation_status = "blocked"
    else:
        validation_status = "pending"

    if missing_fields:
        validation_failures.append("Missing required item fields: " + ", ".join(missing_fields))

    return {
        "index": index,
        "product_id": item.get("product_id", ""),
        "locale": item.get("locale", ""),
        "recommendation": recommendation,
        "qa_status": qa_status,
        "manual_decision": manual_decision,
        "manual_reviewer": manual_reviewer,
        "manual_review_notes": manual_review_notes,
        "validation_status": validation_status,
        "eligible_for_future_apply": eligible_for_future_apply,
        "validation_warnings": _unique(validation_warnings),
        "validation_failures": _unique(validation_failures),
        "missing_required_fields": missing_fields,
        "invalid_manual_decision": invalid_manual_decision,
        "eligible_for_apply": eligible_for_apply,
        "qa_failures": qa_failures,
        "no_shopify_writes_confirmed": no_write_confirmed,
        "review_file_path": item.get("review_file_path", ""),
    }


def _approve_failures(
    recommendation: str,
    qa_status: str,
    eligible_for_apply: bool,
    qa_failures: list[str],
    no_write_confirmed: bool,
) -> list[str]:
    failures = []
    if recommendation not in APPROVABLE_RECOMMENDATIONS:
        failures.append("manual_decision=approve is only allowed for ready_for_human_approval items")
    if qa_status != "pass":
        failures.append("manual_decision=approve requires qa_status=pass")
    if not eligible_for_apply:
        failures.append("manual_decision=approve requires eligible_for_apply=true")
    if qa_failures:
        failures.append("manual_decision=approve requires qa_failures to be empty")
    if not no_write_confirmed:
        failures.append("manual_decision=approve requires no_shopify_writes_confirmed=true")
    return failures


def _product_count(plan: dict, plan_items: list[dict]) -> int:
    explicit = plan.get("product_count", plan.get("source_product_count"))
    try:
        explicit_count = int(explicit)
    except (TypeError, ValueError):
        explicit_count = 0
    if explicit_count:
        return explicit_count
    return len({str(item.get("product_id", "")) for item in plan_items if item.get("product_id")})


def _locale_count(plan: dict, plan_items: list[dict]) -> int:
    explicit = plan.get("locale_count", plan.get("source_locale_count"))
    try:
        explicit_count = int(explicit)
    except (TypeError, ValueError):
        explicit_count = 0
    if explicit_count:
        return explicit_count
    return len({str(item.get("locale", "")) for item in plan_items if item.get("locale")})


def _status_counts(items: list[dict]) -> dict:
    counts = {
        "validated_for_future_apply": 0,
        "needs_revision": 0,
        "blocked": 0,
        "pending": 0,
    }
    for item in items:
        status = item.get("validation_status", "blocked")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _write_json_validation(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    VALIDATION_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(VALIDATION_JSON_PATH.read_text(encoding="utf-8"))
    return VALIDATION_JSON_PATH


def _write_html_validation(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATION_HTML_PATH.write_text(_render_html_validation(payload), encoding="utf-8")
    return VALIDATION_HTML_PATH


def _render_html_validation(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    rows = "\n".join(_render_item_row(item) for item in payload.get("items", []))
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Timestamp", "timestamp"),
            ("Source Apply Plan", "source_apply_plan_path"),
            ("Product Count", "product_count"),
            ("Locale Count", "locale_count"),
            ("Total Plan Items", "total_plan_items"),
            ("Validated For Future Apply", "validated_for_future_apply_count"),
            ("Needs Revision", "needs_revision_count"),
            ("Blocked", "blocked_count"),
            ("Pending", "pending_count"),
            ("Validation Warnings", "validation_warning_count"),
            ("Validation Failures", "validation_failure_count"),
            ("All No-Write Confirmed", "all_no_write_confirmed"),
            ("No Shopify Writes Performed", "no_shopify_writes_performed"),
            ("Apply Performed", "apply_performed"),
            ("Publish Performed", "publish_performed"),
            ("Translations Register Performed", "translations_register_performed"),
            ("Validation Errors", "validation_errors"),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Translation Apply Plan Validation</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; background: #fff; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f6f8fa; }}
    .status {{ padding: 12px 14px; border-radius: 6px; font-weight: 700; margin: 12px 0; }}
    .status.pass {{ background: #dafbe1; color: #116329; }}
    .status.fail {{ background: #ffebe9; color: #82071e; }}
    .path {{ font-family: Consolas, monospace; overflow-wrap: anywhere; }}
    .valid {{ color: #116329; font-weight: 700; }}
    .pending {{ color: #57606a; font-weight: 700; }}
    .revision {{ color: #7d4e00; font-weight: 700; }}
    .blocked {{ color: #82071e; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>Shopify Translation Apply Plan Validation</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Manual Decision Validation</h2>
  <table>
    <thead>
      <tr>
        <th>Product ID</th><th>Locale</th><th>Recommendation</th><th>QA Status</th>
        <th>Manual Decision</th><th>Validation Status</th><th>Eligible For Future Apply</th>
        <th>Reviewer</th><th>Notes</th><th>Warnings</th><th>Failures</th><th>Review File</th>
      </tr>
    </thead>
    <tbody>{rows or _empty_row(12, "No validation items.")}</tbody>
  </table>
  <h2>Safety</h2>
  <ul>
    <li>This task is validation-only.</li>
    <li>No Shopify writes were performed.</li>
    <li>apply_performed=false and publish_performed=false.</li>
    <li>translations_register_performed=false.</li>
    <li>Apply, publish, update, mutation, and translationsRegister are not available in this task.</li>
  </ul>
</body>
</html>
"""


def _render_item_row(item: dict) -> str:
    status = item.get("validation_status", "")
    status_class = {
        "validated_for_future_apply": "valid",
        "needs_revision": "revision",
        "blocked": "blocked",
        "pending": "pending",
    }.get(status, "")
    return (
        "<tr>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{escape(str(item.get('recommendation', '')))}</td>"
        f"<td>{escape(str(item.get('qa_status', '')))}</td>"
        f"<td>{escape(str(item.get('manual_decision', '')))}</td>"
        f"<td class=\"{status_class}\">{escape(str(status))}</td>"
        f"<td>{'true' if item.get('eligible_for_future_apply') else 'false'}</td>"
        f"<td>{escape(str(item.get('manual_reviewer', '')))}</td>"
        f"<td>{escape(str(item.get('manual_review_notes', '')))}</td>"
        f"<td>{escape('; '.join(item.get('validation_warnings') or []))}</td>"
        f"<td>{escape('; '.join(item.get('validation_failures') or []))}</td>"
        f"<td>{_link_for_path(item.get('review_file_path', ''))}</td>"
        "</tr>"
    )


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _empty_row(colspan: int, message: str) -> str:
    return f"<tr><td colspan=\"{colspan}\">{escape(message)}</td></tr>"


def _link_for_path(path: str) -> str:
    if not path:
        return ""
    label = _project_relative_path(path)
    href = _html_relative_href(path)
    return f"<a class=\"path\" href=\"{escape(href)}\">{escape(label)}</a>"


def _project_relative_path(path: str) -> str:
    try:
        absolute = Path(path)
        if not absolute.is_absolute():
            absolute = PROJECT_ROOT / absolute
        return absolute.resolve().relative_to(PROJECT_ROOT).as_posix()
    except (OSError, ValueError):
        return str(path).replace("\\", "/")


def _html_relative_href(path: str) -> str:
    try:
        absolute = Path(path)
        if not absolute.is_absolute():
            absolute = PROJECT_ROOT / absolute
        return absolute.resolve().relative_to(VALIDATION_HTML_PATH.parent.resolve()).as_posix()
    except (OSError, ValueError):
        return _project_relative_path(path)


def _issue_summary(success: bool, validation_errors: list[str], status_counts: dict) -> str:
    if not success:
        return "Apply plan validation failed: " + ", ".join(_unique(validation_errors))
    return (
        "Apply plan validation completed. "
        f"Validated for future apply: {status_counts.get('validated_for_future_apply', 0)}, "
        f"needs revision: {status_counts.get('needs_revision', 0)}, "
        f"blocked: {status_counts.get('blocked', 0)}, "
        f"pending: {status_counts.get('pending', 0)}. No Shopify writes performed."
    )


def _build_approval_message(payload: dict, json_validation_path: Path, html_validation_path: Path) -> str:
    return (
        "Shopify batch translation apply plan validation completed.\n"
        f"Source apply plan: {payload.get('source_apply_plan_path')}\n"
        f"Total plan items: {payload.get('total_plan_items')}\n"
        f"Validated for future apply: {payload.get('validated_for_future_apply_count')}\n"
        f"Needs revision: {payload.get('needs_revision_count')}\n"
        f"Blocked: {payload.get('blocked_count')}\n"
        f"Pending: {payload.get('pending_count')}\n"
        f"Validation errors: {len(payload.get('validation_errors') or [])}\n"
        "Validation JSON:\n"
        f"{json_validation_path}\n\n"
        "Validation HTML:\n"
        f"{html_validation_path}\n"
        "Validation only. No Shopify writes performed by this task.\n"
        "apply_performed=false; publish_performed=false; translationsRegister_performed=false.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep validation files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Write, publish, apply, update, mutation, translationsRegister, commit, and push are not allowed."
    )


def _unique(values: list[str]) -> list[str]:
    unique_values = []
    for value in values:
        if value and value not in unique_values:
            unique_values.append(value)
    return unique_values
