import json
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_shopify_oauth_reauthorization_helper"
COMMAND_LABEL = "shopify_review_request_shopify_oauth_reauthorization_helper_docs_only"
REPORT_DIR = LOG_DIR / "codex_runs"
REPORT_JSON_PATH = REPORT_DIR / "shopify_review_request_shopify_oauth_reauthorization_helper.json"
REPORT_HTML_PATH = REPORT_DIR / "shopify_review_request_shopify_oauth_reauthorization_helper.html"
HELPER_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "shopify_oauth_reauthorize_helper.py"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"

REQUIRED_PLACEHOLDERS = (
    "SHOPIFY_SHOP_DOMAIN",
    "SHOPIFY_CLIENT_ID",
    "SHOPIFY_CLIENT_SECRET",
    "SHOPIFY_REDIRECT_URI",
    "SHOPIFY_SCOPES",
    "SHOPIFY_OAUTH_SCOPES",
    "SHOPIFY_OAUTH_TOKEN_ENV_KEY",
    "SHOPIFY_OAUTH_SAVE_TOKEN",
    "SHOPIFY_OAUTH_LOAD_ENV_FILE",
    "SHOPIFY_ACCESS_TOKEN",
    "SHOPIFY_ADMIN_API_ACCESS_TOKEN",
    "SHOPIFY_API_PASSWORD",
)

RECOMMENDED_COMMANDS = (
    "python scripts/shopify_oauth_reauthorize_helper.py --mode url",
    'python scripts/shopify_oauth_reauthorize_helper.py --mode exchange --code "PASTE_CODE_HERE"',
    "python scripts/shopify_oauth_reauthorize_helper.py --mode verify",
    "python remote_approval_runner.py --task shopify_review_request_shopify_scope_verification --mode dry-run --approval local",
)

SCOPE_UPDATE_STEPS = (
    "Run URL mode.",
    "Open the authorization URL and approve the app in Shopify.",
    "Copy only the code value from the callback URL.",
    "Run exchange mode with SHOPIFY_OAUTH_SAVE_TOKEN only when ready to save.",
    "Restart web after a saved local .env token update.",
    "Run scope verification.",
    "Confirm read_all_orders is present.",
    "Rerun the #21687 lookup.",
)


def run_shopify_review_request_shopify_oauth_reauthorization_helper_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    payload = _build_payload(round(time.time() - started, 3))
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _build_payload(duration_seconds: float) -> dict:
    helper_present = HELPER_SCRIPT_PATH.exists()
    placeholder_status = _env_example_placeholder_status()
    missing_placeholders = [
        key
        for key, status in placeholder_status["placeholders"].items()
        if not status["present"]
    ]
    success = helper_present and not missing_placeholders
    safety = _safety_summary()
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.31E",
        "mode": "shopify-oauth-reauthorization-helper-docs-only",
        "command_label": COMMAND_LABEL,
        "oauth_reauthorization_helper_status": (
            "ready" if success else "needs_placeholder_or_helper_update"
        ),
        "success": success,
        "helper_script": {
            "path": str(HELPER_SCRIPT_PATH.relative_to(PROJECT_ROOT)),
            "present": helper_present,
            "manual_only": True,
            "modes": ["url", "exchange", "verify"],
            "token_output_allowed": False,
            "client_secret_output_allowed": False,
            "writes_tracked_files_by_task": False,
        },
        "env_example_placeholder_status": placeholder_status,
        "missing_env_example_placeholders": missing_placeholders,
        "required_scopes": ["read_orders", "read_all_orders"],
        "recommended_commands": list(RECOMMENDED_COMMANDS),
        "scope_update_steps": list(SCOPE_UPDATE_STEPS),
        "token_save_requires_approval_flag": True,
        "token_save_approval_env": "SHOPIFY_OAUTH_SAVE_TOKEN",
        "token_save_approval_value": "YES_I_APPROVE_UPDATING_SHOPIFY_ACCESS_TOKEN",
        "env_backup_created_by_helper_when_saving": True,
        "env_backup_pattern": ".env.backup.YYYYMMDDTHHMMSSZ",
        "scope_verification_task": "shopify_review_request_shopify_scope_verification",
        "lookup_rerun_order": "#21687",
        "safe_output_policy": {
            "no_access_token_in_report": True,
            "no_client_secret_in_report": True,
            "no_authorization_code_in_report": True,
            "no_env_secret_values_in_report": True,
            "no_customer_email_list_in_report": True,
        },
        "safety_summary": safety,
        **safety,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            "Phase 5.31E Shopify OAuth reauthorization helper package generated as docs/report only. "
            "The runner task performed no Shopify API call, no token exchange, no token output, no .env write, "
            "no Gmail API call, and no email send."
        ),
        "duration_seconds": duration_seconds,
        "json_shopify_oauth_reauthorization_helper_path": str(REPORT_JSON_PATH),
        "html_shopify_oauth_reauthorization_helper_path": str(REPORT_HTML_PATH),
    }


