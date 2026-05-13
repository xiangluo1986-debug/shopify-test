import json
import os
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_gmail_readiness_package"
COMMAND_LABEL = "shopify_review_request_gmail_readiness_package_docs_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_gmail_readiness_package.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_gmail_readiness_package.html"

GMAIL_SEND_FROM = "info@kidstoylover.com"
REQUIRED_SCOPE = "https://www.googleapis.com/auth/gmail.send"
BROAD_SCOPE_NOT_REQUIRED_BY_DEFAULT = "https://mail.google.com/"
AUTOMATION_DECISION_STATUS = "blocked_until_gmail_oauth_and_template_confirmed"

REQUIRED_ENV_VARS = [
    "GMAIL_SEND_FROM",
    "GOOGLE_GMAIL_CLIENT_ID",
    "GOOGLE_GMAIL_CLIENT_SECRET",
    "GOOGLE_GMAIL_REFRESH_TOKEN",
    "GOOGLE_GMAIL_SCOPES",
    "TRUSTPILOT_REVIEW_LINK",
]

EMAIL_TEMPLATE_DRAFT = {
    "subject": "Thank you for your support",
    "body": (
        "Hi {{ first_name }},\n\n"
        "Thank you again for your recent order from Kidstoylover.\n\n"
        "We really appreciate your continued support. If you have a moment, it would mean a lot to us if you could "
        "share your experience on Trustpilot:\n\n"
        "{{ trustpilot_review_link }}\n\n"
        "Your feedback helps other RC hobby customers feel more confident when choosing from our store.\n\n"
        "Thank you again for supporting Kidstoylover.\n\n"
        "Kind regards,\n"
        "Xiang\n"
        "Kidstoylover"
    ),
}


def run_shopify_review_request_gmail_readiness_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    end_time = utc_now_iso()
    payload = _build_payload(start_time, end_time, round(time.time() - started, 3))
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return {
        "task_type": TASK_NAME,
        "success": True,
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_gmail_readiness_package_path": str(json_path),
        "html_gmail_readiness_package_path": str(html_path),
        "phase": payload["phase"],
        "mode": payload["mode"],
        "gmail_send_from": payload["gmail_send_from"],
        "required_scope": payload["required_scope"],
        "required_env_var_count": len(payload["required_env_vars"]),
        "missing_env_var_count": len(payload["missing_env_vars"]),
        "trustpilot_review_link_configured": payload["trustpilot_review_link_configured"],
        "gmail_send_allowed": False,
        "automation_decision_status": payload["automation_decision_status"],
        "gmail_api_call_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "ali_reviews_api_call_performed": False,
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(json_path, html_path, payload),
    }


