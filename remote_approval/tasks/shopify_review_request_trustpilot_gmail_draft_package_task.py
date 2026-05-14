import base64
import json
import os
import re
import time
from email.mime.text import MIMEText
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_draft_package"
COMMAND_LABEL = "shopify_review_request_trustpilot_gmail_draft_package"

SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_unified_decision_engine_dry_run.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_draft_package.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_draft_package.html"

BLOCKED_EXISTING_TRUSTPILOT_INVITATION_TAG = "blocked_existing_trustpilot_invitation_tag"
GMAIL_SEND_FROM = "info@kidstoylover.com"
TRUSTPILOT_LINK = "https://www.trustpilot.com/evaluate/www.kidstoylover.com"
TRUSTPILOT_TAG = "1: trustpilot"
TRUSTPILOT_TAG_ALIASES = [
    "1: trustpilot",
    "1: trustpoilt",
    "1:trustpilot",
    "1 : trustpilot",
    "1:trustpoilt",
    "1 : trustpoilt",
]
TARGET_DECISION = "trustpilot_gmail_candidate_dry_run"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_DRAFT_CREATE_ENABLED_ENV = "TRUSTPILOT_GMAIL_CREATE_DRAFTS"
GMAIL_DRAFT_MAX_ENV = "TRUSTPILOT_GMAIL_DRAFT_MAX"
DEFAULT_GMAIL_DRAFT_MAX = 1
MAX_GMAIL_DRAFTS_THIS_PHASE = 5

SUBJECT = "Thank You for Your Support – We’d Love Your Feedback!"
BODY_TEMPLATE = """Dear {first_name},

Thank you so much for your continued support and for choosing us again — it truly means a lot to our team.

If you have a moment, we would greatly appreciate it if you could leave a quick review of your experience with us. Your feedback not only helps us improve, but also helps other customers feel confident in choosing us too.

You can share your thoughts here:
👉 https://www.trustpilot.com/evaluate/www.kidstoylover.com

Thanks again for being a valued customer. If there's anything else we can assist you with, please don’t hesitate to let us know.

Kind Regards,
Xiang"""

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|access[_\s-]?token|api[_\s-]?key|password|secret|bearer\s+[A-Za-z0-9._-]+)"
)