def _env_example_placeholder_status() -> dict:
    if not ENV_EXAMPLE_PATH.exists():
        return {
            "path": str(ENV_EXAMPLE_PATH.relative_to(PROJECT_ROOT)),
            "present": False,
            "placeholders": {
                key: {"present": False, "value_present": False}
                for key in REQUIRED_PLACEHOLDERS
            },
        }

    present = {}
    for raw_line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in REQUIRED_PLACEHOLDERS:
            present[key] = bool(value.strip())
    return {
        "path": str(ENV_EXAMPLE_PATH.relative_to(PROJECT_ROOT)),
        "present": True,
        "placeholders": {
            key: {
                "present": key in present,
                "value_present": present.get(key, False),
                "value_output": False,
            }
            for key in REQUIRED_PLACEHOLDERS
        },
    }


def _safety_summary() -> dict:
    return {
        "shopify_api_call_performed": False,
        "shopify_oauth_token_exchange_performed": False,
        "shopify_access_scope_verification_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "translations_register_called": False,
        "gmail_api_call_performed": False,
        "gmail_oauth_token_exchange_performed": False,
        "gmail_draft_created": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "env_file_written": False,
        "token_output": False,
        "client_secret_output": False,
        "authorization_code_output": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_shopify_oauth_reauthorization_helper_path": str(json_path),
        "html_shopify_oauth_reauthorization_helper_path": str(html_path),
        "oauth_reauthorization_helper_status": payload["oauth_reauthorization_helper_status"],
        "helper_script_present": payload["helper_script"]["present"],
        "missing_env_example_placeholders": payload["missing_env_example_placeholders"],
        "token_save_requires_approval_flag": payload["token_save_requires_approval_flag"],
        "env_backup_created_by_helper_when_saving": payload["env_backup_created_by_helper_when_saving"],
        "scope_verification_task": payload["scope_verification_task"],
        **payload["safety_summary"],
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "translations_register_called": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _write_json_report(payload: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    commands = _render_pre(payload["recommended_commands"])
    steps = _render_list(payload["scope_update_steps"])
    missing = _render_list(payload["missing_env_example_placeholders"] or ["None"])
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    placeholders = "\n".join(
        "<tr>"
        f"<th>{escape(key)}</th>"
        f"<td>{escape(str(status['present']))}</td>"
        f"<td>{escape(str(status['value_present']))}</td>"
        "</tr>"
        for key, status in payload["env_example_placeholder_status"]["placeholders"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify OAuth Reauthorization Helper</title>
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
  <h1>Shopify OAuth Reauthorization Helper</h1>
  <p class="warning">Docs-only runner report. No Shopify API call, no token exchange, no token output, no .env write, no Gmail API call, and no email send.</p>
  <p>Status: <strong>{escape(payload["oauth_reauthorization_helper_status"])}</strong></p>
  <h2>Recommended Commands</h2>
  {commands}
  <h2>Scope Update Steps</h2>
  {steps}
  <h2>Missing .env.example Placeholders</h2>
  {missing}
  <h2>.env.example Placeholder Check</h2>
  <table><thead><tr><th>Name</th><th>Present</th><th>Value present</th></tr></thead><tbody>{placeholders}</tbody></table>
  <h2>Safety</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


def _render_list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(str(item))}</li>" for item in items) + "</ul>"


def _render_pre(items: list[str]) -> str:
    return "<pre>" + escape("\n".join(str(item) for item in items)) + "</pre>"


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 5.31E OAuth reauthorization helper report finished.\n"
        f"Status: {payload.get('oauth_reauthorization_helper_status')}\n"
        f"Helper present: {payload.get('helper_script', {}).get('present')}\n"
        f"Missing .env.example placeholders: {payload.get('missing_env_example_placeholders')}\n"
        "Recommended URL command: python scripts/shopify_oauth_reauthorize_helper.py --mode url\n"
        "Recommended exchange command: python scripts/shopify_oauth_reauthorize_helper.py --mode exchange --code \"PASTE_CODE_HERE\"\n"
        "Recommended verify command: python scripts/shopify_oauth_reauthorize_helper.py --mode verify\n"
        "Safety: docs/report only; no Shopify API call, no token exchange, no token output, no .env write, no Gmail API/send.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
