import json
import os
import re
import time
from html import escape
from importlib.util import find_spec
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_oauth_config_helper"
COMMAND_LABEL = TASK_NAME
PHASE = "5.16"

REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_oauth_config_helper.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_oauth_config_helper.html"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"

GMAIL_DEPENDENCY_MODULES = (
    "google.oauth2.credentials",
    "googleapiclient.discovery",
    "google.auth.transport.requests",
)

GMAIL_SEND_FROM_EMAIL_ENV = "GMAIL_SEND_FROM_EMAIL"
GMAIL_OAUTH_CLIENT_SECRET_FILE_ENV = "GMAIL_OAUTH_CLIENT_SECRET_FILE"
GMAIL_OAUTH_TOKEN_FILE_ENV = "GMAIL_OAUTH_TOKEN_FILE"
GMAIL_REQUIRED_SCOPE_ENV = "GMAIL_REQUIRED_SCOPE"
REQUIRED_ACK_NAME = "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK"
REQUIRED_EXECUTE_FLAG_NAME = "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_REAL_SEND_EXECUTE"
REQUIRED_SCOPE_EXPECTED = "https://www.googleapis.com/auth/gmail.send"

EXPECTED_ENV_PLACEHOLDERS = {
    GMAIL_SEND_FROM_EMAIL_ENV: "info@kidstoylover.com",
    GMAIL_OAUTH_CLIENT_SECRET_FILE_ENV: "path/to/gmail_client_secret.json",
    GMAIL_OAUTH_TOKEN_FILE_ENV: "path/to/gmail_token.json",
    GMAIL_REQUIRED_SCOPE_ENV: REQUIRED_SCOPE_EXPECTED,
    REQUIRED_ACK_NAME: "",
    REQUIRED_EXECUTE_FLAG_NAME: "",
}

