import json
import os
import re
import time
from html import escape
from importlib.util import find_spec
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_config_compatibility_audit"
COMMAND_LABEL = TASK_NAME
PHASE = "5.18A"

REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_config_compatibility_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_config_compatibility_audit.html"

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"

LEGACY_CONFIG_NAMES = (
    "GMAIL_SEND_FROM",
    "GOOGLE_GMAIL_CLIENT_ID",
    "GOOGLE_GMAIL_CLIENT_SECRET",
    "GOOGLE_GMAIL_REFRESH_TOKEN",
    "GOOGLE_GMAIL_SCOPES",
    "GOOGLE_GMAIL_TOKEN_PATH",
    "GMAIL_TOKEN_PATH",
    "GOOGLE_GMAIL_CREDENTIALS_PATH",
    "GMAIL_CREDENTIALS_PATH",
)

NEW_CONFIG_NAMES = (
    "GMAIL_SEND_FROM_EMAIL",
    "GMAIL_OAUTH_CLIENT_SECRET_FILE",
    "GMAIL_OAUTH_TOKEN_FILE",
    "GMAIL_REQUIRED_SCOPE",
)

GMAIL_DEPENDENCY_MODULES = (
    "google.oauth2.credentials",
    "googleapiclient.discovery",
    "google.auth.transport.requests",
)

SCAN_ROOTS = (
    "remote_approval",
    "backend/shopify_sync",
    "scripts",
    "ai_project_manager/tasks",
)

SCAN_EXTENSIONS = {".py", ".md", ".html", ".txt", ".ps1", ".json"}
SAFE_ROOT_CONFIG_FILES = (".env.example",)
SKIP_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "logs",
    "node_modules",
    "venv",
    ".venv",
}

HELPER_MARKERS = (
    "_build_gmail_service",
    "gmail_oauth_setup_helper.py",
    "shopify_review_request_gmail_oauth_setup_helper",
    "shopify_review_request_gmail_readiness_package",
    "shopify_review_request_trustpilot_gmail_oauth_readiness_preflight",
    "shopify_review_request_trustpilot_gmail_draft_create_locked_test",
    "shopify_review_request_trustpilot_gmail_draft_package",
    "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute",
    "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute",
    "shopify_review_request_trustpilot_gmail_one_draft_send_execute",
    "shopify_review_request_trustpilot_gmail_send_audit",
)

PREVIOUS_FLOW_MARKERS = (
    "shopify_review_request_trustpilot_gmail_one_draft_send_execute",
    "shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight",
    "shopify_review_request_trustpilot_gmail_one_draft_locked_runner",
    "shopify_review_request_trustpilot_gmail_send_audit",
    "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute",
    "one_gmail_draft_sent_and_needs_send_audit",
    "trustpilot_gmail_one_draft_send_audit_passed",
    "real_gmail_draft_sent_and_verified",
    "#22621",
)