def run_shopify_review_request_trustpilot_gmail_draft_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_report, source_error = _load_source_report()
    source_ready = _source_ready(source_report, source_error)
    create_drafts_enabled = os.environ.get(GMAIL_DRAFT_CREATE_ENABLED_ENV, "").strip() == "1"
    draft_max = _draft_max_from_env()
    local_drafts = _build_local_drafts(source_report) if source_ready else []
    gmail_result = _maybe_create_gmail_drafts(local_drafts, create_drafts_enabled, draft_max)
    payload = _build_payload(
        source_report=source_report,
        source_error=source_error,
        source_ready=source_ready,
        local_drafts=local_drafts,
        gmail_result=gmail_result,
        create_drafts_enabled=create_drafts_enabled,
        draft_max=draft_max,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _load_source_report() -> tuple[dict, str]:
    if not SOURCE_JSON_PATH.exists():
        return {}, "blocked_missing_unified_decision_report"
    try:
        return json.loads(SOURCE_JSON_PATH.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"unified_decision_report_json_parse_error: {exc}")


def _source_ready(source_report: dict, source_error: str) -> bool:
    return (
        not source_error
        and source_report.get("task_name") == "shopify_review_request_unified_decision_engine_dry_run"
        and str(source_report.get("phase")) == "3.0"
        and source_report.get("decision_engine_status") == "decision_engine_dry_run_ready"
        and source_report.get("success") is True
    )


def _build_local_drafts(source_report: dict) -> list[dict]:
    drafts = []
    for row in source_report.get("decisions") or []:
        if not isinstance(row, dict) or row.get("decision") != TARGET_DECISION:
            continue
        draft = _draft_from_decision_row(row)
        if draft["blocked_reason"] == BLOCKED_EXISTING_TRUSTPILOT_INVITATION_TAG:
            drafts.append(draft)
            continue
        if not draft["masked_email"]:
            draft["blocked_reason"] = "blocked_missing_email"
        drafts.append(draft)
    return drafts


def _draft_from_decision_row(row: dict) -> dict:
    first_name = _safe_first_name(row)
    body = BODY_TEMPLATE.format(first_name=first_name)
    tag_summary = row.get("safe_tags_summary") if isinstance(row.get("safe_tags_summary"), dict) else {}
    blocked_reason = BLOCKED_EXISTING_TRUSTPILOT_INVITATION_TAG if _has_existing_trustpilot_tag(tag_summary) else ""
    return {
        "order_name": _safe_text(row.get("order_name", "")),
        "order_id_or_gid": _safe_text(row.get("order_id_or_gid", "")),
        "masked_email": _safe_masked_email(row.get("masked_email", "")),
        "first_name_used": first_name,
        "subject": SUBJECT,
        "local_draft_body_preview": body,
        "planned_tag_after_future_send": TRUSTPILOT_TAG,
        "tag_change_performed": False,
        "gmail_draft_created": False,
        "gmail_draft_id": "",
        "gmail_draft_error_sanitized": "",
        "blocked_reason": blocked_reason,
        "source_decision": TARGET_DECISION,
        "source_planned_next_action": _safe_text(row.get("planned_next_action", "")),
        "safe_tags_summary": _safe_tags_summary(tag_summary),
    }


def _maybe_create_gmail_drafts(local_drafts: list[dict], enabled: bool, draft_max: int) -> dict:
    result = {
        "gmail_api_call_performed": False,
        "gmail_draft_created": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "total_gmail_drafts_created": 0,
        "blocked_missing_gmail_oauth": 0,
        "blocked_gmail_draft_limit": 0,
        "gmail_oauth_status": "not_required_local_draft_package_only",
        "gmail_draft_creation_errors_sanitized": [],
    }
    if not enabled:
        return result

    eligible = [draft for draft in local_drafts if not draft["blocked_reason"]]
    result["blocked_gmail_draft_limit"] = max(0, len(eligible) - draft_max)
    env = _gmail_env()
    if not env["ready"]:
        result["gmail_oauth_status"] = env["status"]
        result["blocked_missing_gmail_oauth"] = len(eligible[:draft_max])
        return result

    try:
        service = _build_gmail_service(env)
    except Exception as exc:  # pragma: no cover - only used when Gmail drafting is explicitly enabled.
        result["gmail_oauth_status"] = "blocked_gmail_client_or_oauth_error"
        result["blocked_missing_gmail_oauth"] = len(eligible[:draft_max])
        result["gmail_draft_creation_errors_sanitized"].append(_sanitize_text(str(exc)))
        return result

    result["gmail_oauth_status"] = "gmail_oauth_ready_for_draft_create_only"
    for draft in eligible[:draft_max]:
        raw_recipient = _raw_recipient_for_gmail(draft)
        if not raw_recipient:
            draft["blocked_reason"] = "blocked_missing_email"
            continue
        try:
            draft_body = _create_gmail_draft(service, raw_recipient, draft)
            draft["gmail_draft_created"] = True
            draft["gmail_draft_id"] = _safe_text(draft_body.get("id", ""))
            result["gmail_api_call_performed"] = True
            result["gmail_draft_created"] = True
            result["total_gmail_drafts_created"] += 1
        except Exception as exc:  # pragma: no cover - only used when Gmail drafting is explicitly enabled.
            draft["gmail_draft_error_sanitized"] = _sanitize_text(str(exc))
            result["gmail_draft_creation_errors_sanitized"].append(draft["gmail_draft_error_sanitized"])
    return result


def _gmail_env() -> dict:
    values = _read_dotenv_values(
        {
            "GMAIL_SEND_FROM",
            "GOOGLE_GMAIL_CLIENT_ID",
            "GOOGLE_GMAIL_CLIENT_SECRET",
            "GOOGLE_GMAIL_REFRESH_TOKEN",
            "GOOGLE_GMAIL_SCOPES",
        }
    )
    send_from = (os.environ.get("GMAIL_SEND_FROM") or values.get("GMAIL_SEND_FROM") or "").strip()
    client_id = (os.environ.get("GOOGLE_GMAIL_CLIENT_ID") or values.get("GOOGLE_GMAIL_CLIENT_ID") or "").strip()
    client_secret = (
        os.environ.get("GOOGLE_GMAIL_CLIENT_SECRET") or values.get("GOOGLE_GMAIL_CLIENT_SECRET") or ""
    ).strip()
    refresh_token = (
        os.environ.get("GOOGLE_GMAIL_REFRESH_TOKEN") or values.get("GOOGLE_GMAIL_REFRESH_TOKEN") or ""
    ).strip()
    scopes = _split_scopes(os.environ.get("GOOGLE_GMAIL_SCOPES") or values.get("GOOGLE_GMAIL_SCOPES") or "")
    missing = []
    if send_from != GMAIL_SEND_FROM:
        missing.append("GMAIL_SEND_FROM")
    if not client_id:
        missing.append("GOOGLE_GMAIL_CLIENT_ID")
    if not client_secret:
        missing.append("GOOGLE_GMAIL_CLIENT_SECRET")
    if not refresh_token:
        missing.append("GOOGLE_GMAIL_REFRESH_TOKEN")
    if GMAIL_SCOPE not in scopes:
        missing.append("GOOGLE_GMAIL_SCOPES")
    return {
        "ready": not missing,
        "status": "gmail_oauth_ready" if not missing else "blocked_missing_gmail_oauth",
        "missing_env_vars": missing,
        "send_from": send_from,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "scopes": scopes or [GMAIL_SCOPE],
    }


def _read_dotenv_values(allowed_keys: set[str]) -> dict:
    dotenv_path = Path.cwd() / ".env"
    values = {}
    if not dotenv_path.exists():
        return values
    for line in dotenv_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in allowed_keys:
            values[key] = value.strip().strip("\"'")
    return values


def _build_gmail_service(env: dict):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=None,
        refresh_token=env["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=env["client_id"],
        client_secret=env["client_secret"],
        scopes=env["scopes"],
    )
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _create_gmail_draft(service, recipient_email: str, draft: dict) -> dict:
    message = MIMEText(draft["local_draft_body_preview"], "plain", "utf-8")
    message["to"] = recipient_email
    message["from"] = GMAIL_SEND_FROM
    message["subject"] = draft["subject"]
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    body = {"message": {"raw": raw_message}}
    return service.users().drafts().create(userId="me", body=body).execute()


def _raw_recipient_for_gmail(draft: dict) -> str:
    # Phase 3.0 intentionally stores masked email only. This hook prevents sending to a masked value.
    for key in ("recipient_email", "raw_email", "email"):
        value = draft.get(key)
        if isinstance(value, str) and EMAIL_RE.fullmatch(value.strip()) and "***" not in value:
            return value.strip()
    return ""


def _build_payload(
    source_report: dict,
    source_error: str,
    source_ready: bool,
    local_drafts: list[dict],
    gmail_result: dict,
    create_drafts_enabled: bool,
    draft_max: int,
    duration_seconds: float,
) -> dict:
    blocked_counts = _blocked_counts(local_drafts, gmail_result, create_drafts_enabled)
    prepared = [draft for draft in local_drafts if not draft["blocked_reason"]]
    status = _draft_package_status(source_error, source_ready, create_drafts_enabled, gmail_result)
    safety = _safety_summary(gmail_result)
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.1",
        "mode": "trustpilot-gmail-draft-package-dry-run",
        "command_label": COMMAND_LABEL,
        "draft_package_status": status,
        "success": source_ready and status in {"local_draft_package_only", "gmail_drafts_created", "gmail_draft_package_ready_no_candidates"},
        "source_report_used": {
            "path": str(SOURCE_JSON_PATH),
            "present": not bool(source_error),
            "task_name": source_report.get("task_name", ""),
            "decision_engine_status": source_report.get("decision_engine_status", ""),
            "ready": source_ready,
            "error_sanitized": _sanitize_text(source_error),
        },
        "total_candidates_seen": len(local_drafts),
        "total_local_drafts_prepared": len(prepared),
        "total_gmail_drafts_created": gmail_result["total_gmail_drafts_created"],
        "blocked_counts": blocked_counts,
        "gmail_create_drafts_enabled": create_drafts_enabled,
        "gmail_draft_limit_effective": draft_max,
        "gmail_oauth_status": gmail_result["gmail_oauth_status"],
        "gmail_sender_planned": GMAIL_SEND_FROM,
        "trustpilot_link": TRUSTPILOT_LINK,
        "subject": SUBJECT,
        "trustpilot_tag_aliases": TRUSTPILOT_TAG_ALIASES,
        "html_path": str(REPORT_HTML_PATH),
        "json_path": str(REPORT_JSON_PATH),
        "draft_candidates": local_drafts,
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
        "detected_issue_summary": _issue_summary(status, local_drafts, blocked_counts),
        "duration_seconds": duration_seconds,
        "json_trustpilot_gmail_draft_package_path": str(REPORT_JSON_PATH),
        "html_trustpilot_gmail_draft_package_path": str(REPORT_HTML_PATH),
    }


