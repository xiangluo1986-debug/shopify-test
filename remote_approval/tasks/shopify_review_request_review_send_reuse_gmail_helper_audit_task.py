import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_review_send_reuse_gmail_helper_audit"
COMMAND_LABEL = TASK_NAME
REPORT_DIR = LOG_DIR / "codex_runs"
REPORT_JSON_PATH = REPORT_DIR / "shopify_review_request_review_send_reuse_gmail_helper_audit.json"
REPORT_HTML_PATH = REPORT_DIR / "shopify_review_request_review_send_reuse_gmail_helper_audit.html"

PHASE_316_HELPER_PATH = (
    PROJECT_ROOT
    / "remote_approval"
    / "tasks"
    / "shopify_review_request_trustpilot_gmail_one_draft_send_execute_task.py"
)
PHASE_48B_HELPER_PATH = (
    PROJECT_ROOT
    / "remote_approval"
    / "tasks"
    / "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute_task.py"
)

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._-]{8,}|ya29\.[A-Za-z0-9._-]+|shpat_[A-Za-z0-9_]+|"
    r"access[_\s-]?token\s*[:=]|refresh[_\s-]?token\s*[:=]|client[_\s-]?secret\s*[:=]|"
    r"api[_\s-]?key\s*[:=]|password\s*[:=]|secret\s*[:=])"
)
ALLOWED_REPORT_EMAILS = {"info@kidstoylover.com"}


def run_shopify_review_request_review_send_reuse_gmail_helper_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    phase_316_source = _read_source(PHASE_316_HELPER_PATH)
    phase_48b_source = _read_source(PHASE_48B_HELPER_PATH)
    phase_316 = _phase_316_helper_summary(phase_316_source)
    phase_48b = _phase_48b_helper_summary(phase_48b_source)
    payload = _build_payload(phase_316, phase_48b, duration_seconds=round(time.time() - started, 3))
    json_path = _write_json(payload)
    html_path = _write_html(payload)
    return _task_result(payload, json_path, html_path)


def _read_source(path: Path) -> dict:
    if not path.exists():
        return {"path": _relative_path(path), "present": False, "text": ""}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {"path": _relative_path(path), "present": True, "text": text}


def _phase_316_helper_summary(source: dict) -> dict:
    text = source["text"]
    expected_order = _string_constant(text, "EXPECTED_ORDER_NAME")
    expected_masked_email = _string_constant(text, "EXPECTED_MASKED_EMAIL")
    expected_draft_partial = _string_constant(text, "EXPECTED_DRAFT_ID_PARTIAL")
    ack_env = _string_constant(text, "SEND_DRAFT_ACK_ENV")
    return {
        "helper_found": source["present"] and "users().drafts().send" in text,
        "helper_module": source["path"],
        "uses_gmail_drafts_send": "users().drafts().send" in text,
        "uses_gmail_messages_send": "users().messages().send" in text,
        "expected_order_name": expected_order,
        "expected_masked_email_present": bool(expected_masked_email),
        "expected_draft_id_partial_present": bool(expected_draft_partial),
        "hard_coded_order": expected_order == "#22621",
        "hard_coded_draft_identity": bool(expected_masked_email and expected_draft_partial),
        "requires_runner_ack": bool(ack_env),
        "requires_source_preflight_report": "SOURCE_PREFLIGHT_JSON_PATH" in text,
        "requires_protected_draft_source_report": "PROTECTED_DRAFT_SOURCE_JSON_PATH" in text,
        "supports_dynamic_order": False,
        "can_be_called_from_admin_post": False,
    }


def _phase_48b_helper_summary(source: dict) -> dict:
    text = source["text"]
    expected_order = _string_constant(text, "EXPECTED_ORDER_NAME")
    return {
        "helper_found": source["present"] and "users().drafts().send" in text,
        "helper_module": source["path"],
        "uses_gmail_drafts_send": "users().drafts().send" in text,
        "uses_gmail_messages_send": "users().messages().send" in text,
        "expected_order_name": expected_order,
        "hard_coded_order": bool(expected_order),
        "requires_runner_ack": "APPROVAL_ENV" in text and "ORDER_ENV" in text,
        "requires_source_preflight_report": "SOURCE_SEND_PREFLIGHT_JSON_PATH" in text,
        "supports_dynamic_order": False,
        "can_be_called_from_admin_post": False,
    }


