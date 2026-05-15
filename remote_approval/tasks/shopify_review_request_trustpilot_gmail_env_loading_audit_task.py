import json
import os
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_env_loading_audit"
COMMAND_LABEL = TASK_NAME
PHASE = "5.21"

REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_env_loading_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_env_loading_audit.html"

LEGACY_GMAIL_ENV_NAMES = (
    "GMAIL_SEND_FROM",
    "GOOGLE_GMAIL_CLIENT_ID",
    "GOOGLE_GMAIL_CLIENT_SECRET",
    "GOOGLE_GMAIL_REFRESH_TOKEN",
    "GOOGLE_GMAIL_SCOPES",
)

NEW_GMAIL_ENV_NAMES = (
    "GMAIL_SEND_FROM_EMAIL",
    "GMAIL_OAUTH_CLIENT_SECRET_FILE",
    "GMAIL_OAUTH_TOKEN_FILE",
    "GMAIL_REQUIRED_SCOPE",
)

SCOPE_ENV_NAMES = ("GOOGLE_GMAIL_SCOPES", "GMAIL_REQUIRED_SCOPE")
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
BROAD_MAIL_SCOPE = "https://mail.google.com/"

SAFE_SCAN_MARKERS = (
    "env_file",
    "dotenv",
    "load_dotenv",
    "os.environ",
    "GOOGLE_GMAIL_SCOPES",
    "GMAIL_REQUIRED_SCOPE",
)

