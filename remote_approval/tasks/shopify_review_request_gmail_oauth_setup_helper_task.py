import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_gmail_oauth_setup_helper"
COMMAND_LABEL = "shopify_review_request_gmail_oauth_setup_helper"

REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_gmail_oauth_setup_helper.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_gmail_oauth_setup_helper.html"
HELPER_SCRIPT_PATH = Path("scripts/gmail_oauth_setup_helper.py")

SENDER_EMAIL = "info@kidstoylover.com"
RECOMMENDED_SCOPE = "https://www.googleapis.com/auth/gmail.compose"

REQUIRED_ENV_VARS = [
    "GMAIL_SEND_FROM=info@kidstoylover.com",
    "GOOGLE_GMAIL_CLIENT_ID=",
    "GOOGLE_GMAIL_CLIENT_SECRET=",
    "GOOGLE_GMAIL_REFRESH_TOKEN=",
    "GOOGLE_GMAIL_SCOPES=https://www.googleapis.com/auth/gmail.compose",
]

GOOGLE_CLOUD_STEPS = [
    "Create or use a Google Cloud project.",
    "Enable the Gmail API for that project.",
    "Configure the OAuth consent screen.",
    "Create an OAuth Client ID.",
    "Use a Desktop app client or a Web app redirect URI supported by the helper.",
    "Authorize only the least-permission gmail.compose scope for draft creation.",
    "Store credentials only in local .env.",
    "Do not commit .env, generated token files, authorization codes, or OAuth tokens.",
]

HELPER_MODES = [
    "Generate an OAuth authorization URL locally.",
    "Exchange a pasted OAuth approval code for a refresh token only when run manually.",
    "Never call Gmail drafts.create, drafts.send, or messages.send.",
    "Never write refresh tokens into tracked files.",
]

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|authorization|access[_\s-]?token|refresh[_\s-]?token|api[_\s-]?key|password|secret|bearer\s+[A-Za-z0-9._-]+)"
)


def run_shopify_review_request_gmail_oauth_setup_helper_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    payload = _build_payload(round(time.time() - started, 3))
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _build_payload(duration_seconds: float) -> dict:
    env_example_status = _env_example_placeholder_status()
    helper_script_present = HELPER_SCRIPT_PATH.exists()
    safety = _safety_summary()
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.4",
        "mode": "gmail-oauth-setup-helper-docs-only",
        "command_label": COMMAND_LABEL,
        "setup_status": "gmail_oauth_setup_helper_ready",
        "success": True,
        "required_google_cloud_steps": GOOGLE_CLOUD_STEPS,
        "required_env_vars": REQUIRED_ENV_VARS,
        "recommended_scope": RECOMMENDED_SCOPE,
        "sender_email": SENDER_EMAIL,
        "draft_only_mode": True,
        "gmail_draft_create_allowed_later_only_with_ack": True,
        "gmail_send_allowed": False,
        "helper_script": {
            "path": str(HELPER_SCRIPT_PATH),
            "present": helper_script_present,
            "modes": HELPER_MODES,
            "manual_only": True,
            "writes_tracked_files": False,
            "gmail_api_calls_performed_by_task": False,
            "draft_create_performed_by_script": False,
            "send_performed_by_script": False,
        },
        "env_example_placeholder_status": env_example_status,
        "manual_commands": [
            "python scripts/gmail_oauth_setup_helper.py auth-url --client-id YOUR_CLIENT_ID",
            "python scripts/gmail_oauth_setup_helper.py exchange-code --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET --code YOUR_AUTH_CODE",
        ],
        "next_phase": "Phase 3.5 one Gmail draft creation with explicit ACK only.",
        "safe_output_policy": {
            "no_secret_values_in_report": True,
            "no_oauth_code_value_in_report": True,
            "no_access_token_in_report": True,
            "no_refresh_token_in_report": True,
            "no_customer_email_list_in_report": True,
        },
        "safety_summary": safety,
        **safety,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "logs_committed": False,
        "detected_issue_summary": (
            "Gmail OAuth setup helper package generated without Gmail API calls, draft creation, email sending, "
            "Shopify writes, or secret output."
        ),
        "duration_seconds": duration_seconds,
        "json_gmail_oauth_setup_helper_path": str(REPORT_JSON_PATH),
        "html_gmail_oauth_setup_helper_path": str(REPORT_HTML_PATH),
    }


