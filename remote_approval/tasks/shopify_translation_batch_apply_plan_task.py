import json
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_batch_apply_plan"
COMMAND_LABEL = "shopify_translation_batch_apply_plan_from_review"
SOURCE_REVIEW_PATH = LOG_DIR / "shopify_translation_batch_multi_locale_dry_run_review.json"
PLAN_JSON_PATH = LOG_DIR / "shopify_translation_batch_apply_plan.json"
PLAN_HTML_PATH = LOG_DIR / "shopify_translation_batch_apply_plan.html"
MAX_PRODUCTS = 3
MAX_LOCALES = 5
REQUIRED_SOURCE_TASK = "shopify_translation_batch_multi_locale_dry_run"
REQUIRED_MODE = "dry-run"
EXPECTED_FIELDS = ["title", "body_html", "meta_title", "meta_description"]


def run_shopify_translation_batch_apply_plan_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    source_review = {}
    source_parse_error = ""

    try:
        source_review = _read_source_review(SOURCE_REVIEW_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        source_parse_error = f"Could not parse source batch dry-run review JSON: {exc}"
        validation_errors.append("review_json_unparseable")

    if source_review:
        validation_errors.extend(_validate_source_review(source_review))

    plan_items = _build_plan_items(source_review) if source_review and not validation_errors else []
    recommendation_counts = _recommendation_counts(plan_items)
    ready_count = recommendation_counts.get("ready_for_apply", 0)
    needs_review_count = recommendation_counts.get("needs_review", 0)
    blocked_count = recommendation_counts.get("blocked", 0)
    success = not validation_errors
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "mode": mode,
        "command_label": COMMAND_LABEL,
        "source_review_path": str(SOURCE_REVIEW_PATH),
        "json_plan_path": str(PLAN_JSON_PATH),
        "html_plan_path": str(PLAN_HTML_PATH),
        "source_review_task": source_review.get("task") if source_review else "",
        "source_review_mode": source_review.get("mode") if source_review else "",
        "source_review_timestamp": source_review.get("timestamp") if source_review else "",
        "source_product_count": source_review.get("product_count", 0) if source_review else 0,
        "source_locale_count": source_review.get("locale_count", 0) if source_review else 0,
        "source_total_runs": source_review.get("total_runs", 0) if source_review else 0,
        "source_success_count": source_review.get("success_count", 0) if source_review else 0,
        "source_failed_count": source_review.get("failed_count", 0) if source_review else 0,
        "source_all_no_write_confirmed": bool(source_review.get("all_no_write_confirmed")) if source_review else False,
        "source_no_shopify_writes_performed": bool(source_review.get("no_shopify_writes_performed"))
        if source_review
        else False,
        "source_qa_gate_passed": bool(source_review.get("qa_gate_passed")) if source_review else False,
        "validation_errors": validation_errors,
        "source_parse_error": source_parse_error,
        "success": success,
        "plan_item_count": len(plan_items),
        "ready_for_apply_count": ready_count,
        "needs_review_count": needs_review_count,
        "blocked_count": blocked_count,
        "eligible_for_apply_count": sum(1 for item in plan_items if item["eligible_for_apply"]),
        "recommendation_counts": recommendation_counts,
        "plan_items": plan_items,
        "detected_issue_summary": _issue_summary(success, validation_errors, recommendation_counts),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
        "safety": {
            "plan_only": True,
            "dry_run_only": True,
            "shopify_writes_allowed": False,
            "register_translations_allowed": False,
            "publish_allowed": False,
            "apply_allowed": False,
            "update_allowed": False,
            "database_writes_allowed": False,
            "git_push_allowed": False,
            "auto_scan_all_products_allowed": False,
            "max_products": MAX_PRODUCTS,
            "max_locales": MAX_LOCALES,
            "source_all_no_write_confirmed_required": True,
        },
    }
    json_plan_path = _write_json_plan(payload)
    html_plan_path = _write_html_plan(payload)
    return {
        "task_type": TASK_NAME,
        "success": success,
        "exit_code": 0 if success else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_plan_path),
        "json_plan_path": str(json_plan_path),
        "html_plan_path": str(html_plan_path),
        "source_review_path": str(SOURCE_REVIEW_PATH),
        "plan_item_count": len(plan_items),
        "ready_for_apply_count": ready_count,
        "needs_review_count": needs_review_count,
        "blocked_count": blocked_count,
        "all_no_write_confirmed": payload["source_all_no_write_confirmed"],
        "no_shopify_writes_performed": True,
        "validation_errors_count": len(validation_errors),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_plan_path, html_plan_path),
    }