def _draft_package_status(source_error: str, source_ready: bool, enabled: bool, gmail_result: dict) -> str:
    if source_error or not source_ready:
        return "blocked_missing_unified_decision_report"
    if not enabled:
        return "local_draft_package_only"
    if gmail_result["gmail_oauth_status"] == "blocked_missing_gmail_oauth":
        return "blocked_missing_gmail_oauth"
    if gmail_result["total_gmail_drafts_created"] > 0:
        return "gmail_drafts_created"
    return "local_draft_package_only"


def _blocked_counts(local_drafts: list[dict], gmail_result: dict, enabled: bool) -> dict:
    counts = {
        "blocked_missing_email": 0,
        BLOCKED_EXISTING_TRUSTPILOT_INVITATION_TAG: 0,
        "blocked_missing_gmail_oauth": gmail_result["blocked_missing_gmail_oauth"] if enabled else 0,
        "blocked_gmail_draft_limit": gmail_result["blocked_gmail_draft_limit"] if enabled else 0,
    }
    for draft in local_drafts:
        if draft["blocked_reason"] == "blocked_missing_email":
            counts["blocked_missing_email"] += 1
        elif draft["blocked_reason"] == BLOCKED_EXISTING_TRUSTPILOT_INVITATION_TAG:
            counts[BLOCKED_EXISTING_TRUSTPILOT_INVITATION_TAG] += 1
    return counts


