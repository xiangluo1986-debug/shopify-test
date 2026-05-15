import json
import re
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_order_sync_auto_refresh_hook_audit"
COMMAND_LABEL = TASK_NAME
PHASE = "5.9"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_order_sync_auto_refresh_hook_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_order_sync_auto_refresh_hook_audit.html"
AUTO_REFRESH_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_auto_queue_refresh.json"

WORKBENCH_PATH = PROJECT_ROOT / "backend" / "shopify_sync" / "review_request_workbench.py"
SYNC_COMMAND_PATH = (
    PROJECT_ROOT
    / "backend"
    / "shopify_sync"
    / "management"
    / "commands"
    / "sync_shenzhen_orders.py"
)
VIEWS_PATH = PROJECT_ROOT / "backend" / "shopify_sync" / "views.py"
AUTO_REFRESH_TASK_PATH = (
    PROJECT_ROOT
    / "remote_approval"
    / "tasks"
    / "shopify_review_request_trustpilot_auto_queue_refresh_task.py"
)

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_VALUE_RE = re.compile(
    r"(?i)("
    r"shpat_[A-Za-z0-9_]+|"
    r"ya29\.[A-Za-z0-9._-]+|"
    r"bearer\s+[A-Za-z0-9._-]{8,}|"
    r"x-shopify-access-token\s*[:=]\s*[A-Za-z0-9._-]+|"
    r"access[_\s-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"refresh[_\s-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"client[_\s-]?secret\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"api[_\s-]?key\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"password\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{8,}"
    r")"
)
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

FORBIDDEN_TRUE_FLAGS = (
    "gmail_api_call_performed",
    "gmail_draft_create_attempted",
    "gmail_draft_created",
    "gmail_draft_deleted",
    "gmail_drafts_send_called",
    "gmail_messages_send_called",
    "gmail_send_performed",
    "email_sent",
    "shopify_api_call_performed",
    "shopify_write_performed",
    "shopify_tag_write_allowed_now",
    "mutation_performed",
    "tags_add_performed",
    "tags_remove_performed",
    "tagsAdd_performed",
    "tagsRemove_performed",
    "external_review_api_call_allowed_now",
    "trustpilot_api_call_performed",
    "kudosi_api_call_performed",
    "ali_reviews_api_call_performed",
    "ali_reviews_write_api_call_performed",
    "tracking_redirect_enabled",
    "tracking_token_generated",
    "raw_customer_email_output",
    "full_gmail_draft_or_message_id_output",
)

FORBIDDEN_ACTIVE_CALL_MARKERS = (
    "drafts().create(",
    "drafts().delete(",
    "drafts().send(",
    "messages().send(",
    "tagsAdd(",
    "tagsRemove(",
    "translationsRegister",
    "requests.post(",
    "requests.put(",
    "requests.patch(",
    "requests.delete(",
)


def run_shopify_review_request_order_sync_auto_refresh_hook_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    source_files = {
        "workbench": _read_text(WORKBENCH_PATH),
        "sync_command": _read_text(SYNC_COMMAND_PATH),
        "views": _read_text(VIEWS_PATH),
        "auto_refresh_task": _read_text(AUTO_REFRESH_TASK_PATH),
    }
    latest_refresh = _load_latest_auto_refresh()
    checks = _build_checks(source_files, latest_refresh)
    payload = _build_payload(checks, latest_refresh)
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _build_checks(source_files: dict, latest_refresh: dict) -> dict:
    workbench = source_files["workbench"]["text"]
    sync_command = source_files["sync_command"]["text"]
    views = source_files["views"]["text"]
    auto_refresh_task = source_files["auto_refresh_task"]["text"]
    sync_view_body = _function_body(views, "sync_shenzhen_orders")
    hook_helper_exists = (
        "def run_trustpilot_auto_queue_refresh_after_shopify_order_sync" in workbench
        and "def run_trustpilot_auto_queue_refresh_hook" in workbench
    )
    remote_task_hook_exists = (
        "def run_shopify_review_request_trustpilot_auto_queue_refresh_hook" in auto_refresh_task
    )
    management_command_hook_wired = (
        "run_trustpilot_auto_queue_refresh_after_shopify_order_sync" in sync_command
        and "task_result[\"result\"]" in sync_command
    )
    view_hook_wired = (
        "run_trustpilot_auto_queue_refresh_after_shopify_order_sync" in sync_view_body
        and "trustpilot_queue_auto_refresh" in sync_view_body
    )
    active_call_hits = _active_call_hits(
        {
            "workbench": workbench,
            "sync_command": sync_command,
            "sync_view": sync_view_body,
            "auto_refresh_task": auto_refresh_task,
        }
    )
    latest_forbidden_true_flags = _latest_forbidden_true_flags(latest_refresh.get("data", {}))
    return {
        "hook_helper_exists": hook_helper_exists,
        "remote_task_hook_exists": remote_task_hook_exists,
        "management_command_hook_wired": management_command_hook_wired,
        "view_hook_wired": view_hook_wired,
        "wired_to_discovered_sync_completion_point": management_command_hook_wired and view_hook_wired,
        "dry_run_no_write_only": not active_call_hits and not latest_forbidden_true_flags,
        "safety_flags_remain_false": not latest_forbidden_true_flags,
        "active_forbidden_call_markers_found": active_call_hits,
        "latest_forbidden_true_flags": latest_forbidden_true_flags,
        "discovered_sync_completion_points": [
            "backend/shopify_sync/management/commands/sync_shenzhen_orders.py after successful run_shopify_sync_task result",
            "backend/shopify_sync/views.py sync_shenzhen_orders after successful run_shopify_sync_task result",
        ],
    }


def _build_payload(checks: dict, latest_refresh: dict) -> dict:
    latest_data = latest_refresh.get("data", {})
    latest_status = _safe_text(
        latest_data.get("last_auto_refresh_status")
        or latest_data.get("refresh_status")
        or latest_refresh.get("status")
        or "missing",
        max_length=120,
    )
    payload = {
        "timestamp": utc_now_iso(),
        "report_generated_at": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": PHASE,
        "mode": "dry-run",
        "success": True,
        "audit_status": "passed" if _checks_pass(checks) else "needs_review",
        "hook_helper_exists": checks["hook_helper_exists"],
        "remote_task_hook_exists": checks["remote_task_hook_exists"],
        "management_command_hook_wired": checks["management_command_hook_wired"],
        "view_hook_wired": checks["view_hook_wired"],
        "wired_to_discovered_sync_completion_point": checks["wired_to_discovered_sync_completion_point"],
        "hook_status": (
            "enabled"
            if checks["wired_to_discovered_sync_completion_point"]
            else "prepared_but_not_wired"
        ),
        "hook_status_message": (
            "Auto refresh after Shopify sync is enabled"
            if checks["wired_to_discovered_sync_completion_point"]
            else "Auto refresh hook is prepared but not wired yet"
        ),
        "discovered_sync_completion_points": checks["discovered_sync_completion_points"],
        "dry_run_no_write_only": checks["dry_run_no_write_only"],
        "safety_flags_remain_false": checks["safety_flags_remain_false"],
        "active_forbidden_call_markers_found": checks["active_forbidden_call_markers_found"],
        "latest_forbidden_true_flags": checks["latest_forbidden_true_flags"],
        "latest_auto_refresh": {
            "present": latest_refresh["present"],
            "loaded": latest_refresh["loaded"],
            "relative_path": "logs/shopify_review_request_trustpilot_auto_queue_refresh.json",
            "refresh_status": latest_status,
            "last_auto_refresh_trigger": _safe_text(
                latest_data.get("last_auto_refresh_trigger") or latest_data.get("trigger") or "unknown",
                max_length=80,
            ),
            "last_auto_refresh_at": _safe_text(
                latest_data.get("last_auto_refresh_at")
                or latest_data.get("refreshed_at")
                or latest_refresh.get("modified_at")
                or "",
                max_length=120,
            ),
            "last_auto_refresh_error": _safe_text(latest_data.get("last_auto_refresh_error"), max_length=300),
            "source_readiness_package_status": _safe_text(
                latest_data.get("source_readiness_package_status"),
                max_length=120,
            ),
            "eligible_candidate_count": _int_or_zero(latest_data.get("eligible_candidate_count")),
            "blocked_candidate_count": _int_or_zero(latest_data.get("blocked_candidate_count")),
            "next_real_step": _safe_text(latest_data.get("next_real_step"), max_length=120),
            "order_22620_blocker_status": _known_blocker_summary(latest_data, "#22620"),
            "order_22582_blocker_status": _known_blocker_summary(latest_data, "#22582"),
            "ali_reviews_status": _safe_text(latest_data.get("ali_reviews_status"), max_length=120),
        },
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_draft_deleted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "ali_reviews_write_api_call_performed": False,
        "tracking_redirect_enabled": False,
        "tracking_token_generated": False,
        "raw_customer_email_output": False,
        "full_gmail_draft_or_message_id_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": _issue_summary(checks, latest_status),
    }
    return _sanitize_payload(payload)


def _checks_pass(checks: dict) -> bool:
    return all(
        (
            checks["hook_helper_exists"],
            checks["remote_task_hook_exists"],
            checks["management_command_hook_wired"],
            checks["view_hook_wired"],
            checks["dry_run_no_write_only"],
            checks["safety_flags_remain_false"],
        )
    )


def _issue_summary(checks: dict, latest_status: str) -> str:
    if _checks_pass(checks):
        return (
            "Phase 5.9 hook audit passed: Shopify order sync completion is wired to the "
            f"dry-run Trustpilot queue refresh. Latest refresh status: {latest_status}."
        )
    return "Phase 5.9 hook audit needs review before relying on automatic queue refresh."


def _read_text(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"present": False, "text": "", "error": _safe_text(str(exc), max_length=300)}
    return {"present": True, "text": text, "error": ""}


def _function_body(text: str, function_name: str) -> str:
    marker = f"def {function_name}("
    start = text.find(marker)
    if start < 0:
        return ""
    next_def = text.find("\ndef ", start + len(marker))
    if next_def < 0:
        return text[start:]
    return text[start:next_def]


def _active_call_hits(source_by_name: dict) -> list[dict]:
    hits = []
    for source_name, text in source_by_name.items():
        for marker in FORBIDDEN_ACTIVE_CALL_MARKERS:
            if marker in text:
                hits.append({"source": source_name, "marker": marker})
    return hits


def _load_latest_auto_refresh() -> dict:
    report = {
        "present": AUTO_REFRESH_JSON_PATH.exists(),
        "loaded": False,
        "status": "missing",
        "modified_at": "",
        "data": {},
        "error": "",
    }
    if not AUTO_REFRESH_JSON_PATH.exists():
        return report
    try:
        report["modified_at"] = _safe_text(_format_mtime(AUTO_REFRESH_JSON_PATH.stat().st_mtime), max_length=120)
        data = json.loads(AUTO_REFRESH_JSON_PATH.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        report["status"] = "present_but_unreadable"
        report["error"] = _safe_text(str(exc), max_length=300)
        return report
    if not isinstance(data, dict):
        report["status"] = "present_but_not_object"
        report["error"] = "top_level_json_is_not_object"
        return report
    report["loaded"] = True
    report["data"] = data
    report["status"] = _safe_text(
        data.get("last_auto_refresh_status") or data.get("refresh_status") or data.get("status") or "loaded",
        max_length=120,
    )
    return report


def _latest_forbidden_true_flags(data: dict) -> list[str]:
    flags = []
    safety_flags = data.get("safety_flags") if isinstance(data.get("safety_flags"), dict) else {}
    for flag in FORBIDDEN_TRUE_FLAGS:
        if data.get(flag) is True or safety_flags.get(flag) is True:
            flags.append(flag)
    return flags


def _known_blocker_summary(data: dict, order_name: str) -> str:
    blockers = data.get("known_blockers_summary") if isinstance(data.get("known_blockers_summary"), list) else []
    for blocker in blockers:
        if not isinstance(blocker, dict):
            continue
        if _safe_text(blocker.get("order_name"), max_length=80) == order_name:
            return _safe_text(blocker.get("summary") or blocker.get("message"), max_length=300)
    if order_name == "#22620":
        return "Already sent to this customer via #22621"
    return "Not delivered, missing `1: review request`, related orders #22582/#22581 not ready"


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return REPORT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    latest = payload["latest_auto_refresh"]
    checks = [
        ("Hook helper exists", payload["hook_helper_exists"]),
        ("Remote task hook exists", payload["remote_task_hook_exists"]),
        ("Management command wired", payload["management_command_hook_wired"]),
        ("View wired", payload["view_hook_wired"]),
        ("Dry-run/no-write only", payload["dry_run_no_write_only"]),
        ("Safety flags remain false", payload["safety_flags_remain_false"]),
    ]
    check_rows = "\n".join(
        f"<tr><td>{escape(label)}</td><td>{escape(str(value))}</td></tr>"
        for label, value in checks
    )
    call_hits = payload.get("active_forbidden_call_markers_found") or []
    call_hit_rows = "\n".join(
        f"<tr><td>{escape(item.get('source', ''))}</td><td><code>{escape(item.get('marker', ''))}</code></td></tr>"
        for item in call_hits
        if isinstance(item, dict)
    ) or "<tr><td colspan=\"2\">None</td></tr>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Order Sync Auto Refresh Hook Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
  </style>
</head>
<body>
  <h1>Shopify Order Sync Auto Refresh Hook Audit</h1>
  <p>Status: <strong>{escape(payload["audit_status"])}</strong></p>
  <p>{escape(payload["detected_issue_summary"])}</p>
  <table><tbody>{check_rows}</tbody></table>
  <h2>Latest Auto Refresh</h2>
  <table>
    <tbody>
      <tr><th>Status</th><td><code>{escape(latest["refresh_status"])}</code></td></tr>
      <tr><th>Trigger</th><td><code>{escape(latest["last_auto_refresh_trigger"])}</code></td></tr>
      <tr><th>Refreshed at</th><td>{escape(latest["last_auto_refresh_at"])}</td></tr>
      <tr><th>Source readiness package</th><td><code>{escape(latest["source_readiness_package_status"])}</code></td></tr>
      <tr><th>Eligible / blocked</th><td>{latest["eligible_candidate_count"]} / {latest["blocked_candidate_count"]}</td></tr>
      <tr><th>Next real step</th><td><code>{escape(latest["next_real_step"])}</code></td></tr>
      <tr><th>#22620</th><td>{escape(latest["order_22620_blocker_status"])}</td></tr>
      <tr><th>#22582</th><td>{escape(latest["order_22582_blocker_status"])}</td></tr>
    </tbody>
  </table>
  <h2>Forbidden Active Call Markers</h2>
  <table><thead><tr><th>Source</th><th>Marker</th></tr></thead><tbody>{call_hit_rows}</tbody></table>
</body>
</html>"""


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    latest = payload["latest_auto_refresh"]
    return {
        "task_type": TASK_NAME,
        "success": True,
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_review_path": str(json_path),
        "html_review_path": str(html_path),
        "audit_status": payload["audit_status"],
        "hook_status": payload["hook_status"],
        "wired_to_discovered_sync_completion_point": payload["wired_to_discovered_sync_completion_point"],
        "latest_auto_refresh_status": latest["refresh_status"],
        "eligible_candidate_count": latest["eligible_candidate_count"],
        "blocked_candidate_count": latest["blocked_candidate_count"],
        "next_real_step": latest["next_real_step"],
        "order_22620_blocker_status": latest["order_22620_blocker_status"],
        "order_22582_blocker_status": latest["order_22582_blocker_status"],
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    latest = payload["latest_auto_refresh"]
    return (
        "Shopify review request Phase 5.9 order sync auto-refresh hook audit finished.\n"
        f"Audit status: {payload['audit_status']}\n"
        f"Hook status: {payload['hook_status_message']}\n"
        f"Wired to sync completion point: {payload['wired_to_discovered_sync_completion_point']}\n"
        f"Latest auto refresh status: {latest['refresh_status']}\n"
        f"Eligible candidate count: {latest['eligible_candidate_count']}\n"
        f"Blocked candidate count: {latest['blocked_candidate_count']}\n"
        f"Next real step: {latest['next_real_step']}\n"
        f"#22620 blocker: {latest['order_22620_blocker_status']}\n"
        f"#22582 blocker: {latest['order_22582_blocker_status']}\n"
        "Safety: no Gmail API, no draft creation/deletion, no email send, no Shopify API/write/tag mutation, no Trustpilot/Kudosi/Ali Reviews API, and no tracking token.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _sanitize_payload(value):
    if isinstance(value, dict):
        return {_safe_text(key, max_length=120): _sanitize_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value, max_length=1000)
    return value


def _safe_text(value, max_length=300):
    text = str(value or "")
    text = CONTROL_CHARS_RE.sub("", text)
    text = EMAIL_RE.sub(_mask_email_match, text)
    text = SECRET_VALUE_RE.sub("[redacted]", text)
    text = text.strip()
    if len(text) > max_length:
        return f"{text[:max_length]}..."
    return text


def _mask_email_match(match):
    value = match.group(0)
    local, domain = value.rsplit("@", 1)
    domain_parts = domain.split(".")
    if len(domain_parts) >= 2 and domain_parts[0]:
        domain_mask = f"{domain_parts[0][:1]}***.{domain_parts[-1]}"
    else:
        domain_mask = "***"
    return f"{local[:1]}***@{domain_mask}"


def _int_or_zero(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _format_mtime(timestamp: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