SUCCESS_REFERENCE_MARKERS = (
    "one_gmail_draft_sent_and_needs_send_audit",
    "trustpilot_gmail_one_draft_send_audit_passed",
    "real_gmail_draft_sent_and_verified",
)

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}")
ACCESS_TOKEN_VALUE_RE = re.compile(r"(?i)\baccess[_-]?token\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
REFRESH_TOKEN_VALUE_RE = re.compile(r"(?i)\brefresh[_-]?token\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
CLIENT_SECRET_VALUE_RE = re.compile(r"(?i)\bclient[_-]?secret\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
PRIVATE_KEY_RE = re.compile(r"(?i)-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----|\bprivate_key\b\s*[:=]")
FULL_GMAIL_ID_RE = re.compile(r"(?i)\"(?:gmail_)?(?:draft|message)_id\"\s*:\s*\"[A-Za-z0-9_-]{16,}\"")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
SECRET_VALUE_RE = re.compile(
    r"(?i)("
    r"shpat_[A-Za-z0-9_]+|"
    r"ya29\.[A-Za-z0-9._-]+|"
    r"bearer\s+[A-Za-z0-9._-]{8,}|"
    r"x-shopify-access-token\s*[:=]\s*[A-Za-z0-9._-]+|"
    r"access[_\s-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"refresh[_\s-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"client[_\s-]?secret\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"private_key\s*[:=]\s*['\"]?[^,'\"]+"
    r")"
)
ALLOWED_EMAILS = {"info@kidstoylover.com"}
ALLOWED_EMAIL_DOMAINS = {"example.invalid"}


def run_shopify_review_request_trustpilot_gmail_config_compatibility_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_files = _read_source_files()
    payload = _build_payload(
        source_files=source_files,
        duration_seconds=round(time.time() - started, 3),
    )
    payload["privacy_scan_summary"] = _privacy_scan_for_payload(payload)
    if not payload["privacy_scan_summary"]["passed"]:
        payload["compatibility_audit_status"] = "blocked_privacy_scan_failed"
        payload["blocking_conditions"].append(
            {
                "status": "blocked_privacy_scan_failed",
                "detail": "Generated report content matched one or more sensitive-pattern counters.",
            }
        )
    payload = _safe_payload(payload)
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _build_payload(source_files: list[dict], duration_seconds: float) -> dict:
    legacy_references = _name_reference_summary(LEGACY_CONFIG_NAMES, source_files, "legacy")
    new_references = _name_reference_summary(NEW_CONFIG_NAMES, source_files, "new")
    helper_references = _marker_reference_summary(HELPER_MARKERS, source_files)
    previous_flow_references = _marker_reference_summary(PREVIOUS_FLOW_MARKERS, source_files)
    success_references = _marker_reference_summary(SUCCESS_REFERENCE_MARKERS, source_files)

    legacy_config_names_detected = [
        item["name"] for item in legacy_references if item["code_reference_count"] > 0
    ]
    new_config_names_detected = [
        item["name"] for item in new_references if item["code_reference_count"] > 0
    ]
    previous_gmail_flow_detected = any(item["code_reference_count"] > 0 for item in previous_flow_references)
    previous_successful_send_reference_detected = (
        _marker_detected("#22621", previous_flow_references)
        and any(item["code_reference_count"] > 0 for item in success_references)
    )
    helper_fallback_detected = _helper_fallback_detected(source_files)

    legacy_env_presence_summary = _legacy_env_presence_summary()
    new_env_presence_summary = _new_env_presence_summary()
    scope_compatibility_result = _scope_compatibility_result(
        legacy_env_presence_summary,
        new_env_presence_summary,
    )
    dependency_status = _gmail_dependency_status()
    blocking_conditions = _blocking_conditions(
        previous_gmail_flow_detected=previous_gmail_flow_detected,
        previous_successful_send_reference_detected=previous_successful_send_reference_detected,
        legacy_config_names_detected=legacy_config_names_detected,
        scope_compatibility_result=scope_compatibility_result,
    )
    compatibility_audit_status = _compatibility_audit_status(
        previous_gmail_flow_detected=previous_gmail_flow_detected,
        previous_successful_send_reference_detected=previous_successful_send_reference_detected,
        legacy_config_names_detected=legacy_config_names_detected,
        helper_fallback_detected=helper_fallback_detected,
    )
    generated_at = utc_now_iso()
    return _safe_payload(
        {
            "timestamp": generated_at,
            "report_generated_at": generated_at,
            "task": TASK_NAME,
            "task_name": TASK_NAME,
            "phase": PHASE,
            "channel": "trustpilot",
            "mode": "gmail-config-compatibility-audit",
            "dry_run": True,
            "compatibility_audit_only": True,
            "command_label": COMMAND_LABEL,
            "success": True,
            "compatibility_audit_status": compatibility_audit_status,
            "previous_gmail_flow_detected": previous_gmail_flow_detected,
            "previous_successful_send_reference_detected": previous_successful_send_reference_detected,
            "previous_flow_reference_basis": (
                "source_code_and_safe_docs_only; logs_not_read; report_values_not_used"
            ),
            "legacy_config_names_detected": legacy_config_names_detected,
            "new_config_names_detected": new_config_names_detected,
            "legacy_config_name_references": legacy_references,
            "new_config_name_references": new_references,
            "gmail_helper_reference_summary": helper_references,
            "previous_gmail_flow_reference_summary": previous_flow_references,
            "previous_success_reference_summary": success_references,
            "legacy_env_presence_summary": legacy_env_presence_summary,
            "new_env_presence_summary": new_env_presence_summary,
            "gmail_dependencies_importable": dependency_status["all_importable"],
            "gmail_dependency_status": dependency_status,
            "scope_compatibility_result": scope_compatibility_result,
            "gmail_send_scope_present": scope_compatibility_result == "send_scope_present",
            "gmail_compose_scope_present": (
                legacy_env_presence_summary["gmail_compose_scope_present"]
                or new_env_presence_summary["gmail_compose_scope_present"]
            ),
            "legacy_gmail_oauth_config_present": legacy_env_presence_summary[
                "legacy_gmail_oauth_config_present"
            ],
            "new_gmail_file_path_config_present": new_env_presence_summary[
                "new_gmail_file_path_config_present"
            ],
            "new_helper_legacy_fallback_detected": helper_fallback_detected,
            "probable_legacy_config_style": _probable_legacy_config_style(
                legacy_config_names_detected,
                previous_gmail_flow_detected,
            ),
            "probable_missing_new_config_style": _probable_missing_new_config_style(
                new_config_names_detected,
                helper_fallback_detected,
            ),
            "compatibility_recommendation": _compatibility_recommendation(
                helper_fallback_detected,
                scope_compatibility_result,
            ),
            "suggested_helper_change": _suggested_helper_change(helper_fallback_detected),
            "blocking_conditions": blocking_conditions,
            "next_admin_action": _next_admin_action(helper_fallback_detected, scope_compatibility_result),
            "privacy_scan_summary": _empty_privacy_scan_summary(),
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
            "dotenv_read": False,
            "log_reports_read": False,
            "shopify_api_call_performed": False,
            "shopify_write_performed": False,
            "shopify_tag_write_performed": False,
            "external_review_api_call_performed": False,
            "trustpilot_api_call_performed": False,
            "kudosi_api_call_performed": False,
            "ali_reviews_api_call_performed": False,
            "translations_register_called": False,
            "detected_issue_summary": (
                "The previous Gmail flow appears to use legacy GOOGLE_GMAIL_* configuration. "
                "The new Review Request helper originally checked GMAIL_* file-path configuration only. "
                "Use a safe compatibility fallback so legacy config can be recognized without printing secret values."
            ),
            "report_paths": {
                "json": f"logs/{REPORT_JSON_PATH.name}",
                "html": f"logs/{REPORT_HTML_PATH.name}",
            },
            "duration_seconds": duration_seconds,
        }
    )


def _read_source_files() -> list[dict]:
    files = []
    for path in _iter_scan_paths():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files.append(
            {
                "path": _relative_path(path),
                "text": text,
            }
        )
    return files


def _iter_scan_paths():
    seen = set()
    for root_name in SCAN_ROOTS:
        root = PROJECT_ROOT / root_name
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else root.rglob("*")
        for path in candidates:
            if not path.is_file() or not _is_safe_scan_path(path):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield path

    for config_name in SAFE_ROOT_CONFIG_FILES:
        path = PROJECT_ROOT / config_name
        if path.exists() and path.is_file() and path.resolve() not in seen:
            seen.add(path.resolve())
            yield path


def _is_safe_scan_path(path: Path) -> bool:
    try:
        parts = path.relative_to(PROJECT_ROOT).parts
    except ValueError:
        return False
    if any(part in SKIP_DIR_NAMES for part in parts):
        return False
    name_lower = path.name.lower()
    if name_lower.startswith(".env") and path.name != ".env.example":
        return False
    if any(secret_word in name_lower for secret_word in ("credential", "credentials", "token")):
        return path.suffix.lower() in {".py", ".md", ".txt"}
    return path.suffix.lower() in SCAN_EXTENSIONS


def _name_reference_summary(names: tuple[str, ...], source_files: list[dict], style: str) -> list[dict]:
    return [
        {
            "name": name,
            "style": style,
            "code_reference_count": sum(item["text"].count(name) for item in source_files),
            "files": _files_with_marker(name, source_files),
            "value_reported": False,
        }
        for name in names
    ]


def _marker_reference_summary(markers: tuple[str, ...], source_files: list[dict]) -> list[dict]:
    return [
        {
            "marker": marker,
            "code_reference_count": sum(item["text"].count(marker) for item in source_files),
            "files": _files_with_marker(marker, source_files),
        }
        for marker in markers
    ]


def _files_with_marker(marker: str, source_files: list[dict]) -> list[str]:
    files = [item["path"] for item in source_files if marker in item["text"]]
    return sorted(files)[:30]


def _marker_detected(marker: str, marker_summary: list[dict]) -> bool:
    return any(item.get("marker") == marker and item.get("code_reference_count", 0) > 0 for item in marker_summary)


def _helper_fallback_detected(source_files: list[dict]) -> bool:
    helper_path = "remote_approval/tasks/shopify_review_request_trustpilot_gmail_oauth_config_helper_task.py"
    for item in source_files:
        if item.get("path") != helper_path:
            continue
        text = item.get("text", "")
        return (
            "legacy_gmail_oauth_config_present" in text
            and "GOOGLE_GMAIL_CLIENT_SECRET" in text
            and "GOOGLE_GMAIL_REFRESH_TOKEN" in text
        )
    return False


def _legacy_env_presence_summary() -> dict:
    rows = [_env_name_status(name, "legacy") for name in LEGACY_CONFIG_NAMES]
    name_map = {row["name"]: row["present"] for row in rows}
    scope_status = _scope_status(os.environ.get("GOOGLE_GMAIL_SCOPES", ""))
    legacy_oauth_config_present = (
        name_map.get("GOOGLE_GMAIL_CLIENT_SECRET") is True
        and name_map.get("GOOGLE_GMAIL_REFRESH_TOKEN") is True
    )
    return {
        "process_environment_only": True,
        "dotenv_read": False,
        "values_reported": False,
        "configured_count": sum(1 for row in rows if row["present"]),
        "expected_name_count": len(rows),
        "names": rows,
        "legacy_gmail_oauth_config_present": legacy_oauth_config_present,
        "legacy_sender_config_present": name_map.get("GMAIL_SEND_FROM") is True,
        "legacy_client_id_present": name_map.get("GOOGLE_GMAIL_CLIENT_ID") is True,
        "legacy_client_secret_present": name_map.get("GOOGLE_GMAIL_CLIENT_SECRET") is True,
        "legacy_refresh_token_present": name_map.get("GOOGLE_GMAIL_REFRESH_TOKEN") is True,
        "legacy_scopes_present": name_map.get("GOOGLE_GMAIL_SCOPES") is True,
        "gmail_send_scope_present": scope_status["gmail_send_scope_present"],
        "gmail_compose_scope_present": scope_status["gmail_compose_scope_present"],
        "scope_compatibility": scope_status["scope_compatibility"],
    }


def _new_env_presence_summary() -> dict:
    rows = [_env_name_status(name, "new") for name in NEW_CONFIG_NAMES]
    name_map = {row["name"]: row["present"] for row in rows}
    required_scope_status = _scope_status(os.environ.get("GMAIL_REQUIRED_SCOPE", ""))
    return {
        "process_environment_only": True,
        "dotenv_read": False,
        "values_reported": False,
        "configured_count": sum(1 for row in rows if row["present"]),
        "expected_name_count": len(rows),
        "names": rows,
        "new_gmail_file_path_config_present": all(
            name_map.get(name) is True for name in NEW_CONFIG_NAMES
        ),
        "new_sender_config_present": name_map.get("GMAIL_SEND_FROM_EMAIL") is True,
        "new_client_secret_file_config_present": name_map.get("GMAIL_OAUTH_CLIENT_SECRET_FILE") is True,
        "new_token_file_config_present": name_map.get("GMAIL_OAUTH_TOKEN_FILE") is True,
        "new_required_scope_present": name_map.get("GMAIL_REQUIRED_SCOPE") is True,
        "gmail_send_scope_present": required_scope_status["gmail_send_scope_present"],
        "gmail_compose_scope_present": required_scope_status["gmail_compose_scope_present"],
        "scope_compatibility": required_scope_status["scope_compatibility"],
    }


def _env_name_status(name: str, style: str) -> dict:
    return {
        "name": name,
        "style": style,
        "present": _env_configured(name),
        "status": "present" if _env_configured(name) else "missing",
        "value_reported": False,
    }


def _env_configured(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def _scope_status(raw_value: str) -> dict:
    scopes = _split_scopes(raw_value)
    send_present = GMAIL_SEND_SCOPE in scopes
    compose_present = GMAIL_COMPOSE_SCOPE in scopes
    if send_present:
        compatibility = "send_scope_present"
    elif compose_present:
        compatibility = "compose_only_not_send_scope"
    elif scopes:
        compatibility = "scope_present_unrecognized"
    else:
        compatibility = "scope_missing"
    return {
        "scope_configured": bool(scopes),
        "gmail_send_scope_present": send_present,
        "gmail_compose_scope_present": compose_present,
        "scope_compatibility": compatibility,
        "scope_values_reported": False,
    }


def _split_scopes(raw_value: str) -> set[str]:
    return {item.strip() for item in re.split(r"[\s,]+", raw_value or "") if item.strip()}


def _scope_compatibility_result(legacy_summary: dict, new_summary: dict) -> str:
    if new_summary["gmail_send_scope_present"] or legacy_summary["gmail_send_scope_present"]:
        return "send_scope_present"
    if new_summary["gmail_compose_scope_present"] or legacy_summary["gmail_compose_scope_present"]:
        return "compose_only_not_send_scope"
    if new_summary["new_required_scope_present"] or legacy_summary["legacy_scopes_present"]:
        return "scope_present_unrecognized"
    return "scope_missing"


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


def _compatibility_audit_status(
    previous_gmail_flow_detected: bool,
    previous_successful_send_reference_detected: bool,
    legacy_config_names_detected: list[str],
    helper_fallback_detected: bool,
) -> str:
    if previous_successful_send_reference_detected and legacy_config_names_detected:
        if helper_fallback_detected:
            return "legacy_config_detected_helper_fallback_available"
        return "legacy_config_detected_new_helper_missing_fallback"
    if previous_gmail_flow_detected and legacy_config_names_detected:
        return "legacy_config_detected_needs_manual_success_review"
    return "needs_manual_review_existing_gmail_config"


def _blocking_conditions(
    previous_gmail_flow_detected: bool,
    previous_successful_send_reference_detected: bool,
    legacy_config_names_detected: list[str],
    scope_compatibility_result: str,
) -> list[dict]:
    conditions = []
    if not previous_gmail_flow_detected:
        conditions.append(
            {
                "status": "needs_manual_review_existing_gmail_flow",
                "detail": "No prior Trustpilot Gmail flow references were found in scanned source files.",
            }
        )
    if previous_gmail_flow_detected and not previous_successful_send_reference_detected:
        conditions.append(
            {
                "status": "needs_manual_review_success_reference",
                "detail": "Prior Gmail task names were found, but source-code success markers were incomplete.",
            }
        )
    if not legacy_config_names_detected:
        conditions.append(
            {
                "status": "needs_manual_review_legacy_config_names",
                "detail": "Legacy GOOGLE_GMAIL_* names were not detected in scanned source files.",
            }
        )
    if scope_compatibility_result == "compose_only_not_send_scope":
        conditions.append(
            {
                "status": "gmail_compose_only_not_send_scope",
                "detail": "Legacy Gmail compose scope can support draft flows but is not enough for real sending.",
            }
        )
    elif scope_compatibility_result in {"scope_missing", "scope_present_unrecognized"}:
        conditions.append(
            {
                "status": "gmail_send_scope_not_confirmed",
                "detail": "gmail.send scope was not confirmed from process environment presence checks.",
            }
        )
    return conditions


def _probable_legacy_config_style(names: list[str], previous_gmail_flow_detected: bool) -> str:
    required = {"GOOGLE_GMAIL_CLIENT_SECRET", "GOOGLE_GMAIL_REFRESH_TOKEN", "GOOGLE_GMAIL_SCOPES"}
    if previous_gmail_flow_detected and required.issubset(set(names)):
        return "legacy_google_gmail_env_vars"
    if names:
        return "legacy_gmail_env_vars_partial"
    return "not_detected"


def _probable_missing_new_config_style(names: list[str], helper_fallback_detected: bool) -> str:
    if helper_fallback_detected:
        return "new_helper_now_supports_legacy_fallback"
    if {"GMAIL_OAUTH_CLIENT_SECRET_FILE", "GMAIL_OAUTH_TOKEN_FILE"}.issubset(set(names)):
        return "new_helper_checks_gmail_file_path_config_only"
    if names:
        return "new_gmail_config_names_detected_partial"
    return "not_detected"


def _compatibility_recommendation(helper_fallback_detected: bool, scope_compatibility_result: str) -> str:
    if helper_fallback_detected:
        recommendation = (
            "The helper can recognize legacy GOOGLE_GMAIL_* config presence without printing values. "
            "Rerun the helper/readiness checks and verify gmail.send scope before any future real send."
        )
    else:
        recommendation = (
            "Add a safe legacy fallback so the helper recognizes GOOGLE_GMAIL_CLIENT_SECRET and "
            "GOOGLE_GMAIL_REFRESH_TOKEN presence without printing values or reading token contents."
        )
    if scope_compatibility_result == "compose_only_not_send_scope":
        recommendation += " Existing compose-only scope is draft-capable but not enough for real send."
    elif scope_compatibility_result != "send_scope_present":
        recommendation += " gmail.send scope still needs verification before real send."
    return recommendation


def _suggested_helper_change(helper_fallback_detected: bool) -> str:
    if helper_fallback_detected:
        return (
            "Fallback detection is present: legacy config can be reported as legacy_config_present while "
            "scope compatibility remains separate and value output stays disabled."
        )
    return (
        "Update the Phase 5.16 helper to set legacy_gmail_oauth_config_present=true when "
        "GOOGLE_GMAIL_CLIENT_SECRET and GOOGLE_GMAIL_REFRESH_TOKEN are present, and report "
        "GOOGLE_GMAIL_SCOPES compatibility without outputting the scope value."
    )


def _next_admin_action(helper_fallback_detected: bool, scope_compatibility_result: str) -> str:
    if helper_fallback_detected and scope_compatibility_result == "send_scope_present":
        return (
            "Rerun the Gmail OAuth/config helper and real-send readiness audit. Keep real sending locked "
            "until a later phase has explicit human approval."
        )
    if helper_fallback_detected:
        return (
            "Rerun the Gmail OAuth/config helper, then verify or add gmail.send permission before any "
            "future real-send phase."
        )
    return (
        "Add the safe legacy fallback to the helper, rerun this audit, and then verify gmail.send scope "
        "before any future real-send phase."
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
    json_text = json.dumps(_safe_payload(payload), ensure_ascii=False, indent=2)
    html_text = _render_html_report(_safe_payload(payload))
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
    REPORT_HTML_PATH.write_text(_render_html_report(_safe_payload(payload)), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status_class = (
        "ok"
        if payload["compatibility_audit_status"] == "legacy_config_detected_helper_fallback_available"
        else "warn"
    )
    legacy_rows = "\n".join(_render_reference_row(row, "name") for row in payload["legacy_config_name_references"])
    new_rows = "\n".join(_render_reference_row(row, "name") for row in payload["new_config_name_references"])
    legacy_env_rows = "\n".join(_render_env_row(row) for row in payload["legacy_env_presence_summary"]["names"])
    new_env_rows = "\n".join(_render_env_row(row) for row in payload["new_env_presence_summary"]["names"])
    blocking_rows = "\n".join(_render_condition_row(row) for row in payload["blocking_conditions"])
    if not blocking_rows:
        blocking_rows = '<tr><td colspan="2">No blocking conditions recorded.</td></tr>'
    privacy_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["privacy_scan_summary"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail Config Compatibility Audit</title>
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
  <h1>Trustpilot Gmail Config Compatibility Audit</h1>
  <p class="status {status_class}">Compatibility audit status: <strong>{escape(payload["compatibility_audit_status"])}</strong></p>
  <p>{escape(payload["compatibility_recommendation"])}</p>
  <p>Mode: <code>{escape(payload["mode"])}</code>. This task scans source references and process environment presence only; it does not read token or credential file contents.</p>
  <table>
    <tbody>
      <tr><th>Previous Gmail flow detected</th><td>{payload["previous_gmail_flow_detected"]}</td></tr>
      <tr><th>Previous successful send reference detected</th><td>{payload["previous_successful_send_reference_detected"]}</td></tr>
      <tr><th>Legacy OAuth config present</th><td>{payload["legacy_gmail_oauth_config_present"]}</td></tr>
      <tr><th>New file-path config present</th><td>{payload["new_gmail_file_path_config_present"]}</td></tr>
      <tr><th>Gmail dependencies importable</th><td>{payload["gmail_dependencies_importable"]}</td></tr>
      <tr><th>Scope compatibility</th><td><code>{escape(payload["scope_compatibility_result"])}</code></td></tr>
      <tr><th>Helper legacy fallback detected</th><td>{payload["new_helper_legacy_fallback_detected"]}</td></tr>
      <tr><th>Gmail network/API/send/draft</th><td>false / false / false / false</td></tr>
      <tr><th>Token or credential file read</th><td>false</td></tr>
      <tr><th>Secret value printed</th><td>false</td></tr>
    </tbody>
  </table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>Environment Presence</h2>
  <p>Values are never reported.</p>
  <h3>Legacy Names</h3>
  <table><thead><tr><th>Name</th><th>Status</th><th>Value reported</th></tr></thead><tbody>{legacy_env_rows}</tbody></table>
  <h3>New Names</h3>
  <table><thead><tr><th>Name</th><th>Status</th><th>Value reported</th></tr></thead><tbody>{new_env_rows}</tbody></table>
  <details>
    <summary>Advanced technical details</summary>
    <p>JSON report: <code>logs/{escape(REPORT_JSON_PATH.name)}</code></p>
    <p>HTML report: <code>logs/{escape(REPORT_HTML_PATH.name)}</code></p>
    <p>Suggested helper change: {escape(payload["suggested_helper_change"])}</p>
    <p>Next admin action: {escape(payload["next_admin_action"])}</p>
    <h2>Legacy Name References</h2>
    <table><thead><tr><th>Name</th><th>Count</th><th>Files</th></tr></thead><tbody>{legacy_rows}</tbody></table>
    <h2>New Name References</h2>
    <table><thead><tr><th>Name</th><th>Count</th><th>Files</th></tr></thead><tbody>{new_rows}</tbody></table>
    <h2>Privacy Scan</h2>
    <table><tbody>{privacy_rows}</tbody></table>
  </details>
</body>
</html>"""


def _render_reference_row(row: dict, key_name: str) -> str:
    files = ", ".join(row.get("files", [])[:8])
    if len(row.get("files", [])) > 8:
        files += ", ..."
    return (
        "<tr>"
        f"<td><code>{escape(str(row.get(key_name, '')))}</code></td>"
        f"<td>{escape(str(row.get('code_reference_count', 0)))}</td>"
        f"<td>{escape(files or '-')}</td>"
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


def _render_condition_row(row: dict) -> str:
    return (
        "<tr>"
        f"<td><code>{escape(str(row.get('status', '')))}</code></td>"
        f"<td>{escape(str(row.get('detail', '')))}</td>"
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
        "json_trustpilot_gmail_config_compatibility_audit_path": str(json_path),
        "html_trustpilot_gmail_config_compatibility_audit_path": str(html_path),
        "compatibility_audit_status": payload["compatibility_audit_status"],
        "previous_gmail_flow_detected": payload["previous_gmail_flow_detected"],
        "previous_successful_send_reference_detected": payload[
            "previous_successful_send_reference_detected"
        ],
        "legacy_config_names_detected": payload["legacy_config_names_detected"],
        "new_config_names_detected": payload["new_config_names_detected"],
        "legacy_env_presence_summary": payload["legacy_env_presence_summary"],
        "new_env_presence_summary": payload["new_env_presence_summary"],
        "gmail_dependencies_importable": payload["gmail_dependencies_importable"],
        "scope_compatibility_result": payload["scope_compatibility_result"],
        "compatibility_recommendation": payload["compatibility_recommendation"],
        "suggested_helper_change": payload["suggested_helper_change"],
        "blocking_conditions": payload["blocking_conditions"],
        "next_admin_action": payload["next_admin_action"],
        "gmail_network_call_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_performed": False,
        "token_file_read": False,
        "credential_file_read": False,
        "secret_value_printed": False,
        "privacy_scan_summary": payload["privacy_scan_summary"],
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 5.18A Gmail config compatibility audit finished.\n"
        f"Compatibility audit status: {payload.get('compatibility_audit_status')}\n"
        f"Previous Gmail flow detected: {payload.get('previous_gmail_flow_detected')}\n"
        f"Previous successful send reference detected: {payload.get('previous_successful_send_reference_detected')}\n"
        f"Legacy config names detected: {', '.join(payload.get('legacy_config_names_detected') or []) or 'None'}\n"
        f"New config names detected: {', '.join(payload.get('new_config_names_detected') or []) or 'None'}\n"
        f"Gmail dependencies importable: {payload.get('gmail_dependencies_importable')}\n"
        f"Scope compatibility: {payload.get('scope_compatibility_result')}\n"
        "Safety: no Gmail network/API call, no draft create/update/delete, no send, no token/credential file read, no Shopify write, and no external review API call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _relative_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


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
    text = SECRET_VALUE_RE.sub("[redacted]", text)
    text = EMAIL_RE.sub(_safe_email_replacement, text)
    text = " ".join(text.split())
    return text[:max_length]


def _safe_email_replacement(match) -> str:
    email = match.group(0)
    normalized = email.lower()
    domain = normalized.rsplit("@", 1)[-1]
    if normalized in ALLOWED_EMAILS or domain in ALLOWED_EMAIL_DOMAINS:
        return email
    return "[redacted-email]"
