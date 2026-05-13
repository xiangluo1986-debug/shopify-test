import base64
import json
import os
import re
import time
from email.mime.text import MIMEText
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_draft_create_locked_test"
COMMAND_LABEL = "shopify_review_request_trustpilot_gmail_draft_create_locked_test"

SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_draft_package.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_draft_create_locked_test.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_draft_create_locked_test.html"

CREATE_DRAFTS_ENV = "TRUSTPILOT_GMAIL_CREATE_DRAFTS"
ACK_ENV = "TRUSTPILOT_GMAIL_DRAFT_CREATE_LOCKED_TEST_ACK"
ACK_VALUE = "YES_I_APPROVE_ONE_GMAIL_DRAFT_CREATION"

GMAIL_SEND_FROM = "info@kidstoylover.com"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
TRUSTPILOT_LINK = "https://www.trustpilot.com/evaluate/www.kidstoylover.com"
TRUSTPILOT_TAG = "1: trustpilot"
SUBJECT = "Thank You for Your Support \u2013 We\u2019d Love Your Feedback!"
BODY_TEMPLATE = (
    "Dear {first_name},\n\n"
    "Thank you so much for your continued support and for choosing us again \u2014 it truly means a lot to our team.\n\n"
    "If you have a moment, we would greatly appreciate it if you could leave a quick review of your experience with us. "
    "Your feedback not only helps us improve, but also helps other customers feel confident in choosing us too.\n\n"
    "You can share your thoughts here:\n"
    "\U0001f449 https://www.trustpilot.com/evaluate/www.kidstoylover.com\n\n"
    "Thanks again for being a valued customer. If there's anything else we can assist you with, please don\u2019t hesitate "
    "to let us know.\n\n"
    "Kind Regards,\n"
    "Xiang"
)

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|access[_\s-]?token|api[_\s-]?key|password|secret|bearer\s+[A-Za-z0-9._-]+)"
)