def _env_example_placeholder_status() -> dict:
    path = Path(".env.example")
    expected = {
        "GMAIL_SEND_FROM": "info@kidstoylover.com",
        "GOOGLE_GMAIL_CLIENT_ID": "",
        "GOOGLE_GMAIL_CLIENT_SECRET": "",
        "GOOGLE_GMAIL_REFRESH_TOKEN": "",
        "GOOGLE_GMAIL_SCOPES": RECOMMENDED_SCOPE,
    }
    if not path.exists():
        return {"path": str(path), "present": False, "placeholders": {}}
    values = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key in expected:
            values[key] = value
    return {
        "path": str(path),
        "present": True,
        "placeholders": {
            key: {
                "present": key in values,
                "matches_recommended_placeholder": values.get(key, "") == expected_value,
            }
            for key, expected_value in expected.items()
        },
    }


def _safety_summary() -> dict:
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
        "gmail_api_call_performed": False,
        "gmail_oauth_token_exchange_performed": False,
        "gmail_draft_created": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": True,
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_gmail_oauth_setup_helper_path": str(json_path),
        "html_gmail_oauth_setup_helper_path": str(html_path),
        "setup_status": payload["setup_status"],
        "recommended_scope": payload["recommended_scope"],
        "sender_email": payload["sender_email"],
        "draft_only_mode": payload["draft_only_mode"],
        "gmail_draft_create_allowed_later_only_with_ack": payload[
            "gmail_draft_create_allowed_later_only_with_ack"
        ],
        "gmail_send_allowed": False,
        "gmail_api_call_performed": False,
        "gmail_oauth_token_exchange_performed": False,
        "gmail_draft_created": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
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
    steps = _render_list(payload["required_google_cloud_steps"])
    env_vars = _render_pre(payload["required_env_vars"])
    helper_modes = _render_list(payload["helper_script"]["modes"])
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Gmail OAuth Setup Helper</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code, pre {{ background: #f5f7fa; padding: 2px 4px; }}
    pre {{ padding: 12px; overflow: auto; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .warning {{ border-left: 4px solid #c2410c; background: #fff7ed; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Gmail OAuth Setup Helper</h1>
  <p class="warning">This package contains no Gmail tokens, no authorization code, no customer email list, and no secrets. No Gmail draft was created and no email was sent.</p>
  <p>Status: <strong>{escape(payload["setup_status"])}</strong></p>
  <p>Sender: <code>{escape(payload["sender_email"])}</code></p>
  <p>Recommended scope: <code>{escape(payload["recommended_scope"])}</code></p>
  <h2>Google Cloud Checklist</h2>
  {steps}
  <h2>.env Placeholders</h2>
  {env_vars}
  <h2>Manual Helper Script</h2>
  <p>Script path: <code>{escape(payload["helper_script"]["path"])}</code></p>
  {helper_modes}
  <h2>Safety</h2>
  <table><tbody>{safety_rows}</tbody></table>
  <p>Next phase: {escape(payload["next_phase"])}</p>
</body>
</html>"""


def _render_list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>"


def _render_pre(items: list[str]) -> str:
    return "<pre>" + escape("\n".join(items)) + "</pre>"


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.4 Gmail OAuth setup helper finished.\n"
        f"Status: {payload.get('setup_status')}\n"
        f"Recommended scope: {payload.get('recommended_scope')}\n"
        "Safety: no Gmail API call, no OAuth token exchange, no Gmail draft, no Gmail send, no Shopify write, and no Kudosi call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _safe_text(value) -> str:
    text = str(value or "")
    text = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    return _sanitize_text(text)


def _sanitize_text(text: str) -> str:
    redacted = SENSITIVE_TEXT_RE.sub("[redacted]", text or "")
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), redacted)


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"