def _safety_summary(gmail_result: dict) -> dict:
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
        "gmail_api_call_performed": bool(gmail_result["gmail_api_call_performed"]),
        "gmail_draft_created": bool(gmail_result["gmail_draft_created"]),
        "gmail_send_performed": False,
        "email_sent": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_gmail_draft_package_path": str(json_path),
        "html_trustpilot_gmail_draft_package_path": str(html_path),
        "draft_package_status": payload["draft_package_status"],
        "total_candidates_seen": payload["total_candidates_seen"],
        "total_local_drafts_prepared": payload["total_local_drafts_prepared"],
        "total_gmail_drafts_created": payload["total_gmail_drafts_created"],
        "blocked_counts": payload["blocked_counts"],
        "gmail_create_drafts_enabled": payload["gmail_create_drafts_enabled"],
        "gmail_sender_planned": payload["gmail_sender_planned"],
        "trustpilot_link": payload["trustpilot_link"],
        "subject": payload["subject"],
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
        "gmail_send_performed": False,
        "email_sent": False,
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


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
    blocked_rows = "\n".join(
        f"<tr><td><code>{escape(key)}</code></td><td>{escape(str(value))}</td></tr>"
        for key, value in payload["blocked_counts"].items()
    )
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    draft_rows = "\n".join(_render_draft_row(row) for row in payload["draft_candidates"][:100])
    if not draft_rows:
        draft_rows = '<tr><td colspan="8">No Trustpilot draft candidates available.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail Draft Package</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .warning {{ border-left: 4px solid #c2410c; background: #fff7ed; padding: 10px 12px; }}
    .preview {{ white-space: pre-wrap; max-width: 520px; }}
  </style>
</head>
<body>
  <h1>Trustpilot Gmail Draft Package</h1>
  <p class="warning">Phase 3.1 is draft-package only by default. No Gmail send was performed. No Shopify tag write was performed. No Trustpilot tag was added.</p>
  <p>Status: <strong>{escape(str(payload["draft_package_status"]))}</strong></p>
  <p>Gmail draft creation enabled: <strong>{escape(str(payload["gmail_create_drafts_enabled"]))}</strong></p>
  <p>Sender planned: <code>{escape(payload["gmail_sender_planned"])}</code></p>
  <p>Trustpilot link: <a href="{escape(payload["trustpilot_link"])}">{escape(payload["trustpilot_link"])}</a></p>
  <h2>Summary</h2>
  <table><tbody>
    <tr><th>Total candidates seen</th><td>{escape(str(payload["total_candidates_seen"]))}</td></tr>
    <tr><th>Local drafts prepared</th><td>{escape(str(payload["total_local_drafts_prepared"]))}</td></tr>
    <tr><th>Gmail drafts created</th><td>{escape(str(payload["total_gmail_drafts_created"]))}</td></tr>
  </tbody></table>
  <h2>Blocked Counts</h2>
  <table><tbody>{blocked_rows}</tbody></table>
  <h2>Safety</h2>
  <table><tbody>{safety_rows}</tbody></table>
  <h2>Draft Previews</h2>
  <table>
    <thead><tr><th>Order</th><th>Masked email</th><th>First name</th><th>Subject</th><th>Preview</th><th>Future tag</th><th>Gmail draft</th><th>Blocked reason</th></tr></thead>
    <tbody>{draft_rows}</tbody>
  </table>
  <p><strong>NOT PERFORMED:</strong> no Gmail send, no Shopify tag write, no Trustpilot tag add.</p>