SETUP_STEPS = [
    "Add placeholder names to .env.example only; put real local values only in .env or the host environment.",
    "Configure GMAIL_OAUTH_CLIENT_SECRET_FILE to point at the local Gmail OAuth client secret JSON file.",
    "Configure GMAIL_OAUTH_TOKEN_FILE to point at the local Gmail OAuth token JSON file.",
    "Configure GMAIL_SEND_FROM_EMAIL for the authorized sender.",
    f"Configure GMAIL_REQUIRED_SCOPE to {REQUIRED_SCOPE_EXPECTED}.",
    "Rerun this helper and confirm OAuth config, final preflight, and readiness audit all pass before any future real send.",
]

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}")
ACCESS_TOKEN_VALUE_RE = re.compile(r"(?i)\baccess[_-]?token\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
REFRESH_TOKEN_VALUE_RE = re.compile(r"(?i)\brefresh[_-]?token\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
CLIENT_SECRET_VALUE_RE = re.compile(r"(?i)\bclient[_-]?secret\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
PRIVATE_KEY_RE = re.compile(r"(?i)-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----|\bprivate_key\b\s*[:=]")
FULL_GMAIL_ID_RE = re.compile(r"(?i)\b(?:gmail_)?(?:draft|message)_id\b\s*[:=]\s*['\"]?[A-Za-z0-9_-]{16,}")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
ALLOWED_EMAILS = {"info@kidstoylover.com"}
ALLOWED_EMAIL_DOMAINS = {"example.invalid"}


def run_shopify_review_request_trustpilot_gmail_oauth_config_helper_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    payload = _build_payload(duration_seconds=round(time.time() - started, 3))
    payload["privacy_scan_summary"] = _privacy_scan_for_payload(payload)
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _build_payload(duration_seconds: float) -> dict:
    dependency_status = _gmail_dependency_status()
    env_status = _gmail_config_status()
    env_example_status = _env_example_placeholder_status()
    required_ack_documented = _name_documented(REQUIRED_ACK_NAME, env_example_status)
    required_execute_documented = _name_documented(REQUIRED_EXECUTE_FLAG_NAME, env_example_status)
    blocking_conditions = _blocking_conditions(
        dependency_status=dependency_status,
        env_status=env_status,
        required_ack_documented=required_ack_documented,
        required_execute_documented=required_execute_documented,
    )
    generated_at = utc_now_iso()
    payload = {
        "timestamp": generated_at,
        "report_generated_at": generated_at,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": PHASE,
        "channel": "trustpilot",
        "mode": "gmail-oauth-config-helper",
        "dry_run": True,
        "command_label": COMMAND_LABEL,
        "success": True,
        "config_helper_status": _config_helper_status(blocking_conditions, dependency_status),
        "gmail_dependencies_importable": dependency_status["all_importable"],
        "gmail_dependency_status": dependency_status,
        "gmail_send_from_email_configured": env_status["gmail_send_from_email_configured"],
        "gmail_oauth_client_secret_file_configured": env_status[
            "gmail_oauth_client_secret_file_configured"
        ],
        "gmail_oauth_client_secret_path_exists": env_status["gmail_oauth_client_secret_path_exists"],
        "gmail_oauth_token_file_configured": env_status["gmail_oauth_token_file_configured"],
        "gmail_oauth_token_path_exists": env_status["gmail_oauth_token_path_exists"],
        "gmail_required_scope_configured": env_status["gmail_required_scope_configured"],
        "gmail_required_scope_matches_expected": env_status["gmail_required_scope_matches_expected"],
        "required_scope_expected": REQUIRED_SCOPE_EXPECTED,
        "required_ack_name": REQUIRED_ACK_NAME,
        "required_execute_flag_name": REQUIRED_EXECUTE_FLAG_NAME,
        "required_ack_name_documented": required_ack_documented,
        "required_execute_flag_name_documented": required_execute_documented,
        "env_var_name_status": env_status["env_var_name_status"],
        "env_example_placeholder_status": env_example_status,
        "gmail_network_call_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_performed": False,
        "gmail_draft_update_performed": False,
        "gmail_draft_delete_performed": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "token_file_read": False,
        "credential_file_read": False,
        "secret_value_printed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "translations_register_called": False,
        "setup_steps": SETUP_STEPS,
        "blocking_conditions": blocking_conditions,
        "next_admin_action": (
            "Configure Gmail OAuth client secret file path and token file path, then rerun the helper. "
            "Do not enable real send until final preflight and real-send readiness pass."
        ),
        "dashboard_message": "Gmail OAuth is not fully configured yet. No Gmail network call was made.",
        "safety_message": (
            "Do not enable real sending until OAuth config, final preflight, and readiness audit all pass."
        ),
        "privacy_scan_summary": _empty_privacy_scan_summary(),
        "report_paths": {
            "json": f"logs/{REPORT_JSON_PATH.name}",
            "html": f"logs/{REPORT_HTML_PATH.name}",
        },
        "duration_seconds": duration_seconds,
        "detected_issue_summary": _detected_issue_summary(blocking_conditions),
    }
    return _safe_payload(payload)


def _gmail_dependency_status() -> dict:
    modules = []
    for module_name in GMAIL_DEPENDENCY_MODULES:
        try:
            importable = find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            importable = False
        modules.append(
            {
                "module": module_name,
                "importable": importable,
                "status": "ready" if importable else "missing",
            }
        )
    all_importable = all(item["importable"] for item in modules)
    return {
        "all_importable": all_importable,
        "status": "ready" if all_importable else "missing",
        "modules": modules,
        "network_call_performed": False,
    }


def _gmail_config_status() -> dict:
    from_configured = _env_configured(GMAIL_SEND_FROM_EMAIL_ENV)
    client_secret_file_configured = _env_configured(GMAIL_OAUTH_CLIENT_SECRET_FILE_ENV)
    token_file_configured = _env_configured(GMAIL_OAUTH_TOKEN_FILE_ENV)
    required_scope_configured = _env_configured(GMAIL_REQUIRED_SCOPE_ENV)
    required_scope_matches_expected = (
        os.environ.get(GMAIL_REQUIRED_SCOPE_ENV, "").strip() == REQUIRED_SCOPE_EXPECTED
    )
    return {
        "process_environment_only": True,
        "dotenv_read": False,
        "values_reported": False,
        "gmail_send_from_email_configured": from_configured,
        "gmail_oauth_client_secret_file_configured": client_secret_file_configured,
        "gmail_oauth_client_secret_path_exists": _path_exists_from_env(GMAIL_OAUTH_CLIENT_SECRET_FILE_ENV),
        "gmail_oauth_token_file_configured": token_file_configured,
        "gmail_oauth_token_path_exists": _path_exists_from_env(GMAIL_OAUTH_TOKEN_FILE_ENV),
        "gmail_required_scope_configured": required_scope_configured,
        "gmail_required_scope_matches_expected": required_scope_matches_expected,
        "env_var_name_status": [
            _env_var_name_status(GMAIL_SEND_FROM_EMAIL_ENV, from_configured),
            _env_var_name_status(GMAIL_OAUTH_CLIENT_SECRET_FILE_ENV, client_secret_file_configured),
            _env_var_name_status(GMAIL_OAUTH_TOKEN_FILE_ENV, token_file_configured),
            _env_var_name_status(GMAIL_REQUIRED_SCOPE_ENV, required_scope_configured),
            _env_var_name_status(REQUIRED_ACK_NAME, _env_configured(REQUIRED_ACK_NAME)),
            _env_var_name_status(REQUIRED_EXECUTE_FLAG_NAME, _env_configured(REQUIRED_EXECUTE_FLAG_NAME)),
        ],
    }


def _env_configured(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def _env_var_name_status(name: str, configured: bool) -> dict:
    return {
        "name": name,
        "configured": configured,
        "status": "configured" if configured else "not_configured",
        "value_reported": False,
    }


def _path_exists_from_env(name: str) -> bool:
    raw_path = os.environ.get(name, "").strip()
    if not raw_path:
        return False
    try:
        candidate = Path(raw_path).expanduser()
        candidates = [candidate] if candidate.is_absolute() else [PROJECT_ROOT / candidate, candidate]
        return any(path.exists() for path in candidates)
    except (OSError, RuntimeError, ValueError):
        return False


def _env_example_placeholder_status() -> dict:
    expected_names = set(EXPECTED_ENV_PLACEHOLDERS)
    found = {}
    if ENV_EXAMPLE_PATH.exists():
        for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if key in expected_names:
                found[key] = value.strip()
    return {
        "path": ".env.example",
        "present": ENV_EXAMPLE_PATH.exists(),
        "file_read": ENV_EXAMPLE_PATH.exists(),
        "values_reported": False,
        "placeholders": {
            name: {
                "present": name in found,
                "matches_recommended_placeholder": found.get(name, "") == expected,
                "value_reported": False,
            }
            for name, expected in EXPECTED_ENV_PLACEHOLDERS.items()
        },
    }


def _name_documented(name: str, env_example_status: dict) -> bool:
    placeholders = env_example_status.get("placeholders") if isinstance(env_example_status, dict) else {}
    if isinstance(placeholders, dict) and placeholders.get(name, {}).get("present") is True:
        return True
    for relative_path in (
        "remote_approval/LOCAL_APPROVAL_WORKFLOW.md",
        "remote_approval/review_request_integration_checklist.md",
    ):
        path = PROJECT_ROOT / relative_path
        try:
            if path.exists() and name in path.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def _blocking_conditions(
    dependency_status: dict,
    env_status: dict,
    required_ack_documented: bool,
    required_execute_documented: bool,
) -> list[dict]:
    conditions = []
    if not dependency_status["all_importable"]:
        conditions.append(
            _condition(
                "blocked_missing_gmail_dependencies",
                "One or more Gmail dependency modules are not importable locally.",
            )
        )
    if not env_status["gmail_send_from_email_configured"]:
        conditions.append(_condition("missing_gmail_send_from_email", f"{GMAIL_SEND_FROM_EMAIL_ENV} is not configured."))
    if not env_status["gmail_oauth_client_secret_file_configured"]:
        conditions.append(
            _condition(
                "missing_gmail_oauth_client_secret_file",
                f"{GMAIL_OAUTH_CLIENT_SECRET_FILE_ENV} is not configured.",
            )
        )
    elif not env_status["gmail_oauth_client_secret_path_exists"]:
        conditions.append(
            _condition(
                "missing_gmail_oauth_client_secret_path",
                f"{GMAIL_OAUTH_CLIENT_SECRET_FILE_ENV} is configured, but the path does not exist.",
            )
        )
    if not env_status["gmail_oauth_token_file_configured"]:
        conditions.append(
            _condition("missing_gmail_oauth_token_file", f"{GMAIL_OAUTH_TOKEN_FILE_ENV} is not configured.")
        )
    elif not env_status["gmail_oauth_token_path_exists"]:
        conditions.append(
            _condition(
                "missing_gmail_oauth_token_path",
                f"{GMAIL_OAUTH_TOKEN_FILE_ENV} is configured, but the path does not exist.",
            )
        )
    if not env_status["gmail_required_scope_configured"]:
        conditions.append(_condition("missing_gmail_required_scope", f"{GMAIL_REQUIRED_SCOPE_ENV} is not configured."))
    elif not env_status["gmail_required_scope_matches_expected"]:
        conditions.append(
            _condition(
                "gmail_required_scope_not_expected",
                f"{GMAIL_REQUIRED_SCOPE_ENV} must match the required gmail.send scope.",
            )
        )
    if not required_ack_documented:
        conditions.append(_condition("missing_required_ack_documentation", f"{REQUIRED_ACK_NAME} is not documented."))
    if not required_execute_documented:
        conditions.append(
            _condition(
                "missing_required_execute_flag_documentation",
                f"{REQUIRED_EXECUTE_FLAG_NAME} is not documented.",
            )
        )
    return conditions


def _condition(status: str, detail: str) -> dict:
    return {"status": status, "detail": detail}


def _config_helper_status(blocking_conditions: list[dict], dependency_status: dict) -> str:
    if not blocking_conditions:
        return "gmail_oauth_config_ready_for_preflight"
    if not dependency_status["all_importable"]:
        return "blocked_missing_gmail_dependencies"
    return "blocked_missing_gmail_oauth_config"


def _detected_issue_summary(blocking_conditions: list[dict]) -> str:
    if not blocking_conditions:
        return "Gmail OAuth/config helper passed local config presence checks without Gmail network calls."
    return (
        "Gmail OAuth/config helper is blocked by missing local Gmail config. "
        "No Gmail network call, draft creation, send, Shopify write, or external review API call was performed."
    )


def _empty_privacy_scan_summary() -> dict:
    return {
        "scan_performed": False,
        "passed": False,
        "raw_email_like_disallowed_count": 0,
        "allowed_placeholder_email_count": 0,
        "bearer_token_count": 0,
        "access_token_value_count": 0,
        "refresh_token_value_count": 0,
        "client_secret_value_count": 0,
        "private_key_pattern_count": 0,
        "full_gmail_id_pattern_count": 0,
        "sensitive_matches_reported": False,
    }


def _privacy_scan_for_payload(payload: dict) -> dict:
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    html_text = _render_html_report(payload)
    content = f"{json_text}\n{html_text}"
    email_matches = EMAIL_RE.findall(content)
    disallowed_email_count = 0
    allowed_email_count = 0
    for email in email_matches:
        normalized = email.lower()
        domain = normalized.rsplit("@", 1)[-1]
        if normalized in ALLOWED_EMAILS or domain in ALLOWED_EMAIL_DOMAINS:
            allowed_email_count += 1
        else:
            disallowed_email_count += 1
    counts = {
        "raw_email_like_disallowed_count": disallowed_email_count,
        "allowed_placeholder_email_count": allowed_email_count,
        "bearer_token_count": len(BEARER_TOKEN_RE.findall(content)),
        "access_token_value_count": len(ACCESS_TOKEN_VALUE_RE.findall(content)),
        "refresh_token_value_count": len(REFRESH_TOKEN_VALUE_RE.findall(content)),
        "client_secret_value_count": len(CLIENT_SECRET_VALUE_RE.findall(content)),
        "private_key_pattern_count": len(PRIVATE_KEY_RE.findall(content)),
        "full_gmail_id_pattern_count": len(FULL_GMAIL_ID_RE.findall(content)),
    }
    passed = all(value == 0 for key, value in counts.items() if key != "allowed_placeholder_email_count")
    return {
        "scan_performed": True,
        "passed": passed,
        **counts,
        "sensitive_matches_reported": False,
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(_safe_payload(payload), report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status_class = (
        "ok" if payload["config_helper_status"] == "gmail_oauth_config_ready_for_preflight" else "warn"
    )
    blocking_rows = "\n".join(_render_condition_row(row) for row in payload["blocking_conditions"])
    if not blocking_rows:
        blocking_rows = '<tr><td colspan="2">No blocking conditions recorded.</td></tr>'
    env_rows = "\n".join(_render_env_row(row) for row in payload["env_var_name_status"])
    dependency_rows = "\n".join(_render_dependency_row(row) for row in payload["gmail_dependency_status"]["modules"])
    placeholder_rows = "\n".join(
        _render_placeholder_row(name, status)
        for name, status in payload["env_example_placeholder_status"]["placeholders"].items()
    )
    privacy_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["privacy_scan_summary"].items()
    )
    setup_steps = "<ol>" + "".join(f"<li>{escape(step)}</li>" for step in payload["setup_steps"]) + "</ol>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail OAuth Config Helper</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .status {{ border-left: 4px solid #d97706; background: #fff7ed; padding: 10px 12px; }}
    .status.ok {{ border-left-color: #16a34a; background: #f0fdf4; }}
  </style>
</head>
<body>
  <h1>Trustpilot Gmail OAuth Config Helper</h1>
  <p class="status {status_class}">Config helper status: <strong>{escape(payload["config_helper_status"])}</strong></p>
  <p>{escape(payload["dashboard_message"])}</p>
  <p>{escape(payload["safety_message"])}</p>
  <p>Mode: <code>{escape(payload["mode"])}</code>. This task checks local config presence only; it does not read token or credential file contents.</p>
  <table>
    <tbody>
      <tr><th>Gmail dependencies importable</th><td>{payload["gmail_dependencies_importable"]}</td></tr>
      <tr><th>From email configured</th><td>{payload["gmail_send_from_email_configured"]}</td></tr>
      <tr><th>OAuth client secret path configured</th><td>{payload["gmail_oauth_client_secret_file_configured"]}</td></tr>
      <tr><th>OAuth client secret path exists</th><td>{payload["gmail_oauth_client_secret_path_exists"]}</td></tr>
      <tr><th>OAuth token path configured</th><td>{payload["gmail_oauth_token_file_configured"]}</td></tr>
      <tr><th>OAuth token path exists</th><td>{payload["gmail_oauth_token_path_exists"]}</td></tr>
      <tr><th>Required scope configured</th><td>{payload["gmail_required_scope_configured"]}</td></tr>
      <tr><th>Required scope matches expected</th><td>{payload["gmail_required_scope_matches_expected"]}</td></tr>
      <tr><th>Required scope expected</th><td><code>{escape(payload["required_scope_expected"])}</code></td></tr>
      <tr><th>Token file read</th><td>{payload["token_file_read"]}</td></tr>
      <tr><th>Credential file read</th><td>{payload["credential_file_read"]}</td></tr>
      <tr><th>Secret value printed</th><td>{payload["secret_value_printed"]}</td></tr>
    </tbody>
  </table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>Setup Steps</h2>
  {setup_steps}
  <details>
    <summary>Advanced debug details</summary>
    <p>JSON report: <code>logs/{escape(REPORT_JSON_PATH.name)}</code></p>
    <p>HTML report: <code>logs/{escape(REPORT_HTML_PATH.name)}</code></p>
    <p>Required ACK name: <code>{escape(payload["required_ack_name"])}</code></p>
    <p>Required execute flag name: <code>{escape(payload["required_execute_flag_name"])}</code></p>
    <h2>Environment Variable Names</h2>
    <table><thead><tr><th>Name</th><th>Status</th><th>Value reported</th></tr></thead><tbody>{env_rows}</tbody></table>
    <h2>Dependency Modules</h2>
    <table><thead><tr><th>Module</th><th>Status</th></tr></thead><tbody>{dependency_rows}</tbody></table>
    <h2>.env.example Placeholders</h2>
    <table><thead><tr><th>Name</th><th>Present</th><th>Recommended placeholder</th></tr></thead><tbody>{placeholder_rows}</tbody></table>
    <h2>Privacy Scan</h2>
    <table><tbody>{privacy_rows}</tbody></table>
  </details>
</body>
</html>"""


def _render_condition_row(row: dict) -> str:
    return (
        "<tr>"
        f"<td><code>{escape(str(row.get('status', '')))}</code></td>"
        f"<td>{escape(str(row.get('detail', '')))}</td>"
        "</tr>"
    )


def _render_env_row(row: dict) -> str:
    return (
        "<tr>"
        f"<td><code>{escape(str(row.get('name', '')))}</code></td>"
        f"<td>{escape(str(row.get('status', '')))}</td>"
        f"<td>{escape(str(row.get('value_reported') is True))}</td>"
        "</tr>"
    )


def _render_dependency_row(row: dict) -> str:
    return (
        "<tr>"
        f"<td><code>{escape(str(row.get('module', '')))}</code></td>"
        f"<td>{escape(str(row.get('status', '')))}</td>"
        "</tr>"
    )


def _render_placeholder_row(name: str, status: dict) -> str:
    return (
        "<tr>"
        f"<td><code>{escape(str(name))}</code></td>"
        f"<td>{escape(str(status.get('present') is True))}</td>"
        f"<td>{escape(str(status.get('matches_recommended_placeholder') is True))}</td>"
        "</tr>"
    )


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": True,
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_review_path": str(json_path),
        "html_review_path": str(html_path),
        "json_trustpilot_gmail_oauth_config_helper_path": str(json_path),
        "html_trustpilot_gmail_oauth_config_helper_path": str(html_path),
        "config_helper_status": payload["config_helper_status"],
        "gmail_dependencies_importable": payload["gmail_dependencies_importable"],
        "gmail_send_from_email_configured": payload["gmail_send_from_email_configured"],
        "gmail_oauth_client_secret_file_configured": payload["gmail_oauth_client_secret_file_configured"],
        "gmail_oauth_client_secret_path_exists": payload["gmail_oauth_client_secret_path_exists"],
        "gmail_oauth_token_file_configured": payload["gmail_oauth_token_file_configured"],
        "gmail_oauth_token_path_exists": payload["gmail_oauth_token_path_exists"],
        "gmail_required_scope_configured": payload["gmail_required_scope_configured"],
        "gmail_required_scope_matches_expected": payload["gmail_required_scope_matches_expected"],
        "required_ack_name_documented": payload["required_ack_name_documented"],
        "required_execute_flag_name_documented": payload["required_execute_flag_name_documented"],
        "gmail_network_call_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_performed": False,
        "token_file_read": False,
        "credential_file_read": False,
        "secret_value_printed": False,
        "privacy_scan_summary": payload["privacy_scan_summary"],
        "blocking_conditions": payload["blocking_conditions"],
        "next_admin_action": payload["next_admin_action"],
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 5.16 Gmail OAuth/config helper finished.\n"
        f"Status: {payload.get('config_helper_status')}\n"
        f"Gmail dependencies importable: {payload.get('gmail_dependencies_importable')}\n"
        f"From email configured: {payload.get('gmail_send_from_email_configured')}\n"
        f"OAuth client secret path configured: {payload.get('gmail_oauth_client_secret_file_configured')}\n"
        f"OAuth token path configured: {payload.get('gmail_oauth_token_file_configured')}\n"
        "Safety: no Gmail network/API call, no draft create/update/delete, no send, no token/credential file read, no Shopify write, and no external review API call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _safe_payload(value):
    if isinstance(value, dict):
        return {str(key): _safe_payload(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_safe_payload(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value, max_length=4000)
    return value


def _safe_text(value, max_length=300) -> str:
    text = str(value or "")
    text = CONTROL_CHARS_RE.sub(" ", text)
    text = " ".join(text.split())
    return text[:max_length]
