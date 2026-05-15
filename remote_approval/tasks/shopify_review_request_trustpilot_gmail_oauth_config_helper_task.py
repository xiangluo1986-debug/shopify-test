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
LEGACY_GMAIL_SEND_FROM_ENV = "GMAIL_SEND_FROM"
LEGACY_GMAIL_CLIENT_ID_ENV = "GOOGLE_GMAIL_CLIENT_ID"
LEGACY_GMAIL_CLIENT_SECRET_ENV = "GOOGLE_GMAIL_CLIENT_SECRET"
LEGACY_GMAIL_REFRESH_TOKEN_ENV = "GOOGLE_GMAIL_REFRESH_TOKEN"
LEGACY_GMAIL_SCOPES_ENV = "GOOGLE_GMAIL_SCOPES"
LEGACY_GMAIL_ENV_NAMES = (
    LEGACY_GMAIL_SEND_FROM_ENV,
    LEGACY_GMAIL_CLIENT_ID_ENV,
    LEGACY_GMAIL_CLIENT_SECRET_ENV,
    LEGACY_GMAIL_REFRESH_TOKEN_ENV,
    LEGACY_GMAIL_SCOPES_ENV,
)
REQUIRED_ACK_NAME = "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK"
REQUIRED_EXECUTE_FLAG_NAME = "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_REAL_SEND_EXECUTE"
REQUIRED_SCOPE_EXPECTED = "https://www.googleapis.com/auth/gmail.send"
COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"

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
    "If the older GOOGLE_GMAIL_* flow is already configured, the helper can detect its presence without printing values.",
    "If the older flow only has gmail.compose scope, verify gmail.send before any future real-send phase.",
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
    config_helper_status = _config_helper_status(blocking_conditions, dependency_status, env_status)
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
        "config_helper_status": config_helper_status,
        "gmail_dependencies_importable": dependency_status["all_importable"],
        "gmail_dependency_status": dependency_status,
        "gmail_oauth_config_status": env_status["gmail_oauth_config_status"],
        "gmail_token_config_status": env_status["gmail_token_config_status"],
        "gmail_send_from_email_configured": env_status["gmail_send_from_email_configured"],
        "gmail_oauth_client_secret_file_configured": env_status[
            "gmail_oauth_client_secret_file_configured"
        ],
        "gmail_oauth_client_secret_path_exists": env_status["gmail_oauth_client_secret_path_exists"],
        "gmail_oauth_token_file_configured": env_status["gmail_oauth_token_file_configured"],
        "gmail_oauth_token_path_exists": env_status["gmail_oauth_token_path_exists"],
        "gmail_required_scope_configured": env_status["gmail_required_scope_configured"],
        "gmail_required_scope_matches_expected": env_status["gmail_required_scope_matches_expected"],
        "legacy_gmail_oauth_config_present": env_status["legacy_gmail_oauth_config_present"],
        "legacy_gmail_sender_configured": env_status["legacy_gmail_sender_configured"],
        "legacy_gmail_client_id_configured": env_status["legacy_gmail_client_id_configured"],
        "legacy_gmail_client_secret_configured": env_status["legacy_gmail_client_secret_configured"],
        "legacy_gmail_refresh_token_configured": env_status["legacy_gmail_refresh_token_configured"],
        "legacy_gmail_scopes_configured": env_status["legacy_gmail_scopes_configured"],
        "legacy_gmail_send_scope_present": env_status["legacy_gmail_send_scope_present"],
        "legacy_gmail_compose_scope_present": env_status["legacy_gmail_compose_scope_present"],
        "legacy_gmail_scope_compatibility": env_status["legacy_gmail_scope_compatibility"],
        "gmail_scope_compatibility_result": env_status["gmail_scope_compatibility_result"],
        "gmail_send_scope_present": env_status["gmail_send_scope_present"],
        "gmail_compose_scope_present": env_status["gmail_compose_scope_present"],
        "required_scope_expected": REQUIRED_SCOPE_EXPECTED,
        "required_ack_name": REQUIRED_ACK_NAME,
        "required_execute_flag_name": REQUIRED_EXECUTE_FLAG_NAME,
        "required_ack_name_documented": required_ack_documented,
        "required_execute_flag_name_documented": required_execute_documented,
        "env_var_name_status": env_status["env_var_name_status"],
        "legacy_env_var_name_status": env_status["legacy_env_var_name_status"],
        "new_env_var_name_status": env_status["new_env_var_name_status"],
        "gmail_config_detection_summary": env_status["gmail_config_detection_summary"],
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
        "next_admin_action": _next_admin_action(env_status),
        "dashboard_message": _dashboard_message(env_status),
        "safety_message": (
            "Do not enable real sending until OAuth config, final preflight, and readiness audit all pass."
        ),
        "privacy_scan_summary": _empty_privacy_scan_summary(),
        "report_paths": {
            "json": f"logs/{REPORT_JSON_PATH.name}",
            "html": f"logs/{REPORT_HTML_PATH.name}",
        },
        "duration_seconds": duration_seconds,
        "detected_issue_summary": _detected_issue_summary(blocking_conditions, env_status),
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
    client_secret_path_exists = _path_exists_from_env(GMAIL_OAUTH_CLIENT_SECRET_FILE_ENV)
    token_path_exists = _path_exists_from_env(GMAIL_OAUTH_TOKEN_FILE_ENV)

    legacy_sender_configured = _env_configured(LEGACY_GMAIL_SEND_FROM_ENV)
    legacy_client_id_configured = _env_configured(LEGACY_GMAIL_CLIENT_ID_ENV)
    legacy_client_secret_configured = _env_configured(LEGACY_GMAIL_CLIENT_SECRET_ENV)
    legacy_refresh_token_configured = _env_configured(LEGACY_GMAIL_REFRESH_TOKEN_ENV)
    legacy_scopes_configured = _env_configured(LEGACY_GMAIL_SCOPES_ENV)
    legacy_scope_status = _scope_status(os.environ.get(LEGACY_GMAIL_SCOPES_ENV, ""))
    required_scope_status = _scope_status(os.environ.get(GMAIL_REQUIRED_SCOPE_ENV, ""))
    legacy_config_present = legacy_client_secret_configured and legacy_refresh_token_configured
    new_file_path_config_present = (
        from_configured
        and client_secret_file_configured
        and client_secret_path_exists
        and token_file_configured
        and token_path_exists
        and required_scope_matches_expected
    )
    send_scope_present = (
        required_scope_matches_expected
        or legacy_scope_status["gmail_send_scope_present"]
        or required_scope_status["gmail_send_scope_present"]
    )
    compose_scope_present = (
        legacy_scope_status["gmail_compose_scope_present"]
        or required_scope_status["gmail_compose_scope_present"]
    )
    scope_compatibility = _combined_scope_compatibility(send_scope_present, compose_scope_present)
    return {
        "process_environment_only": True,
        "dotenv_read": False,
        "values_reported": False,
        "gmail_send_from_email_configured": from_configured,
        "gmail_oauth_client_secret_file_configured": client_secret_file_configured,
        "gmail_oauth_client_secret_path_exists": client_secret_path_exists,
        "gmail_oauth_token_file_configured": token_file_configured,
        "gmail_oauth_token_path_exists": token_path_exists,
        "gmail_required_scope_configured": required_scope_configured,
        "gmail_required_scope_matches_expected": required_scope_matches_expected,
        "legacy_gmail_oauth_config_present": legacy_config_present,
        "legacy_gmail_sender_configured": legacy_sender_configured,
        "legacy_gmail_client_id_configured": legacy_client_id_configured,
        "legacy_gmail_client_secret_configured": legacy_client_secret_configured,
        "legacy_gmail_refresh_token_configured": legacy_refresh_token_configured,
        "legacy_gmail_scopes_configured": legacy_scopes_configured,
        "legacy_gmail_send_scope_present": legacy_scope_status["gmail_send_scope_present"],
        "legacy_gmail_compose_scope_present": legacy_scope_status["gmail_compose_scope_present"],
        "legacy_gmail_scope_compatibility": legacy_scope_status["scope_compatibility"],
        "new_gmail_file_path_config_present": new_file_path_config_present,
        "gmail_oauth_config_status": _gmail_oauth_config_status(new_file_path_config_present, legacy_config_present),
        "gmail_token_config_status": _gmail_token_config_status(token_path_exists, legacy_refresh_token_configured),
        "gmail_send_scope_present": send_scope_present,
        "gmail_compose_scope_present": compose_scope_present,
        "gmail_scope_compatibility_result": scope_compatibility,
        "new_env_var_name_status": [
            _env_var_name_status(GMAIL_SEND_FROM_EMAIL_ENV, from_configured),
            _env_var_name_status(GMAIL_OAUTH_CLIENT_SECRET_FILE_ENV, client_secret_file_configured),
            _env_var_name_status(GMAIL_OAUTH_TOKEN_FILE_ENV, token_file_configured),
            _env_var_name_status(GMAIL_REQUIRED_SCOPE_ENV, required_scope_configured),
        ],
        "legacy_env_var_name_status": [
            _env_var_name_status(LEGACY_GMAIL_SEND_FROM_ENV, legacy_sender_configured),
            _env_var_name_status(LEGACY_GMAIL_CLIENT_ID_ENV, legacy_client_id_configured),
            _env_var_name_status(LEGACY_GMAIL_CLIENT_SECRET_ENV, legacy_client_secret_configured),
            _env_var_name_status(LEGACY_GMAIL_REFRESH_TOKEN_ENV, legacy_refresh_token_configured),
            _env_var_name_status(LEGACY_GMAIL_SCOPES_ENV, legacy_scopes_configured),
        ],
        "env_var_name_status": [
            _env_var_name_status(GMAIL_SEND_FROM_EMAIL_ENV, from_configured),
            _env_var_name_status(GMAIL_OAUTH_CLIENT_SECRET_FILE_ENV, client_secret_file_configured),
            _env_var_name_status(GMAIL_OAUTH_TOKEN_FILE_ENV, token_file_configured),
            _env_var_name_status(GMAIL_REQUIRED_SCOPE_ENV, required_scope_configured),
            _env_var_name_status(LEGACY_GMAIL_SEND_FROM_ENV, legacy_sender_configured),
            _env_var_name_status(LEGACY_GMAIL_CLIENT_ID_ENV, legacy_client_id_configured),
            _env_var_name_status(LEGACY_GMAIL_CLIENT_SECRET_ENV, legacy_client_secret_configured),
            _env_var_name_status(LEGACY_GMAIL_REFRESH_TOKEN_ENV, legacy_refresh_token_configured),
            _env_var_name_status(LEGACY_GMAIL_SCOPES_ENV, legacy_scopes_configured),
            _env_var_name_status(REQUIRED_ACK_NAME, _env_configured(REQUIRED_ACK_NAME)),
            _env_var_name_status(REQUIRED_EXECUTE_FLAG_NAME, _env_configured(REQUIRED_EXECUTE_FLAG_NAME)),
        ],
        "gmail_config_detection_summary": {
            "new_file_path_config_present": new_file_path_config_present,
            "legacy_config_present": legacy_config_present,
            "legacy_config_fallback_supported": True,
            "scope_values_reported": False,
            "secret_values_reported": False,
        },
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


def _scope_status(raw_value: str) -> dict:
    scopes = {item.strip() for item in re.split(r"[\s,]+", raw_value or "") if item.strip()}
    send_present = REQUIRED_SCOPE_EXPECTED in scopes
    compose_present = COMPOSE_SCOPE in scopes
    return {
        "scope_configured": bool(scopes),
        "gmail_send_scope_present": send_present,
        "gmail_compose_scope_present": compose_present,
        "scope_compatibility": _combined_scope_compatibility(send_present, compose_present),
        "scope_values_reported": False,
    }


def _combined_scope_compatibility(send_present: bool, compose_present: bool) -> str:
    if send_present:
        return "send_scope_present"
    if compose_present:
        return "compose_only_not_send_scope"
    return "scope_missing"


def _gmail_oauth_config_status(new_file_path_config_present: bool, legacy_config_present: bool) -> str:
    if new_file_path_config_present:
        return "new_file_path_config_present"
    if legacy_config_present:
        return "legacy_config_present"
    return "missing"


def _gmail_token_config_status(new_token_path_exists: bool, legacy_refresh_token_present: bool) -> str:
    if new_token_path_exists:
        return "new_token_file_present"
    if legacy_refresh_token_present:
        return "legacy_refresh_token_present"
    return "missing"


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
    legacy_config_present = env_status["legacy_gmail_oauth_config_present"]
    sender_configured = (
        env_status["gmail_send_from_email_configured"] or env_status["legacy_gmail_sender_configured"]
    )
    client_secret_available = (
        env_status["gmail_oauth_client_secret_path_exists"] or legacy_config_present
    )
    token_available = env_status["gmail_oauth_token_path_exists"] or env_status[
        "legacy_gmail_refresh_token_configured"
    ]
    if not dependency_status["all_importable"]:
        conditions.append(
            _condition(
                "blocked_missing_gmail_dependencies",
                "One or more Gmail dependency modules are not importable locally.",
            )
        )
    if not sender_configured:
        conditions.append(
            _condition(
                "missing_gmail_sender",
                f"Neither {GMAIL_SEND_FROM_EMAIL_ENV} nor legacy {LEGACY_GMAIL_SEND_FROM_ENV} is configured.",
            )
        )
    if not client_secret_available and not env_status["gmail_oauth_client_secret_file_configured"]:
        conditions.append(
            _condition(
                "missing_gmail_oauth_client_secret_file",
                (
                    f"{GMAIL_OAUTH_CLIENT_SECRET_FILE_ENV} is not configured and legacy "
                    f"{LEGACY_GMAIL_CLIENT_SECRET_ENV}/{LEGACY_GMAIL_REFRESH_TOKEN_ENV} config was not detected."
                ),
            )
        )
    elif not client_secret_available and not env_status["gmail_oauth_client_secret_path_exists"]:
        conditions.append(
            _condition(
                "missing_gmail_oauth_client_secret_path",
                (
                    f"{GMAIL_OAUTH_CLIENT_SECRET_FILE_ENV} is configured, but the path does not exist "
                    "and no legacy fallback config was detected."
                ),
            )
        )
    if not token_available and not env_status["gmail_oauth_token_file_configured"]:
        conditions.append(
            _condition(
                "missing_gmail_oauth_token_file",
                (
                    f"{GMAIL_OAUTH_TOKEN_FILE_ENV} is not configured and legacy "
                    f"{LEGACY_GMAIL_REFRESH_TOKEN_ENV} was not detected."
                ),
            )
        )
    elif not token_available and not env_status["gmail_oauth_token_path_exists"]:
        conditions.append(
            _condition(
                "missing_gmail_oauth_token_path",
                (
                    f"{GMAIL_OAUTH_TOKEN_FILE_ENV} is configured, but the path does not exist "
                    "and no legacy refresh-token fallback was detected."
                ),
            )
        )
    if not env_status["gmail_send_scope_present"]:
        if env_status["gmail_compose_scope_present"]:
            conditions.append(
                _condition(
                    "gmail_compose_only_not_send_scope",
                    "A Gmail compose scope was detected, but real sending requires gmail.send.",
                )
            )
        elif not env_status["gmail_required_scope_configured"] and not env_status["legacy_gmail_scopes_configured"]:
            conditions.append(
                _condition(
                    "missing_gmail_required_scope",
                    f"Neither {GMAIL_REQUIRED_SCOPE_ENV} nor legacy {LEGACY_GMAIL_SCOPES_ENV} is configured.",
                )
            )
        else:
            conditions.append(
                _condition(
                    "gmail_required_scope_not_expected",
                    "Configured Gmail scope names do not confirm gmail.send.",
                )
            )
    elif env_status["gmail_required_scope_configured"] and not env_status["gmail_required_scope_matches_expected"]:
        conditions.append(
            _condition(
                "gmail_required_scope_not_expected_but_legacy_send_scope_present",
                (
                    f"{GMAIL_REQUIRED_SCOPE_ENV} does not match gmail.send, but another configured "
                    "scope source confirms gmail.send."
                ),
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


def _config_helper_status(blocking_conditions: list[dict], dependency_status: dict, env_status: dict) -> str:
    if not blocking_conditions:
        if env_status["gmail_oauth_config_status"] == "legacy_config_present":
            return "legacy_gmail_oauth_config_ready_for_preflight"
        return "gmail_oauth_config_ready_for_preflight"
    if not dependency_status["all_importable"]:
        return "blocked_missing_gmail_dependencies"
    if env_status["legacy_gmail_oauth_config_present"]:
        if env_status["gmail_scope_compatibility_result"] == "compose_only_not_send_scope":
            return "legacy_config_present_compose_only_not_send_scope"
        return "legacy_config_present_needs_final_scope_or_sender_check"
    return "blocked_missing_gmail_oauth_config"


def _next_admin_action(env_status: dict) -> str:
    if env_status["legacy_gmail_oauth_config_present"]:
        if env_status["gmail_send_scope_present"]:
            return (
                "Legacy Gmail config was detected safely. Rerun final preflight/readiness checks before any "
                "future real send, and keep explicit human approval required."
            )
        return (
            "Legacy Gmail config was detected safely, but gmail.send still needs verification before any "
            "future real send."
        )
    return (
        "Configure Gmail OAuth client secret file path and token file path, or confirm the older "
        "GOOGLE_GMAIL_* config in the host environment. Do not enable real send until final preflight "
        "and real-send readiness pass."
    )


def _dashboard_message(env_status: dict) -> str:
    if env_status["legacy_gmail_oauth_config_present"]:
        if env_status["gmail_scope_compatibility_result"] == "compose_only_not_send_scope":
            return "Gmail can create drafts from the older email flow, but real sending may need gmail.send permission."
        return (
            "Gmail configuration was found from the older email flow. It still needs final send-scope "
            "verification before real sending."
        )
    if env_status["new_gmail_file_path_config_present"]:
        return "Gmail setup was found from the new file-path configuration. No Gmail network call was made."
    return "Gmail setup is not complete yet. No Gmail network call was made."


def _detected_issue_summary(blocking_conditions: list[dict], env_status: dict) -> str:
    if not blocking_conditions:
        if env_status["legacy_gmail_oauth_config_present"]:
            return "Legacy Gmail config presence was detected without reading or printing secret values."
        return "Gmail OAuth/config helper passed local config presence checks without Gmail network calls."
    if env_status["legacy_gmail_oauth_config_present"]:
        return (
            "Legacy Gmail config presence was detected, but real send remains blocked until gmail.send "
            "scope and final approval checks pass. No Gmail network call, draft creation, send, Shopify "
            "write, or external review API call was performed."
        )
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
      <tr><th>OAuth config status</th><td><code>{escape(payload["gmail_oauth_config_status"])}</code></td></tr>
      <tr><th>Token config status</th><td><code>{escape(payload["gmail_token_config_status"])}</code></td></tr>
      <tr><th>From email configured</th><td>{payload["gmail_send_from_email_configured"]}</td></tr>
      <tr><th>OAuth client secret path configured</th><td>{payload["gmail_oauth_client_secret_file_configured"]}</td></tr>
      <tr><th>OAuth client secret path exists</th><td>{payload["gmail_oauth_client_secret_path_exists"]}</td></tr>
      <tr><th>OAuth token path configured</th><td>{payload["gmail_oauth_token_file_configured"]}</td></tr>
      <tr><th>OAuth token path exists</th><td>{payload["gmail_oauth_token_path_exists"]}</td></tr>
      <tr><th>Legacy config detected</th><td>{payload["legacy_gmail_oauth_config_present"]}</td></tr>
      <tr><th>Required scope configured</th><td>{payload["gmail_required_scope_configured"]}</td></tr>
      <tr><th>Required scope matches expected</th><td>{payload["gmail_required_scope_matches_expected"]}</td></tr>
      <tr><th>Scope compatibility</th><td><code>{escape(payload["gmail_scope_compatibility_result"])}</code></td></tr>
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
        "gmail_oauth_config_status": payload["gmail_oauth_config_status"],
        "gmail_token_config_status": payload["gmail_token_config_status"],
        "gmail_send_from_email_configured": payload["gmail_send_from_email_configured"],
        "gmail_oauth_client_secret_file_configured": payload["gmail_oauth_client_secret_file_configured"],
        "gmail_oauth_client_secret_path_exists": payload["gmail_oauth_client_secret_path_exists"],
        "gmail_oauth_token_file_configured": payload["gmail_oauth_token_file_configured"],
        "gmail_oauth_token_path_exists": payload["gmail_oauth_token_path_exists"],
        "gmail_required_scope_configured": payload["gmail_required_scope_configured"],
        "gmail_required_scope_matches_expected": payload["gmail_required_scope_matches_expected"],
        "legacy_gmail_oauth_config_present": payload["legacy_gmail_oauth_config_present"],
        "legacy_gmail_scope_compatibility": payload["legacy_gmail_scope_compatibility"],
        "gmail_scope_compatibility_result": payload["gmail_scope_compatibility_result"],
        "gmail_send_scope_present": payload["gmail_send_scope_present"],
        "gmail_compose_scope_present": payload["gmail_compose_scope_present"],
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
        f"Gmail OAuth config status: {payload.get('gmail_oauth_config_status')}\n"
        f"Gmail token config status: {payload.get('gmail_token_config_status')}\n"
        f"Legacy Gmail config present: {payload.get('legacy_gmail_oauth_config_present')}\n"
        f"Scope compatibility: {payload.get('gmail_scope_compatibility_result')}\n"
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