</body>
</html>"""


def _render_draft_row(row: dict) -> str:
    draft_status = "created" if row["gmail_draft_created"] else "not created"
    if row.get("gmail_draft_id"):
        draft_status += f"<br><code>{escape(row['gmail_draft_id'])}</code>"
    body = escape(row["local_draft_body_preview"])
    return f"""<tr>
  <td>{escape(row["order_name"])}<br><code>{escape(row["order_id_or_gid"])}</code></td>
  <td>{escape(row["masked_email"])}</td>
  <td>{escape(row["first_name_used"])}</td>
  <td>{escape(row["subject"])}</td>
  <td class="preview">{body}</td>
  <td><code>{escape(row["planned_tag_after_future_send"])}</code><br>performed=false</td>
  <td>{draft_status}</td>
  <td>{escape(row.get("blocked_reason", ""))}</td>
</tr>"""


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.1 Trustpilot Gmail draft package finished.\n"
        f"Status: {payload.get('draft_package_status')}\n"
        f"Candidates seen: {payload.get('total_candidates_seen')}\n"
        f"Local drafts prepared: {payload.get('total_local_drafts_prepared')}\n"
        f"Gmail drafts created: {payload.get('total_gmail_drafts_created')}\n"
        "Safety: no Shopify API call, no Shopify writes, no tagsAdd/tagsRemove, no Kudosi API call, no Gmail send, and no email sending.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(status: str, local_drafts: list[dict], blocked_counts: dict) -> str:
    if status == "blocked_missing_unified_decision_report":
        return "Trustpilot Gmail draft package blocked because the Phase 3.0 unified decision report is missing or not ready."
    return (
        f"Prepared {sum(1 for draft in local_drafts if not draft['blocked_reason'])} local Trustpilot draft previews "
        f"from {len(local_drafts)} candidates; blocked counts: {json.dumps(blocked_counts, ensure_ascii=False)}."
    )


def _draft_max_from_env() -> int:
    raw = os.environ.get(GMAIL_DRAFT_MAX_ENV, "").strip()
    if not raw:
        return DEFAULT_GMAIL_DRAFT_MAX
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_GMAIL_DRAFT_MAX
    return max(1, min(value, MAX_GMAIL_DRAFTS_THIS_PHASE))


def _safe_first_name(row: dict) -> str:
    for key in ("first_name_used", "customer_first_name", "first_name"):
        value = _safe_text(row.get(key, "")).strip()
        if value and "@" not in value and len(value) <= 40:
            return value.split()[0]
    return "there"


def _has_existing_trustpilot_tag(tag_summary: dict) -> bool:
    if tag_summary.get("contains_trustpilot_alias") is True:
        return True
    aliases = {_normalize_tag(tag) for tag in TRUSTPILOT_TAG_ALIASES}
    for key in ("tags_of_interest", "safe_tags", "exact_tags_of_interest"):
        for tag in tag_summary.get(key, []) or []:
            if _normalize_tag(tag) in aliases:
                return True
    return False


def _safe_tags_summary(tag_summary: dict) -> dict:
    return {
        "contains_trustpilot_alias": bool(tag_summary.get("contains_trustpilot_alias")),
        "tags_of_interest": [_safe_text(tag) for tag in tag_summary.get("tags_of_interest", [])],
    }


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


def _normalize_tag(tag: str) -> str:
    text = str(tag or "").strip().lower()
    text = re.sub(r"\s*:\s*", ":", text)
    return re.sub(r"\s+", " ", text)


def _split_scopes(value: str) -> list[str]:
    return [item.strip() for item in value.split() if item.strip()]