def _build_payload(start_time: str, end_time: str, duration_seconds: float) -> dict:
    present_env_vars = _present_env_vars(REQUIRED_ENV_VARS)
    missing_env_vars = [key for key in REQUIRED_ENV_VARS if key not in present_env_vars]
    trustpilot_review_link_configured = "TRUSTPILOT_REVIEW_LINK" in present_env_vars
    configured_scopes = _configured_scopes_present()
    return {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "0.3",
        "mode": "docs-only-gmail-readiness",
        "command_label": COMMAND_LABEL,
        "gmail_send_from": GMAIL_SEND_FROM,
        "required_scope": REQUIRED_SCOPE,
        "broad_scope_not_required_by_default": BROAD_SCOPE_NOT_REQUIRED_BY_DEFAULT,
        "required_env_vars": REQUIRED_ENV_VARS,
        "missing_env_vars": missing_env_vars,
        "present_env_vars": sorted(present_env_vars),
        "env_value_policy": "presence_only_checked_from_process_environment; values_not_read_from_dotenv_or_reported",
        "trustpilot_review_link_configured": trustpilot_review_link_configured,
        "gmail_scope_readiness": {
            "required_scope": REQUIRED_SCOPE,
            "required_scope_configured_in_process_env": REQUIRED_SCOPE in configured_scopes,
            "broad_scope_present_in_process_env": BROAD_SCOPE_NOT_REQUIRED_BY_DEFAULT in configured_scopes,
            "broad_scope_allowed_by_default": False,
        },
        "oauth_readiness_requirements": [
            "Gmail API enabled in Google Cloud.",
            "OAuth client ID configured.",
            "OAuth client secret configured.",
            "Refresh token configured.",
            "Sender identity verified or authorized to send as info@kidstoylover.com.",
            "Least-privilege gmail.send scope configured.",
        ],
        "manual_approval_requirements_before_any_send": [
            "Dry-run email preview report generated.",
            "Trustpilot review link confirmed.",
            "Customer selected as repeat/high-value.",
            "Customer not blocked by tickets, refunds, shipping issues, privacy requests, or manual suppression.",
            "Ali Reviews / Kudosi sent-status checked when capability is confirmed, or manual dashboard review completed.",
            "Final human approval present.",
        ],
        "email_template_draft": EMAIL_TEMPLATE_DRAFT,
        "automation_decision_status": AUTOMATION_DECISION_STATUS,
        "gmail_send_allowed": False,
        "safety_summary": {
            "docs_only_gmail_readiness": True,
            "gmail_api_call_performed": False,
            "email_sent": False,
            "shopify_api_call_performed": False,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "tags_add_performed": False,
            "tags_remove_performed": False,
            "ali_reviews_api_call_performed": False,
            "review_request_sent": False,
            "secrets_recorded": False,
            "dotenv_read": False,
            "logs_are_local_reports_only": True,
        },
        "gmail_api_call_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "ali_reviews_api_call_performed": False,
        "review_request_sent": False,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            "Gmail sending remains blocked until OAuth, sender identity, Trustpilot link, template preview, "
            "customer eligibility, and final human approval are confirmed."
        ),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": duration_seconds,
        "json_gmail_readiness_package_path": str(REPORT_JSON_PATH),
        "html_gmail_readiness_package_path": str(REPORT_HTML_PATH),
    }


def _present_env_vars(keys: list[str]) -> set[str]:
    present = set()
    for key in keys:
        value = os.environ.get(key)
        if value:
            present.add(key)
    return present


def _configured_scopes_present() -> set[str]:
    scopes_value = os.environ.get("GOOGLE_GMAIL_SCOPES") or ""
    return {item.strip() for item in scopes_value.split() if item.strip()}


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
    safety = payload["safety_summary"]
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in safety.items()
    )
    missing = _render_list(payload["missing_env_vars"])
    requirements = _render_list(payload["manual_approval_requirements_before_any_send"])
    body = escape(payload["email_template_draft"]["body"])
    body = body.replace("\n", "<br>")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Gmail Readiness Package</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin-top: 8px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    li {{ margin-bottom: 4px; }}
    .template {{ border: 1px solid #d9e2ec; padding: 12px; background: #fbfcfe; }}
  </style>
</head>
<body>
  <h1>Gmail Readiness Package</h1>
  <p>Phase: <code>{escape(payload["phase"])}</code></p>
  <p>Mode: <code>{escape(payload["mode"])}</code></p>
  <p>Gmail sender: <code>{escape(payload["gmail_send_from"])}</code></p>
  <p>Required scope: <code>{escape(payload["required_scope"])}</code></p>
  <p>Broad scope not required by default: <code>{escape(payload["broad_scope_not_required_by_default"])}</code></p>
  <p>Decision status: <code>{escape(payload["automation_decision_status"])}</code></p>

  <h2>Missing Environment Variables</h2>
  {missing}

  <h2>Approval Requirements Before Any Send</h2>
  {requirements}

  <h2>Email Template Draft</h2>
  <div class="template">
    <p><strong>Subject:</strong> {escape(payload["email_template_draft"]["subject"])}</p>
    <p>{body}</p>
  </div>

  <h2>Safety Flags</h2>
  <table>
    <tbody>
      {safety_rows}
    </tbody>
  </table>
</body>
</html>
"""


def _render_list(items: list[str]) -> str:
    if not items:
        return "<p>None.</p>"
    return "<ul>" + "\n".join(f"<li>{escape(str(item))}</li>" for item in items) + "</ul>"


def _build_approval_message(json_path: Path, html_path: Path, payload: dict) -> str:
    return (
        "Gmail readiness package generated locally.\n"
        f"Decision status: {payload['automation_decision_status']}\n"
        "Safety: docs-only; no Gmail API, email sending, Shopify API/write/mutation, tagsAdd/tagsRemove, or Ali Reviews API.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