FILE_SCAN_TARGETS = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "backend/Dockerfile",
    "backend/manage.py",
    "backend/config/settings.py",
    "scripts/run_codex_clipboard_task.ps1",
    "scripts/run_codex_task.ps1",
    "remote_approval_runner.py",
    "remote_approval/approval_runner.py",
)

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}")
ACCESS_TOKEN_VALUE_RE = re.compile(r"(?i)\baccess[_-]?token\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
REFRESH_TOKEN_VALUE_RE = re.compile(r"(?i)\brefresh[_-]?token\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
CLIENT_SECRET_VALUE_RE = re.compile(r"(?i)\bclient[_-]?secret\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
PRIVATE_KEY_RE = re.compile(r"(?i)-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----|\bprivate[_-]?key\b\s*[:=]")
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


def run_shopify_review_request_trustpilot_gmail_env_loading_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    env_summary = _process_env_summary()
    dot_env_summary = _dot_env_key_summary()
    file_scan = _file_loading_scan()
    decision = _decision_summary(env_summary, dot_env_summary, file_scan)
    generated_at = utc_now_iso()
    payload = {
        "timestamp": generated_at,
        "report_generated_at": generated_at,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": PHASE,
        "channel": "trustpilot",
        "mode": "gmail-env-loading-audit",
        "dry_run": True,
        "env_loading_audit_only": True,
        "command_label": COMMAND_LABEL,
        "success": True,
        "audit_status": decision["audit_status"],
        "env_loading_audit_status": decision["audit_status"],
        "dashboard_message": decision["dashboard_message"],
        "recommendation": decision["recommendation"],
        "minimum_safe_fix": decision["recommendation"],
        "probable_missing_link": decision["probable_missing_link"],
        "missing_link_explanation": decision["missing_link_explanation"],
        "process_environment_summary": env_summary,
        "dot_env_summary": dot_env_summary,
        "file_loading_scan_summary": file_scan,
        "os_environ_legacy_gmail_key_count": env_summary["legacy_gmail_key_count"],
        "os_environ_new_gmail_key_count": env_summary["new_gmail_key_count"],
        "os_environ_gmail_keys_detected": env_summary["gmail_keys_detected"],
        "scope_key_detected_in_os_environ": env_summary["scope_key_detected"],
        "scope_value_nonempty_in_os_environ": env_summary["scope_value_nonempty"],
        "os_environ_compose_scope_detected": env_summary["compose_scope_detected"],
        "os_environ_send_scope_detected": env_summary["send_scope_detected"],
        "os_environ_broad_mail_scope_detected": env_summary["broad_mail_scope_detected"],
        "dot_env_file_exists": dot_env_summary["dot_env_file_exists"],
        "dot_env_gmail_keys_detected": dot_env_summary["dot_env_gmail_keys_detected"],
        "dot_env_legacy_gmail_key_count": dot_env_summary["dot_env_legacy_gmail_key_count"],
        "dot_env_new_gmail_key_count": dot_env_summary["dot_env_new_gmail_key_count"],
        "dot_env_scope_key_detected": dot_env_summary["dot_env_scope_key_detected"],
        "scope_key_detected_in_dot_env": dot_env_summary["dot_env_scope_key_detected"],
        "dot_env_value_read_or_printed": False,
        "docker_compose_env_file_detected": file_scan["docker_compose_env_file_detected"],
        "django_dotenv_loader_detected": file_scan["django_dotenv_loader_detected"],
        "remote_approval_dotenv_loader_detected": file_scan["remote_approval_dotenv_loader_detected"],
        "codex_runner_env_forwarding_detected": file_scan["codex_runner_env_forwarding_detected"],
        "searched_key_phrases": list(SAFE_SCAN_MARKERS),
        "gmail_network_call_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_performed": False,
        "gmail_draft_update_performed": False,
        "gmail_draft_delete_performed": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "email_sent": False,
        "token_file_read": False,
        "credential_file_read": False,
        "secret_value_printed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "translations_register_called": False,
        "privacy_scan_summary": _empty_privacy_scan_summary(),
        "safety_message": (
            "No Gmail network/API call was made. No draft was created, updated, deleted, or sent. "
            "No Shopify, Trustpilot, Kudosi, or Ali Reviews API call was made."
        ),
        "report_paths": {
            "json": f"logs/{REPORT_JSON_PATH.name}",
            "html": f"logs/{REPORT_HTML_PATH.name}",
        },
        "duration_seconds": round(time.time() - started, 3),
        "detected_issue_summary": decision["detected_issue_summary"],
    }
    payload["privacy_scan_summary"] = _privacy_scan_for_payload(payload)
    if not payload["privacy_scan_summary"]["passed"]:
        payload["audit_status"] = "blocked_privacy_scan_failed"
        payload["env_loading_audit_status"] = "blocked_privacy_scan_failed"
        payload["dashboard_message"] = "Gmail env loading audit is blocked because the generated report privacy scan failed."
        payload["recommendation"] = "Inspect privacy scan counters only, then rerun the audit after correcting report content."
        payload["minimum_safe_fix"] = payload["recommendation"]
        payload["probable_missing_link"] = "privacy_scan_failed"
    payload = _safe_payload(payload)
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _process_env_summary() -> dict:
    legacy_presence = _expected_key_presence(LEGACY_GMAIL_ENV_NAMES, "legacy", os.environ)
    new_presence = _expected_key_presence(NEW_GMAIL_ENV_NAMES, "new", os.environ)
    scope_summary = _process_scope_summary()
    return {
        "process_environment_only": True,
        "values_reported": False,
        "scope_values_reported": False,
        "legacy_expected_keys": legacy_presence,
        "new_expected_keys": new_presence,
        "legacy_gmail_key_count": sum(1 for row in legacy_presence if row["present"]),
        "new_gmail_key_count": sum(1 for row in new_presence if row["present"]),
        "gmail_keys_detected": [
            row["name"] for row in (*legacy_presence, *new_presence) if row["present"]
        ],
        "scope_key_detected": scope_summary["scope_key_detected"],
        "scope_value_nonempty": scope_summary["scope_value_nonempty"],
        "compose_scope_detected": scope_summary["compose_scope_detected"],
        "send_scope_detected": scope_summary["send_scope_detected"],
        "broad_mail_scope_detected": scope_summary["broad_mail_scope_detected"],
        "recognized_scope_detected": scope_summary["recognized_scope_detected"],
    }


def _expected_key_presence(names: tuple[str, ...], style: str, environ) -> list[dict]:
    return [
        {
            "name": name,
            "style": style,
            "present": name in environ,
            "status": "present" if name in environ else "missing",
            "value_reported": False,
        }
        for name in names
    ]


def _process_scope_summary() -> dict:
    scope_key_detected = False
    scope_value_nonempty = False
    compose_scope_detected = False
    send_scope_detected = False
    broad_mail_scope_detected = False
    for name in SCOPE_ENV_NAMES:
        if name not in os.environ:
            continue
        scope_key_detected = True
        scopes = _split_scopes(os.environ.get(name, ""))
        if scopes:
            scope_value_nonempty = True
        compose_scope_detected = compose_scope_detected or GMAIL_COMPOSE_SCOPE in scopes
        send_scope_detected = send_scope_detected or GMAIL_SEND_SCOPE in scopes
        broad_mail_scope_detected = broad_mail_scope_detected or BROAD_MAIL_SCOPE in scopes
    return {
        "scope_key_detected": scope_key_detected,
        "scope_value_nonempty": scope_value_nonempty,
        "compose_scope_detected": compose_scope_detected,
        "send_scope_detected": send_scope_detected,
        "broad_mail_scope_detected": broad_mail_scope_detected,
        "recognized_scope_detected": compose_scope_detected or send_scope_detected or broad_mail_scope_detected,
    }


def _split_scopes(raw_value: str) -> set[str]:
    return {item.strip() for item in re.split(r"[\s,;]+", raw_value or "") if item.strip()}


def _dot_env_key_summary() -> dict:
    path = PROJECT_ROOT / ".env"
    summary = {
        "dot_env_file_exists": path.exists(),
        "dot_env_file_read_for_key_names": False,
        "dot_env_value_read_or_printed": False,
        "dot_env_value_stored_or_reported": False,
        "dot_env_gmail_keys_detected": [],
        "dot_env_expected_legacy_keys": _dot_env_key_rows(LEGACY_GMAIL_ENV_NAMES, set(), "legacy"),
        "dot_env_expected_new_keys": _dot_env_key_rows(NEW_GMAIL_ENV_NAMES, set(), "new"),
        "dot_env_legacy_gmail_key_count": 0,
        "dot_env_new_gmail_key_count": 0,
        "dot_env_scope_key_detected": False,
        "read_error_sanitized": "",
    }
    if not path.exists():
        return summary

    try:
        key_names = _read_dot_env_key_names(path)
    except OSError:
        summary["read_error_sanitized"] = "unable_to_read_dot_env"
        return summary

    expected = set(LEGACY_GMAIL_ENV_NAMES) | set(NEW_GMAIL_ENV_NAMES)
    detected = sorted(key for key in key_names if key in expected)
    legacy_rows = _dot_env_key_rows(LEGACY_GMAIL_ENV_NAMES, key_names, "legacy")
    new_rows = _dot_env_key_rows(NEW_GMAIL_ENV_NAMES, key_names, "new")
    summary.update(
        {
            "dot_env_file_read_for_key_names": True,
            "dot_env_gmail_keys_detected": detected,
            "dot_env_expected_legacy_keys": legacy_rows,
            "dot_env_expected_new_keys": new_rows,
            "dot_env_legacy_gmail_key_count": sum(1 for row in legacy_rows if row["present"]),
            "dot_env_new_gmail_key_count": sum(1 for row in new_rows if row["present"]),
            "dot_env_scope_key_detected": any(name in key_names for name in SCOPE_ENV_NAMES),
        }
    )
    return summary


def _read_dot_env_key_names(path: Path) -> set[str]:
    key_names = set()
    with path.open("r", encoding="utf-8", errors="replace") as env_file:
        for raw_line in env_file:
            key = _key_name_before_equals(raw_line)
            if key:
                key_names.add(key)
    return key_names


def _key_name_before_equals(raw_line: str) -> str:
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return ""
    key = stripped.split("=", 1)[0].strip()
    if key.startswith("export "):
        key = key[len("export ") :].strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return ""
    return key


def _dot_env_key_rows(names: tuple[str, ...], key_names: set[str], style: str) -> list[dict]:
    return [
        {
            "name": name,
            "style": style,
            "present": name in key_names,
            "status": "present" if name in key_names else "missing",
            "value_reported": False,
        }
        for name in names
    ]


def _file_loading_scan() -> dict:
    file_rows = [_file_marker_summary(relative_path) for relative_path in FILE_SCAN_TARGETS]
    docker_rows = [
        row
        for row in file_rows
        if row["relative_path"] in {"docker-compose.yml", "docker-compose.yaml"}
    ]
    django_rows = [
        row
        for row in file_rows
        if row["relative_path"] in {"backend/manage.py", "backend/config/settings.py"}
    ]
    remote_rows = [
        row
        for row in file_rows
        if row["relative_path"] in {"remote_approval_runner.py", "remote_approval/approval_runner.py"}
    ]
    runner_rows = [
        row
        for row in file_rows
        if row["relative_path"] in {"scripts/run_codex_clipboard_task.ps1", "scripts/run_codex_task.ps1"}
    ]
    return {
        "files_scanned": file_rows,
        "values_reported": False,
        "lines_reported": False,
        "docker_compose_env_file_detected": any(_marker(row, "env_file") for row in docker_rows),
        "django_dotenv_loader_detected": any(
            _marker(row, "dotenv") or _marker(row, "load_dotenv") for row in django_rows
        ),
        "remote_approval_dotenv_loader_detected": any(
            _marker(row, "dotenv") or _marker(row, "load_dotenv") for row in remote_rows
        ),
        "codex_runner_env_forwarding_detected": any(
            _marker(row, "GOOGLE_GMAIL_SCOPES")
            or _marker(row, "GMAIL_REQUIRED_SCOPE")
            or _marker(row, "dotenv")
            or _marker(row, "load_dotenv")
            for row in runner_rows
        ),
        "remote_approval_os_environ_detected": any(_marker(row, "os.environ") for row in remote_rows),
        "django_os_environ_detected": any(_marker(row, "os.environ") for row in django_rows),
    }


def _file_marker_summary(relative_path: str) -> dict:
    path = PROJECT_ROOT / relative_path
    row = {
        "relative_path": relative_path,
        "present": path.exists(),
        "scanned": False,
        "markers": {marker: False for marker in SAFE_SCAN_MARKERS},
        "line_content_reported": False,
        "secret_values_reported": False,
        "read_error_sanitized": "",
    }
    if not path.exists() or not path.is_file():
        return row
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        row["read_error_sanitized"] = "unable_to_read_file"
        return row
    row["scanned"] = True
    row["markers"] = {marker: _detect_marker(text, marker) for marker in SAFE_SCAN_MARKERS}
    return row


def _detect_marker(text: str, marker: str) -> bool:
    if marker == "dotenv":
        return bool(re.search(r"(?i)(?:\bfrom\s+dotenv\b|\bimport\s+dotenv\b|\bdotenv\b)", text))
    if marker == "env_file":
        return bool(re.search(r"(?m)^\s*env_file\s*:", text))
    return marker in text


def _marker(row: dict, marker: str) -> bool:
    return ((row or {}).get("markers") or {}).get(marker) is True


def _decision_summary(env_summary: dict, dot_env_summary: dict, file_scan: dict) -> dict:
    if env_summary["send_scope_detected"]:
        return {
            "audit_status": "gmail_send_scope_available_in_runner_env",
            "dashboard_message": "Gmail send permission is available.",
            "probable_missing_link": "none_runner_env_has_gmail_send_scope",
            "missing_link_explanation": (
                "The runner process environment has a recognized Gmail send scope."
            ),
            "recommendation": (
                "Real send route can proceed only after final preflight, exactly one eligible candidate, "
                "and explicit approvals."
            ),
            "detected_issue_summary": (
                "Gmail send scope is visible in the runner environment. No Gmail API call was made."
            ),
        }
    if env_summary["broad_mail_scope_detected"]:
        return {
            "audit_status": "gmail_send_scope_available_in_runner_env",
            "dashboard_message": "Gmail send permission is available.",
            "probable_missing_link": "none_runner_env_has_broad_mail_scope",
            "missing_link_explanation": (
                "The runner process environment has the broad Gmail mail scope, which can cover send."
            ),
            "recommendation": (
                "Real send route can proceed only after final preflight, exactly one eligible candidate, "
                "and explicit approvals; prefer least-privilege gmail.send when possible."
            ),
            "detected_issue_summary": (
                "A broad Gmail mail scope is visible in the runner environment. No Gmail API call was made."
            ),
        }
    if env_summary["compose_scope_detected"]:
        return {
            "audit_status": "gmail_compose_scope_available_in_runner_env",
            "dashboard_message": "Gmail draft permission is available.",
            "probable_missing_link": "none_runner_env_has_gmail_compose_scope",
            "missing_link_explanation": (
                "The runner process environment has a recognized Gmail compose scope."
            ),
            "recommendation": (
                "Draft-only route can proceed once exactly one eligible candidate exists."
            ),
            "detected_issue_summary": (
                "Gmail compose scope is visible in the runner environment. No Gmail API call was made."
            ),
        }
    if dot_env_summary["dot_env_scope_key_detected"] and not env_summary["scope_key_detected"]:
        return {
            "audit_status": "env_file_has_gmail_scope_but_runner_env_missing",
            "dashboard_message": (
                "Gmail settings may exist in `.env`, but the automation runner cannot see them yet."
            ),
            "probable_missing_link": _probable_dot_env_missing_link(file_scan),
            "missing_link_explanation": (
                "A Gmail scope key name exists in `.env`, but neither supported scope key name is present "
                "in the runner process environment."
            ),
            "recommendation": (
                "Add safe `.env` loading for remote approval tasks, or run runner with required env variables injected."
            ),
            "detected_issue_summary": (
                ".env contains a Gmail scope key name, but the remote approval runner environment does not. "
                "No Gmail API call was made."
            ),
        }
    if not dot_env_summary["dot_env_scope_key_detected"] and not env_summary["scope_key_detected"]:
        return {
            "audit_status": "gmail_scope_not_configured_anywhere_detected",
            "dashboard_message": "Gmail permission is not configured yet.",
            "probable_missing_link": "gmail_scope_key_missing_from_dot_env_and_runner_env",
            "missing_link_explanation": (
                "No supported Gmail scope key name was found in `.env` key names or in process environment keys."
            ),
            "recommendation": (
                f"Add `GOOGLE_GMAIL_SCOPES={GMAIL_COMPOSE_SCOPE}` for draft-only mode, or "
                f"`GMAIL_REQUIRED_SCOPE={GMAIL_SEND_SCOPE}` for direct send after approval."
            ),
            "detected_issue_summary": (
                "No supported Gmail scope key name was found in `.env` or the runner environment. "
                "No Gmail API call was made."
            ),
        }
    if env_summary["scope_key_detected"] and not env_summary["recognized_scope_detected"]:
        return {
            "audit_status": "gmail_scope_key_present_but_scope_unrecognized",
            "dashboard_message": "Gmail permission is not configured yet.",
            "probable_missing_link": "runner_env_has_scope_key_without_recognized_gmail_scope",
            "missing_link_explanation": (
                "A supported Gmail scope key is present in process environment, but no recognized compose/send scope "
                "was detected."
            ),
            "recommendation": (
                f"Use `{GMAIL_COMPOSE_SCOPE}` for draft-only mode or `{GMAIL_SEND_SCOPE}` for direct send after approval."
            ),
            "detected_issue_summary": (
                "A Gmail scope key is present in the runner environment, but no recognized scope was detected. "
                "No Gmail API call was made."
            ),
        }
    return {
        "audit_status": "gmail_scope_key_name_detected_needs_manual_review",
        "dashboard_message": "Gmail permission is not configured yet.",
        "probable_missing_link": "scope_key_name_detected_but_value_not_available_to_audit",
        "missing_link_explanation": (
            "A Gmail scope key name was detected, but the audit cannot confirm a recognized scope from runner env."
        ),
        "recommendation": (
            "Verify runner environment injection or add safe `.env` loading for remote approval tasks."
        ),
        "detected_issue_summary": (
            "A Gmail scope key name was detected, but no recognized runner scope was confirmed. "
            "No Gmail API call was made."
        ),
    }


def _probable_dot_env_missing_link(file_scan: dict) -> str:
    docker_env_file = file_scan.get("docker_compose_env_file_detected") is True
    remote_loader = file_scan.get("remote_approval_dotenv_loader_detected") is True
    runner_forwarding = file_scan.get("codex_runner_env_forwarding_detected") is True
    if docker_env_file and not remote_loader and not runner_forwarding:
        return "docker_compose_loads_env_file_but_local_remote_approval_runner_does_not"
    if not remote_loader and not runner_forwarding:
        return "remote_approval_runner_has_no_detected_dotenv_loader_or_scope_env_forwarding"
    if not remote_loader:
        return "remote_approval_runner_has_no_detected_dotenv_loader"
    return "runner_env_missing_scope_despite_detected_loader_markers"


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
    safe_payload = _safe_payload(payload)
    json_text = json.dumps(safe_payload, ensure_ascii=False, indent=2)
    html_text = _render_html_report(safe_payload)
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
        if payload["audit_status"]
        in {
            "gmail_compose_scope_available_in_runner_env",
            "gmail_send_scope_available_in_runner_env",
        }
        else "warn"
    )
    env_rows = _env_presence_rows(
        payload["process_environment_summary"]["legacy_expected_keys"],
        payload["process_environment_summary"]["new_expected_keys"],
    )
    dot_env_rows = _env_presence_rows(
        payload["dot_env_summary"]["dot_env_expected_legacy_keys"],
        payload["dot_env_summary"]["dot_env_expected_new_keys"],
    )
    file_rows = "\n".join(_file_scan_row(row) for row in payload["file_loading_scan_summary"]["files_scanned"])
    privacy_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["privacy_scan_summary"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail Env Loading Audit</title>
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
  <h1>Trustpilot Gmail Env Loading Audit</h1>
  <p class="status {status_class}">Audit status: <strong>{escape(payload["audit_status"])}</strong></p>
  <p>{escape(payload["dashboard_message"])}</p>
  <p>{escape(payload["recommendation"])}</p>
  <p>Mode: <code>{escape(payload["mode"])}</code>. This task checks key presence and loader markers only; it does not call Gmail, read token files, create drafts, send email, or write Shopify data.</p>
  <table>
    <tbody>
      <tr><th>Legacy Gmail env keys in process</th><td>{payload["os_environ_legacy_gmail_key_count"]}</td></tr>
      <tr><th>New Gmail env keys in process</th><td>{payload["os_environ_new_gmail_key_count"]}</td></tr>
      <tr><th>.env exists</th><td>{payload["dot_env_file_exists"]}</td></tr>
      <tr><th>.env legacy Gmail keys</th><td>{payload["dot_env_legacy_gmail_key_count"]}</td></tr>
      <tr><th>.env new Gmail keys</th><td>{payload["dot_env_new_gmail_key_count"]}</td></tr>
      <tr><th>Scope key in process env</th><td>{payload["scope_key_detected_in_os_environ"]}</td></tr>
      <tr><th>Scope key in .env</th><td>{payload["scope_key_detected_in_dot_env"]}</td></tr>
      <tr><th>Docker Compose env_file detected</th><td>{payload["docker_compose_env_file_detected"]}</td></tr>
      <tr><th>Remote approval dotenv loader detected</th><td>{payload["remote_approval_dotenv_loader_detected"]}</td></tr>
      <tr><th>Probable missing link</th><td><code>{escape(payload["probable_missing_link"])}</code></td></tr>
      <tr><th>.env values read or printed</th><td>false</td></tr>
      <tr><th>Secret values printed</th><td>false</td></tr>
    </tbody>
  </table>
  <h2>Process Environment Key Presence</h2>
  <table><thead><tr><th>Name</th><th>Status</th><th>Value reported</th></tr></thead><tbody>{env_rows}</tbody></table>
  <h2>.env Key Presence</h2>
  <p>Only key names before <code>=</code> are recorded for expected Gmail keys. Values are not reported.</p>
  <table><thead><tr><th>Name</th><th>Status</th><th>Value reported</th></tr></thead><tbody>{dot_env_rows}</tbody></table>
  <details>
    <summary>Advanced technical details</summary>
    <p>JSON report: <code>logs/{escape(REPORT_JSON_PATH.name)}</code></p>
    <p>HTML report: <code>logs/{escape(REPORT_HTML_PATH.name)}</code></p>
    <p>Missing link explanation: {escape(payload["missing_link_explanation"])}</p>
    <h2>Loader Marker Scan</h2>
    <table><thead><tr><th>File</th><th>Present</th><th>Scanned</th><th>Markers detected</th></tr></thead><tbody>{file_rows}</tbody></table>
    <h2>Privacy Scan</h2>
    <table><tbody>{privacy_rows}</tbody></table>
  </details>
</body>
</html>"""


def _env_presence_rows(legacy_rows: list[dict], new_rows: list[dict]) -> str:
    return "\n".join(_env_presence_row(row) for row in (*legacy_rows, *new_rows))


def _env_presence_row(row: dict) -> str:
    return (
        "<tr>"
        f"<td><code>{escape(str(row.get('name', '')))}</code></td>"
        f"<td>{escape(str(row.get('status', '')))}</td>"
        f"<td>{escape(str(row.get('value_reported') is True))}</td>"
        "</tr>"
    )


def _file_scan_row(row: dict) -> str:
    markers = ", ".join(
        marker for marker, detected in (row.get("markers") or {}).items() if detected
    ) or "-"
    return (
        "<tr>"
        f"<td><code>{escape(str(row.get('relative_path', '')))}</code></td>"
        f"<td>{escape(str(row.get('present') is True))}</td>"
        f"<td>{escape(str(row.get('scanned') is True))}</td>"
        f"<td>{escape(markers)}</td>"
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
        "json_trustpilot_gmail_env_loading_audit_path": str(json_path),
        "html_trustpilot_gmail_env_loading_audit_path": str(html_path),
        "audit_status": payload["audit_status"],
        "env_loading_audit_status": payload["env_loading_audit_status"],
        "os_environ_legacy_gmail_key_count": payload["os_environ_legacy_gmail_key_count"],
        "os_environ_new_gmail_key_count": payload["os_environ_new_gmail_key_count"],
        "dot_env_file_exists": payload["dot_env_file_exists"],
        "dot_env_legacy_gmail_key_count": payload["dot_env_legacy_gmail_key_count"],
        "dot_env_new_gmail_key_count": payload["dot_env_new_gmail_key_count"],
        "scope_key_detected_in_os_environ": payload["scope_key_detected_in_os_environ"],
        "scope_key_detected_in_dot_env": payload["scope_key_detected_in_dot_env"],
        "docker_compose_env_file_detected": payload["docker_compose_env_file_detected"],
        "django_dotenv_loader_detected": payload["django_dotenv_loader_detected"],
        "remote_approval_dotenv_loader_detected": payload["remote_approval_dotenv_loader_detected"],
        "codex_runner_env_forwarding_detected": payload["codex_runner_env_forwarding_detected"],
        "probable_missing_link": payload["probable_missing_link"],
        "recommendation": payload["recommendation"],
        "gmail_network_call_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_performed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "translations_register_called": False,
        "secret_value_printed": False,
        "dot_env_value_read_or_printed": False,
        "privacy_scan_summary": payload["privacy_scan_summary"],
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 5.21 Gmail env loading audit finished.\n"
        f"Audit status: {payload.get('audit_status')}\n"
        f"os.environ legacy Gmail key count: {payload.get('os_environ_legacy_gmail_key_count')}\n"
        f"os.environ new Gmail key count: {payload.get('os_environ_new_gmail_key_count')}\n"
        f".env exists: {payload.get('dot_env_file_exists')}\n"
        f".env legacy Gmail key count: {payload.get('dot_env_legacy_gmail_key_count')}\n"
        f".env new Gmail key count: {payload.get('dot_env_new_gmail_key_count')}\n"
        f"Scope key in os.environ: {payload.get('scope_key_detected_in_os_environ')}\n"
        f"Scope key in .env: {payload.get('scope_key_detected_in_dot_env')}\n"
        f"Docker Compose env_file detected: {payload.get('docker_compose_env_file_detected')}\n"
        f"Remote approval dotenv loader detected: {payload.get('remote_approval_dotenv_loader_detected')}\n"
        f"Probable missing link: {payload.get('probable_missing_link')}\n"
        f"Recommendation: {payload.get('recommendation')}\n"
        "Safety: no Gmail network/API call, no draft create/update/delete, no send, no token/credential file read, no Shopify write, and no external review API call.\n"
        f"Privacy scan passed: {payload['privacy_scan_summary'].get('passed')}\n"
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