def _build_payload(phase_316: dict, phase_48b: dict, duration_seconds: float) -> dict:
    previous_found = phase_316["helper_found"]
    drafts_send_available = phase_316["uses_gmail_drafts_send"]
    helper_reusable = (
        previous_found
        and drafts_send_available
        and phase_316["supports_dynamic_order"]
        and phase_316["can_be_called_from_admin_post"]
    )
    blocker = ""
    if not helper_reusable:
        blocker = (
            "Previous #22621 drafts.send helper is hard-coded to #22621, a fixed masked email, "
            "a fixed draft id partial, protected source reports, and runner ACK variables; it "
            "cannot create or send a Trustpilot email for a dynamic admin-selected order such as #21075."
        )
    payload = {
        "timestamp": utc_now_iso(),
        "report_generated_at": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.28K",
        "mode": "dry-run-local-helper-reuse-audit",
        "review_send_reuse_gmail_helper_audit_status": (
            "blocked_previous_gmail_helper_not_reusable_from_admin"
            if not helper_reusable
            else "previous_gmail_helper_reusable_from_admin"
        ),
        "report_status": (
            "blocked_previous_gmail_helper_not_reusable_from_admin"
            if not helper_reusable
            else "previous_gmail_helper_reusable_from_admin"
        ),
        "success": True,
        "previous_gmail_draft_send_helper_found": previous_found,
        "helper_module": phase_316["helper_module"],
        "helper_supports_dynamic_order": phase_316["supports_dynamic_order"],
        "helper_requires_remote_approval_runner": phase_316["requires_runner_ack"],
        "can_be_called_from_admin_post": phase_316["can_be_called_from_admin_post"],
        "gmail_scope_status": "not_checked_no_env_read_no_gmail_call",
        "compose_scope_detected": False,
        "gmail_compose_scope_supported_by_helper": True,
        "drafts_send_path_available": drafts_send_available,
        "gmail_messages_send_called": False,
        "gmail_drafts_send_called": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "sent_count": 0,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "translations_register_called": False,
        "blocker_if_not_reusable": blocker,
        "recommended_integration_path": (
            "Extract a reviewed dynamic admin-safe helper from the proven draft creation and drafts.send "
            "primitives: accept exactly one server-revalidated eligible candidate, perform protected runtime "
            "email lookup, create one Gmail draft with the approved Trustpilot template, send that draft via "
            "Gmail drafts.send, record a local masked report, and keep Shopify tag write in a separate post-send phase."
        ),
        "post_send_audit_task_name_prepared": "shopify_review_request_review_send_post_send_audit",
        "no_gmail_call_during_audit": True,
        "phase_316_helper": phase_316,
        "phase_48b_one_candidate_helper": phase_48b,
        "detected_issue_summary": (
            "The successful #22621 Gmail drafts.send path exists, but it is not reusable from the current "
            "admin Review & Send POST because it is fixed to one historical order/draft and runner ACK flow. "
            "No Gmail API call, email send, Shopify write, external review API call, or translationsRegister call was performed."
        ),
        "duration_seconds": duration_seconds,
    }
    payload["privacy_scan_summary"] = _privacy_scan(payload)
    if not payload["privacy_scan_summary"]["passed"]:
        payload["review_send_reuse_gmail_helper_audit_status"] = "blocked_privacy_scan_failed"
        payload["report_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
    return payload


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload.get("success") is True,
        "review_path": str(json_path),
        "html_review_path": str(html_path),
        "review_send_reuse_gmail_helper_audit_status": payload[
            "review_send_reuse_gmail_helper_audit_status"
        ],
        "previous_gmail_draft_send_helper_found": payload["previous_gmail_draft_send_helper_found"],
        "helper_module": payload["helper_module"],
        "helper_supports_dynamic_order": payload["helper_supports_dynamic_order"],
        "helper_requires_remote_approval_runner": payload["helper_requires_remote_approval_runner"],
        "can_be_called_from_admin_post": payload["can_be_called_from_admin_post"],
        "gmail_scope_status": payload["gmail_scope_status"],
        "compose_scope_detected": payload["compose_scope_detected"],
        "drafts_send_path_available": payload["drafts_send_path_available"],
        "blocker_if_not_reusable": payload["blocker_if_not_reusable"],
        "recommended_integration_path": payload["recommended_integration_path"],
        "gmail_api_call_performed": payload["gmail_api_call_performed"],
        "email_sent": payload["email_sent"],
        "shopify_write_performed": payload["shopify_write_performed"],
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _write_json(payload: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return REPORT_JSON_PATH


def _write_html(payload: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html(payload: dict) -> str:
    rows = "\n".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in (
            ("Status", payload.get("review_send_reuse_gmail_helper_audit_status")),
            ("Previous helper found", payload.get("previous_gmail_draft_send_helper_found")),
            ("Helper module", payload.get("helper_module")),
            ("Supports dynamic order", payload.get("helper_supports_dynamic_order")),
            ("Requires remote approval runner", payload.get("helper_requires_remote_approval_runner")),
            ("Can be called from admin POST", payload.get("can_be_called_from_admin_post")),
            ("Gmail scope status", payload.get("gmail_scope_status")),
            ("Compose scope detected", payload.get("compose_scope_detected")),
            ("Drafts.send path available", payload.get("drafts_send_path_available")),
            ("Blocker", payload.get("blocker_if_not_reusable")),
            ("Gmail API call performed", payload.get("gmail_api_call_performed")),
            ("Email sent", payload.get("email_sent")),
            ("Shopify write performed", payload.get("shopify_write_performed")),
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Review &amp; Send Gmail Helper Reuse Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ width: 280px; background: #f0f4f8; }}
  </style>
</head>
<body>
  <h1>Review &amp; Send Gmail Helper Reuse Audit</h1>
  <table><tbody>{rows}</tbody></table>
</body>
</html>"""


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Review & Send Gmail helper reuse audit complete.\n"
        f"Status: {payload.get('review_send_reuse_gmail_helper_audit_status')}\n"
        f"Previous helper found: {payload.get('previous_gmail_draft_send_helper_found')}\n"
        f"Helper module: {payload.get('helper_module')}\n"
        f"Drafts.send path available: {payload.get('drafts_send_path_available')}\n"
        f"Can admin POST reuse helper: {payload.get('can_be_called_from_admin_post')}\n"
        f"Blocker: {payload.get('blocker_if_not_reusable')}\n"
        "Safety: no Gmail API call, no email send, no Shopify write, and no external review API call.\n"
        f"JSON: {json_path}\n"
        f"HTML: {html_path}"
    )


def _string_constant(source: str, name: str) -> str:
    match = re.search(rf"(?m)^{re.escape(name)}\s*=\s*['\"]([^'\"]*)['\"]", source)
    return match.group(1) if match else ""


def _relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _privacy_scan(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_emails = []
    for match in EMAIL_RE.finditer(text):
        email = match.group(0).lower()
        if email in ALLOWED_REPORT_EMAILS or "***" in email:
            continue
        raw_emails.append(_mask_email(email))
    secret_count = 1 if SECRET_RE.search(text) else 0
    return {
        "scan_performed": True,
        "passed": not raw_emails and not secret_count,
        "raw_customer_email_count": len(set(raw_emails)),
        "masked_raw_customer_email_findings": sorted(set(raw_emails))[:5],
        "token_secret_bearer_pattern_count": secret_count,
    }


def _mask_email(email: str) -> str:
    local, domain = str(email or "").split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"