def _read_source_review(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_source_review(review: dict) -> list[str]:
    errors = []
    checks = [
        ("task", review.get("task") == REQUIRED_SOURCE_TASK),
        ("mode", review.get("mode") == REQUIRED_MODE),
        ("success_count", int(review.get("success_count") or 0) > 0),
        ("failed_count", int(review.get("failed_count") or 0) == 0),
        ("all_no_write_confirmed", review.get("all_no_write_confirmed") is True),
        ("no_shopify_writes_performed", review.get("no_shopify_writes_performed") is True),
        ("product_count", int(review.get("product_count") or 0) <= MAX_PRODUCTS),
        ("locale_count", int(review.get("locale_count") or 0) <= MAX_LOCALES),
    ]
    for name, passed in checks:
        if not passed:
            errors.append(f"source_{name}_invalid")
    return errors


def _build_plan_items(review: dict) -> list[dict]:
    return [_build_plan_item(item) for item in review.get("results", [])]


def _build_plan_item(item: dict) -> dict:
    reason = []
    qa_status = item.get("qa_status") or "unknown"
    success = bool(item.get("success"))
    no_write = bool(item.get("no_shopify_writes_confirmed"))
    warnings_count = int(item.get("warnings_count") or 0)
    qa_warnings = [str(value) for value in item.get("qa_warnings") or []]
    qa_failures = [str(value) for value in item.get("qa_failures") or []]

    if not success:
        reason.append(f"Dry-run failed: {item.get('failure_type') or 'unknown'}")
    if not no_write:
        reason.append("No-write confirmation is missing")
    if qa_status != "pass":
        reason.append(f"QA status is {qa_status}")
    if warnings_count:
        reason.append(f"Translation command emitted {warnings_count} warning(s)")
    reason.extend(qa_warnings)
    reason.extend(qa_failures)

    recommendation = "ready_for_apply"
    eligible_for_apply = True
    if not success or not no_write or qa_status == "fail" or qa_failures:
        recommendation = "blocked"
        eligible_for_apply = False
    elif qa_status == "warning" or warnings_count or qa_warnings:
        recommendation = "needs_review"
        eligible_for_apply = False

    return {
        "product_id": item.get("product_id", ""),
        "locale": item.get("locale", ""),
        "qa_status": qa_status,
        "recommendation": recommendation,
        "eligible_for_apply": eligible_for_apply,
        "manual_decision": "pending",
        "reason": _unique(reason) or ["All dry-run and QA gates passed"],
        "fields_included": list(item.get("payload_keys") or []),
        "expected_fields": EXPECTED_FIELDS,
        "warnings_count": warnings_count,
        "qa_warnings": qa_warnings,
        "qa_failures": qa_failures,
        "qa_checks": item.get("qa_checks") or {},
        "title_chars": item.get("title_chars", 0),
        "meta_title_chars": item.get("meta_title_chars", 0),
        "meta_description_chars": item.get("meta_description_chars", 0),
        "review_file_path": item.get("review_file_path", ""),
        "no_shopify_writes_confirmed": no_write,
        "source_success": success,
    }


def _recommendation_counts(plan_items: list[dict]) -> dict:
    counts = {"ready_for_apply": 0, "needs_review": 0, "blocked": 0}
    for item in plan_items:
        recommendation = item.get("recommendation") or "blocked"
        counts[recommendation] = counts.get(recommendation, 0) + 1
    return counts


def _write_json_plan(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    PLAN_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(PLAN_JSON_PATH.read_text(encoding="utf-8"))
    return PLAN_JSON_PATH


def _write_html_plan(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_HTML_PATH.write_text(_render_html_plan(payload), encoding="utf-8")
    return PLAN_HTML_PATH


def _render_html_plan(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    rows = "\n".join(_render_item_row(item) for item in payload.get("plan_items", []))
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Timestamp", "timestamp"),
            ("Source Review", "source_review_path"),
            ("Source Products", "source_product_count"),
            ("Source Locales", "source_locale_count"),
            ("Source Success Count", "source_success_count"),
            ("Source Failed Count", "source_failed_count"),
            ("All No-Write Confirmed", "source_all_no_write_confirmed"),
            ("Plan Items", "plan_item_count"),
            ("Ready For Apply", "ready_for_apply_count"),
            ("Needs Review", "needs_review_count"),
            ("Blocked", "blocked_count"),
            ("Validation Errors", "validation_errors"),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Translation Batch Apply Plan</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; background: #fff; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f6f8fa; }}
    .status {{ padding: 12px 14px; border-radius: 6px; font-weight: 700; margin: 12px 0; }}
    .status.pass {{ background: #dafbe1; color: #116329; }}
    .status.fail {{ background: #ffebe9; color: #82071e; }}
    .path {{ font-family: Consolas, monospace; overflow-wrap: anywhere; }}
    .ready {{ color: #116329; font-weight: 700; }}
    .review {{ color: #7d4e00; font-weight: 700; }}
    .blocked {{ color: #82071e; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>Shopify Translation Batch Apply Plan</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Plan Items</h2>
  <table>
    <thead>
      <tr>
        <th>Product ID</th><th>Locale</th><th>QA Status</th><th>Recommendation</th>
        <th>Eligible</th><th>Fields</th><th>Reasons</th><th>Review File</th>
      </tr>
    </thead>
    <tbody>{rows or _empty_row(8, "No plan items.")}</tbody>
  </table>
  <h2>Safety</h2>
  <ul>
    <li>This plan is review-only.</li>
    <li>No Shopify writes were performed.</li>
    <li>Apply, publish, update, mutation, and translationsRegister are not available in this task.</li>
  </ul>
</body>
</html>
"""


def _render_item_row(item: dict) -> str:
    rec = item.get("recommendation", "")
    rec_class = {
        "ready_for_apply": "ready",
        "needs_review": "review",
        "blocked": "blocked",
    }.get(rec, "")
    return (
        "<tr>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{escape(str(item.get('qa_status', '')))}</td>"
        f"<td class=\"{rec_class}\">{escape(str(rec))}</td>"
        f"<td>{'true' if item.get('eligible_for_apply') else 'false'}</td>"
        f"<td>{escape(', '.join(item.get('fields_included') or []))}</td>"
        f"<td>{escape('; '.join(item.get('reason') or []))}</td>"
        f"<td class=\"path\">{escape(str(item.get('review_file_path', '')))}</td>"
        "</tr>"
    )


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _empty_row(colspan: int, message: str) -> str:
    return f"<tr><td colspan=\"{colspan}\">{escape(message)}</td></tr>"


def _issue_summary(success: bool, validation_errors: list[str], counts: dict) -> str:
    if not success:
        return "Apply plan was not generated from a valid batch dry-run review: " + ", ".join(validation_errors)
    return (
        "Apply plan generated from dry-run review. "
        f"Ready: {counts.get('ready_for_apply', 0)}, "
        f"needs review: {counts.get('needs_review', 0)}, "
        f"blocked: {counts.get('blocked', 0)}. No Shopify writes performed."
    )


def _build_approval_message(payload: dict, json_plan_path: Path, html_plan_path: Path) -> str:
    return (
        "Shopify batch translation apply plan generated.\n"
        f"Source review: {payload.get('source_review_path')}\n"
        f"Plan items: {payload.get('plan_item_count')}\n"
        f"Ready for apply: {payload.get('ready_for_apply_count')}\n"
        f"Needs review: {payload.get('needs_review_count')}\n"
        f"Blocked: {payload.get('blocked_count')}\n"
        f"Validation errors: {len(payload.get('validation_errors') or [])}\n"
        "Plan JSON:\n"
        f"{json_plan_path}\n\n"
        "Plan HTML:\n"
        f"{html_plan_path}\n"
        "No Shopify writes performed by this task.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep plan files\n"
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