def run_shopify_review_request_trustpilot_gmail_draft_create_locked_test_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_report, source_error = _load_source_report()
    source_ready = _source_ready(source_report, source_error)
    candidates = _candidate_rows(source_report) if source_ready else []
    selected_candidate = _select_candidate(candidates)
    create_enabled = os.environ.get(CREATE_DRAFTS_ENV, "").strip() == "1"
    ack_valid = os.environ.get(ACK_ENV, "").strip() == ACK_VALUE
    gmail_readiness = _gmail_oauth_readiness()
    draft_result = _maybe_create_locked_draft(
        selected_candidate=selected_candidate,
        create_enabled=create_enabled,
        ack_valid=ack_valid,
        gmail_readiness=gmail_readiness,
        source_ready=source_ready,
        source_error=source_error,
    )
    payload = _build_payload(
        source_report=source_report,
        source_error=source_error,
        source_ready=source_ready,
        candidates=candidates,
        selected_candidate=selected_candidate,
        create_enabled=create_enabled,
        ack_valid=ack_valid,
        gmail_readiness=gmail_readiness,
        draft_result=draft_result,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _load_source_report() -> tuple[dict, str]:
    if not SOURCE_JSON_PATH.exists():
        return {}, "blocked_missing_trustpilot_draft_package"
    try:
        return json.loads(SOURCE_JSON_PATH.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"trustpilot_draft_package_json_parse_error: {exc}")


def _source_ready(source_report: dict, source_error: str) -> bool:
    return (
        not source_error
        and source_report.get("task_name") == "shopify_review_request_trustpilot_gmail_draft_package"
        and str(source_report.get("phase")) == "3.1"
        and source_report.get("draft_package_status") == "local_draft_package_only"
        and source_report.get("success") is True
    )


def _candidate_rows(source_report: dict) -> list[dict]:
    candidates = []
    for row in source_report.get("draft_candidates") or []:
        if not isinstance(row, dict):
            continue
        if row.get("blocked_reason"):
            continue
        if row.get("gmail_draft_created") is True:
            continue
        candidates.append(row)
    return candidates


def _select_candidate(candidates: list[dict]) -> dict:
    return candidates[0] if candidates else {}


def _maybe_create_locked_draft(
    selected_candidate: dict,
    create_enabled: bool,
    ack_valid: bool,
    gmail_readiness: dict,
    source_ready: bool,
    source_error: str,
) -> dict:
    result = {
        "draft_create_status": "dry_run_gmail_draft_not_created",
        "gmail_draft_create_attempted": False,
        "gmail_api_call_performed": False,
        "gmail_draft_created": False,
        "gmail_drafts_created_count": 0,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "gmail_draft_id": "",
        "error_sanitized": "",
    }
    if source_error or not source_ready:
        result["draft_create_status"] = "blocked_missing_trustpilot_draft_package"
        return result
    if not selected_candidate:
        result["draft_create_status"] = "blocked_no_trustpilot_draft_candidate"
        return result
    if not create_enabled or not ack_valid:
        result["draft_create_status"] = "dry_run_gmail_draft_not_created"
        return result
    if not gmail_readiness["gmail_oauth_present"] or not gmail_readiness["gmail_scope_configured"]:
        result["draft_create_status"] = "blocked_missing_gmail_oauth"
        return result

    raw_recipient = _raw_recipient_for_gmail(selected_candidate)
    if not raw_recipient:
        result["draft_create_status"] = "blocked_missing_raw_email_for_gmail_draft"
        return result

    try:
        service = _build_gmail_service(gmail_readiness)
        result["gmail_draft_create_attempted"] = True
        result["gmail_api_call_performed"] = True
        response = _create_gmail_draft(service, raw_recipient, selected_candidate)
        result["gmail_draft_created"] = True
        result["gmail_drafts_created_count"] = 1
        result["gmail_draft_id"] = _safe_text(response.get("id", ""))
        result["draft_create_status"] = "gmail_draft_created_locked_test"
    except Exception as exc:  # pragma: no cover - only used when the explicit Gmail draft gate is enabled.
        result["draft_create_status"] = "gmail_draft_create_failed"
        result["error_sanitized"] = _sanitize_text(str(exc))
    return result


def _gmail_oauth_readiness() -> dict:
    env = {
        "send_from": os.environ.get("GMAIL_SEND_FROM", "").strip(),
        "client_id_present": bool(os.environ.get("GOOGLE_GMAIL_CLIENT_ID", "").strip()),
        "client_secret_present": bool(os.environ.get("GOOGLE_GMAIL_CLIENT_SECRET", "").strip()),
        "refresh_token_present": bool(os.environ.get("GOOGLE_GMAIL_REFRESH_TOKEN", "").strip()),
        "scopes": _split_scopes(os.environ.get("GOOGLE_GMAIL_SCOPES", "")),
        "client_id": os.environ.get("GOOGLE_GMAIL_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("GOOGLE_GMAIL_CLIENT_SECRET", "").strip(),
        "refresh_token": os.environ.get("GOOGLE_GMAIL_REFRESH_TOKEN", "").strip(),
    }
    missing = []
    if env["send_from"] != GMAIL_SEND_FROM:
        missing.append("GMAIL_SEND_FROM")
    if not env["client_id_present"]:
        missing.append("GOOGLE_GMAIL_CLIENT_ID")
    if not env["client_secret_present"]:
        missing.append("GOOGLE_GMAIL_CLIENT_SECRET")
    if not env["refresh_token_present"]:
        missing.append("GOOGLE_GMAIL_REFRESH_TOKEN")
    scope_configured = GMAIL_COMPOSE_SCOPE in env["scopes"]
    if not scope_configured:
        missing.append("GOOGLE_GMAIL_SCOPES")
    return {
        "gmail_oauth_present": not missing,
        "gmail_scope_configured": scope_configured,
        "gmail_scope_required": GMAIL_COMPOSE_SCOPE,
        "missing_env_vars": missing,
        "send_from": env["send_from"],
        "client_id": env["client_id"],
        "client_secret": env["client_secret"],
        "refresh_token": env["refresh_token"],
        "scopes": env["scopes"] or [GMAIL_COMPOSE_SCOPE],
    }


def _build_gmail_service(gmail_readiness: dict):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=None,
        refresh_token=gmail_readiness["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=gmail_readiness["client_id"],
        client_secret=gmail_readiness["client_secret"],
        scopes=gmail_readiness["scopes"],
    )
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _create_gmail_draft(service, recipient_email: str, selected_candidate: dict) -> dict:
    body = _body_for_candidate(selected_candidate)
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = recipient_email
    message["from"] = GMAIL_SEND_FROM
    message["subject"] = SUBJECT
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return service.users().drafts().create(userId="me", body={"message": {"raw": raw_message}}).execute()


def _build_payload(
    source_report: dict,
    source_error: str,
    source_ready: bool,
    candidates: list[dict],
    selected_candidate: dict,
    create_enabled: bool,
    ack_valid: bool,
    gmail_readiness: dict,
    draft_result: dict,
    duration_seconds: float,
) -> dict:
    selected_preview = _selected_preview(selected_candidate)
    safety = _safety_summary(draft_result)
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.2",
        "mode": "trustpilot-gmail-draft-create-locked-test",
        "command_label": COMMAND_LABEL,
        "draft_create_status": draft_result["draft_create_status"],
        "success": source_ready
        and draft_result["draft_create_status"]
        in {
            "dry_run_gmail_draft_not_created",
            "blocked_missing_raw_email_for_gmail_draft",
            "gmail_draft_created_locked_test",
        },
        "source_report_used": {
            "path": str(SOURCE_JSON_PATH),
            "present": not bool(source_error),
            "task_name": source_report.get("task_name", ""),
            "draft_package_status": source_report.get("draft_package_status", ""),
            "ready": source_ready,
            "error_sanitized": _sanitize_text(source_error),
        },
        "candidate_count_seen": len(candidates),
        "candidate_selected_count": 1 if selected_candidate else 0,
        "gmail_create_drafts_enabled": create_enabled,
        "approval_ack_valid": ack_valid,
        "approval_ack_required_env": ACK_ENV,
        "gmail_oauth_present": bool(gmail_readiness["gmail_oauth_present"]),
        "gmail_sender_planned": GMAIL_SEND_FROM,
        "gmail_scope_required": GMAIL_COMPOSE_SCOPE,
        "gmail_scope_configured": bool(gmail_readiness["gmail_scope_configured"]),
        "gmail_missing_env_vars": gmail_readiness["missing_env_vars"],
        "gmail_draft_create_attempted": draft_result["gmail_draft_create_attempted"],
        "gmail_drafts_created_count": draft_result["gmail_drafts_created_count"],
        "selected_order_name": selected_preview["order_name"],
        "selected_masked_email": selected_preview["masked_email"],
        "subject": SUBJECT,
        "trustpilot_link": TRUSTPILOT_LINK,
        "selected_draft_preview": selected_preview,
        "planned_tag_after_future_send": TRUSTPILOT_TAG,
        "tag_change_performed": False,
        "html_path": str(REPORT_HTML_PATH),
        "json_path": str(REPORT_JSON_PATH),
        "safe_output_policy": {
            "masked_email_only": True,
            "raw_email_output": False,
            "phone_output": False,
            "address_output": False,
            "ticket_body_output": False,
            "ticket_comments_output": False,
            "private_customer_notes_output": False,
        },
        "safety_summary": safety,
        **safety,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(draft_result["draft_create_status"], len(candidates)),
        "duration_seconds": duration_seconds,
        "json_trustpilot_gmail_draft_create_locked_test_path": str(REPORT_JSON_PATH),
        "html_trustpilot_gmail_draft_create_locked_test_path": str(REPORT_HTML_PATH),
    }
    if draft_result["gmail_draft_created"] and draft_result["gmail_draft_id"]:
        payload["gmail_draft_id"] = draft_result["gmail_draft_id"]
    if draft_result["error_sanitized"]:
        payload["gmail_draft_error_sanitized"] = draft_result["error_sanitized"]
    return payload


def _safety_summary(draft_result: dict) -> dict:
    return {
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "ali_reviews_api_call_performed": False,
        "gmail_api_call_performed": bool(draft_result["gmail_api_call_performed"]),
        "gmail_draft_created": bool(draft_result["gmail_draft_created"]),
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    result = {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_gmail_draft_create_locked_test_path": str(json_path),
        "html_trustpilot_gmail_draft_create_locked_test_path": str(html_path),
        "draft_create_status": payload["draft_create_status"],
        "candidate_count_seen": payload["candidate_count_seen"],
        "candidate_selected_count": payload["candidate_selected_count"],
        "gmail_create_drafts_enabled": payload["gmail_create_drafts_enabled"],
        "approval_ack_valid": payload["approval_ack_valid"],
        "gmail_oauth_present": payload["gmail_oauth_present"],
        "gmail_sender_planned": payload["gmail_sender_planned"],
        "gmail_scope_configured": payload["gmail_scope_configured"],
        "gmail_draft_create_attempted": payload["gmail_draft_create_attempted"],
        "gmail_drafts_created_count": payload["gmail_drafts_created_count"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "subject": payload["subject"],
        "trustpilot_link": payload["trustpilot_link"],
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "ali_reviews_api_call_performed": False,
        "gmail_api_call_performed": payload["gmail_api_call_performed"],
        "gmail_draft_created": payload["gmail_draft_created"],
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }
    if "gmail_draft_id" in payload:
        result["gmail_draft_id"] = payload["gmail_draft_id"]
    return result


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    preview = payload["selected_draft_preview"]
    body = escape(preview["body"]).replace("\n", "<br>")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail Draft Creation Locked Test</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .warning {{ border-left: 4px solid #c2410c; background: #fff7ed; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Trustpilot Gmail Draft Creation Locked Test</h1>
  <p class="warning">Phase 3.2 is locked to at most one Gmail drafts.create call. No Gmail send was performed. No Shopify tag write was performed. No Trustpilot tag was added.</p>
  <p>Status: <strong>{escape(str(payload["draft_create_status"]))}</strong></p>
  <p>Gmail draft creation attempted: <strong>{escape(str(payload["gmail_draft_create_attempted"]))}</strong></p>
  <p>Gmail drafts created: <strong>{escape(str(payload["gmail_drafts_created_count"]))}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <h2>Draft Preview</h2>
  <p>Subject: <strong>{escape(payload["subject"])}</strong></p>
  <p>{body}</p>
  <h2>Safety</h2>
  <table><tbody>{safety_rows}</tbody></table>
  <p><strong>NOT PERFORMED:</strong> no Gmail drafts.send, no Gmail messages.send, no email send, no Shopify tag write, no Kudosi call.</p>
</body>
</html>"""


def _selected_preview(selected_candidate: dict) -> dict:
    if not selected_candidate:
        return {"order_name": "", "masked_email": "", "first_name_used": "there", "body": BODY_TEMPLATE.format(first_name="there")}
    first_name = _safe_text(selected_candidate.get("first_name_used", "")).strip() or "there"
    body = _safe_text(selected_candidate.get("local_draft_body_preview", "")) or BODY_TEMPLATE.format(first_name=first_name)
    return {
        "order_name": _safe_text(selected_candidate.get("order_name", "")),
        "order_id_or_gid": _safe_text(selected_candidate.get("order_id_or_gid", "")),
        "masked_email": _safe_masked_email(selected_candidate.get("masked_email", "")),
        "first_name_used": first_name,
        "body": body,
        "planned_tag_after_future_send": TRUSTPILOT_TAG,
        "tag_change_performed": False,
    }


def _body_for_candidate(selected_candidate: dict) -> str:
    first_name = _safe_text(selected_candidate.get("first_name_used", "")).strip() or "there"
    return _safe_text(selected_candidate.get("local_draft_body_preview", "")) or BODY_TEMPLATE.format(first_name=first_name)


def _raw_recipient_for_gmail(selected_candidate: dict) -> str:
    for key in ("recipient_email", "raw_email", "email"):
        value = selected_candidate.get(key)
        if isinstance(value, str):
            value = value.strip()
            if "***" not in value and EMAIL_RE.fullmatch(value):
                return value
    return ""


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.2 Trustpilot Gmail draft creation locked test finished.\n"
        f"Status: {payload.get('draft_create_status')}\n"
        f"Candidates seen: {payload.get('candidate_count_seen')}\n"
        f"Selected candidates: {payload.get('candidate_selected_count')}\n"
        f"Gmail drafts created: {payload.get('gmail_drafts_created_count')}\n"
        "Safety: no Shopify API call, no Shopify writes, no tagsAdd/tagsRemove, no Kudosi API call, no Gmail send, and no email sending.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(status: str, candidate_count: int) -> str:
    if status == "dry_run_gmail_draft_not_created":
        return f"Locked Gmail draft test inspected {candidate_count} candidates and did not call Gmail because approval gates were not both enabled."
    if status == "blocked_missing_raw_email_for_gmail_draft":
        return "Locked Gmail draft test blocked before Gmail because Phase 3.1 does not persist a raw recipient email."
    if status == "gmail_draft_created_locked_test":
        return "Exactly one Gmail draft was created with drafts.create; no send method was called."
    return f"Locked Gmail draft test status: {status}."


def _safe_masked_email(value: str) -> str:
    text = _safe_text(value)
    if not text or "@" not in text:
        return ""
    if "***" in text:
        return text
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), text)


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def _safe_text(value) -> str:
    text = str(value or "")
    text = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    return _sanitize_text(text)


def _sanitize_text(text: str) -> str:
    redacted = SENSITIVE_TEXT_RE.sub("[redacted]", text or "")
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), redacted)


def _split_scopes(value: str) -> list[str]:
    return [item.strip() for item in value.split() if item.strip()]
