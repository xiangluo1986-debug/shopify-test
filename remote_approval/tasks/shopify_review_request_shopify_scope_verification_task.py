import json
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_shopify_scope_verification"
COMMAND_LABEL = "shopify_review_request_shopify_scope_verification_read_only"
REPORT_DIR = LOG_DIR / "codex_runs"
REPORT_JSON_PATH = REPORT_DIR / "shopify_review_request_shopify_scope_verification.json"
REPORT_HTML_PATH = REPORT_DIR / "shopify_review_request_shopify_scope_verification.html"
SQLITE_DB_PATH = PROJECT_ROOT / "backend" / "db.sqlite3"

SHOP_DOMAIN = "kidstoylover.myshopify.com"
DOCKER_TIMEOUT_SECONDS = 120
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_SCOPE_VERIFICATION_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_SCOPE_VERIFICATION_JSON_END"
REQUIRED_SCOPES = ("read_orders", "read_all_orders")
REAUTHORIZE_MESSAGE = "Reauthorize or reinstall the Shopify app, then save the new access token before sending."

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_VALUE_RE = re.compile(
    r"(?i)("
    r"shpat_[A-Za-z0-9_]+|"
    r"ya29\.[A-Za-z0-9._-]+|"
    r"bearer\s+[A-Za-z0-9._-]{8,}|"
    r"x-shopify-access-token\s*[:=]\s*[A-Za-z0-9._-]+|"
    r"access[_\s-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"refresh[_\s-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"client[_\s-]?secret\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"api[_\s-]?key\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"authorization\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"password\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{8,}"
    r")"
)


def run_shopify_review_request_shopify_scope_verification_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    verification = _run_protected_scope_verification()
    payload = _build_payload(verification, round(time.time() - started, 3))
    payload = _apply_self_privacy_assertion(payload)
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _run_protected_scope_verification() -> dict:
    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "web",
        "python",
        "manage.py",
        "shell",
        "-c",
        _django_shell_script(),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=False,
            timeout=DOCKER_TIMEOUT_SECONDS,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            **_empty_verification(),
            "scope_verification_status": "scope_check_runtime_timeout",
            "failure_type": "timeout",
            "error_sanitized": f"Scope verification timed out after {DOCKER_TIMEOUT_SECONDS} seconds.",
            "stdout_tail": _tail(_decode_bytes(exc.stdout or b"")),
            "stderr_tail": _tail(_decode_bytes(exc.stderr or b"")),
        }
    except FileNotFoundError as exc:
        return {
            **_empty_verification(),
            "scope_verification_status": "scope_check_runtime_unavailable",
            "failure_type": "docker_command_not_found",
            "error_sanitized": _sanitize_text(str(exc)),
        }
    except PermissionError as exc:
        return {
            **_empty_verification(),
            "scope_verification_status": "scope_check_runtime_unavailable",
            "failure_type": "docker_permission_denied",
            "error_sanitized": _sanitize_text(str(exc)),
        }

    stdout = _decode_bytes(completed.stdout)
    stderr = _decode_bytes(completed.stderr)
    parsed = _extract_payload(stdout)
    if not parsed:
        docker_failure = {
            **_empty_verification(),
            "scope_verification_status": "scope_check_payload_missing",
            "failure_type": "scope_check_payload_missing",
            "error_sanitized": "Scope verification did not return parseable JSON.",
            "exit_code": completed.returncode,
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "manual_verification_command": (
                "docker compose exec -T web python manage.py shell -c "
                "\"from shopify_sync.models import ShopifyInstallation; "
                "from shopify_sync.sync_helpers import shopify_get; "
                "print('Use /admin/oauth/access_scopes.json; do not print the token.')\""
            ),
        }
        fallback = _run_host_sqlite_scope_verification(docker_failure)
        if fallback.get("fallback_attempted") is True:
            return fallback
        return docker_failure
    parsed = {**_empty_verification(), **parsed}
    parsed["exit_code"] = completed.returncode
    if completed.returncode != 0 and not parsed.get("error_sanitized"):
        parsed["error_sanitized"] = _sanitize_text(stderr or stdout or "Scope verification failed.")
    parsed["stdout_tail"] = "" if parsed.get("success") else _tail(stdout)
    parsed["stderr_tail"] = "" if parsed.get("success") else _tail(stderr)
    return parsed


def _run_host_sqlite_scope_verification(docker_failure: dict) -> dict:
    result = {
        **_empty_verification(),
        "fallback_attempted": True,
        "fallback_source": "host_sqlite",
        "docker_failure_type": _safe_text(docker_failure.get("failure_type"), 120),
        "docker_error_sanitized": _safe_text(docker_failure.get("error_sanitized"), 500),
        "docker_stderr_tail": _safe_text(docker_failure.get("stderr_tail"), 800),
        "scope_check_helper_available": True,
    }
    if not SQLITE_DB_PATH.exists():
        result["scope_verification_status"] = "scope_check_runtime_unavailable"
        result["failure_type"] = "sqlite_db_missing"
        result["error_sanitized"] = "Local SQLite database was not found."
        result["next_admin_action"] = "Run the scope verification in Docker or verify the local database path."
        return result

    try:
        connection = sqlite3.connect(SQLITE_DB_PATH)
        connection.row_factory = sqlite3.Row
        try:
            installation = connection.execute(
                "SELECT shop, access_token, scope FROM shopify_sync_shopifyinstallation WHERE shop=? "
                "ORDER BY id DESC LIMIT 1",
                [SHOP_DOMAIN],
            ).fetchone() or connection.execute(
                "SELECT shop, access_token, scope FROM shopify_sync_shopifyinstallation ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not installation:
                result["scope_verification_status"] = "shopify_installation_missing"
                result["failure_type"] = "shopify_installation_missing"
                result["next_admin_action"] = "Install or reauthorize the Shopify app so a local installation record exists."
                return result

            result["shopify_installation_found"] = True
            configured_scopes = _split_scopes(installation["scope"] or "")
            result["configured_scope_source"] = "ShopifyInstallation.scope"
            result["configured_read_orders_present"] = "read_orders" in configured_scopes
            result["configured_read_all_orders_present"] = "read_all_orders" in configured_scopes

            access_token = str(installation["access_token"] or "")
            result["shopify_credentials_found"] = bool(access_token)
            if not access_token:
                result["scope_verification_status"] = "missing_shopify_access_token"
                result["failure_type"] = "missing_shopify_access_token"
                result["next_admin_action"] = "Reauthorize the Shopify app and save the new access token before sending."
                return result

            shop = str(installation["shop"] or SHOP_DOMAIN)
            handles = _host_access_scope_handles(shop, access_token, result)
            result["token_scope_source"] = "shopify_access_scopes_endpoint" if handles else "unavailable"
            result["read_orders_present"] = "read_orders" in handles
            result["read_all_orders_present"] = "read_all_orders" in handles
            result["reauthorization_required"] = not all(scope in handles for scope in REQUIRED_SCOPES)
            if result["read_orders_present"] and result["read_all_orders_present"]:
                result["scope_verification_status"] = "active_token_scope_verified"
                result["success"] = True
                result["next_admin_action"] = "No reauthorization needed for Review Request customer history reads."
            elif handles and result["read_orders_present"]:
                result["scope_verification_status"] = "read_all_orders_missing_reauthorization_required"
                result["next_admin_action"] = REAUTHORIZE_MESSAGE
            elif handles:
                result["scope_verification_status"] = "read_orders_scope_missing_reauthorization_required"
                result["next_admin_action"] = "Reauthorize or reinstall the Shopify app with read_orders and read_all_orders before sending."
            else:
                result["scope_verification_status"] = "access_scope_endpoint_unavailable"
                result["next_admin_action"] = (
                    "Run the scope verification again after confirming network access; if it still fails, "
                    "manually verify /admin/oauth/access_scopes.json without printing the token."
                )
            return result
        finally:
            connection.close()
    except Exception as exc:
        result["scope_verification_status"] = "scope_verification_exception"
        result["failure_type"] = "host_sqlite_scope_verification_exception"
        result["error_sanitized"] = _safe_text(exc, 600)
        return result


def _host_access_scope_handles(shop, access_token, result):
    request = urllib.request.Request(
        f"https://{shop}/admin/oauth/access_scopes.json",
        headers={
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        },
        method="GET",
    )
    body = b""
    try:
        result["shopify_api_call_performed"] = True
        with urllib.request.urlopen(request, timeout=30) as opened:
            body = opened.read()
            result["shopify_http_status"] = opened.status
    except urllib.error.HTTPError as exc:
        result["shopify_api_call_performed"] = True
        result["shopify_http_status"] = exc.code
        result["shopify_api_response_error_count"] = _int_or_zero(
            result.get("shopify_api_response_error_count")
        ) + 1
        result.setdefault("shopify_api_response_errors_sanitized", []).append(
            f"Shopify access scope HTTP error {exc.code}"
        )
        return set()
    except urllib.error.URLError as exc:
        result["shopify_api_call_performed"] = True
        result["shopify_api_response_error_count"] = _int_or_zero(
            result.get("shopify_api_response_error_count")
        ) + 1
        result.setdefault("shopify_api_response_errors_sanitized", []).append(
            _safe_text(f"Shopify access scope request failed: {exc.reason}", 240)
        )
        return set()

    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        result["shopify_api_response_error_count"] = _int_or_zero(
            result.get("shopify_api_response_error_count")
        ) + 1
        result.setdefault("shopify_api_response_errors_sanitized", []).append(
            "Shopify access scope non-JSON response"
        )
        return set()
    return {
        str(scope.get("handle") or "").strip()
        for scope in data.get("access_scopes", [])
        if isinstance(scope, dict) and str(scope.get("handle") or "").strip()
    }


def _split_scopes(scope_text):
    return {part.strip() for part in re.split(r"[\s,]+", str(scope_text or "")) if part.strip()}


def _django_shell_script() -> str:
    template = r'''
import json
import re

shop = __SHOP_LITERAL__
required_scopes = __REQUIRED_SCOPES_LITERAL__

email_re = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
secret_re = re.compile(
    r"(?i)(shpat_[A-Za-z0-9_]+|ya29\.[A-Za-z0-9._-]+|bearer\s+[A-Za-z0-9._-]{8,}|"
    r"x-shopify-access-token|authorization|access[_\s-]?token|refresh[_\s-]?token|"
    r"client[_\s-]?secret|api[_\s-]?key|password|secret)"
)

result = {
    "success": False,
    "scope_verification_status": "scope_check_not_started",
    "shopify_api_call_performed": False,
    "read_orders_present": False,
    "read_all_orders_present": False,
    "token_scope_source": "unavailable",
    "configured_scope_source": "unavailable",
    "configured_read_orders_present": False,
    "configured_read_all_orders_present": False,
    "reauthorization_required": True,
    "next_admin_action": "Verify Shopify installation and reauthorize the app if the active token is old.",
    "shopify_installation_found": False,
    "shopify_credentials_found": False,
    "scope_check_helper_available": False,
    "manual_verification_command": "",
    "failure_type": "",
    "error_sanitized": "",
    "shopify_http_status": None,
    "shopify_api_response_error_count": 0,
    "shopify_api_response_errors_sanitized": [],
    "privacy_scan_summary": {},
}

def sanitize(text):
    text = str(text or "")
    text = secret_re.sub("[redacted]", text)
    return email_re.sub("[masked-email]", text)[:600]

def split_scopes(scope_text):
    return {part.strip() for part in re.split(r"[\s,]+", str(scope_text or "")) if part.strip()}

def finish():
    print("__JSON_BEGIN__")
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    print("__JSON_END__")

try:
    from shopify_sync.models import ShopifyInstallation
except Exception as exc:
    result["scope_verification_status"] = "shopify_installation_model_unavailable"
    result["failure_type"] = "shopify_installation_model_unavailable"
    result["error_sanitized"] = sanitize(exc)
    finish()
    raise SystemExit(0)

try:
    from shopify_sync.sync_helpers import shopify_get
    result["scope_check_helper_available"] = True
except Exception as exc:
    result["scope_verification_status"] = "scope_check_helper_missing"
    result["failure_type"] = "scope_check_helper_missing"
    result["error_sanitized"] = sanitize(exc)
    result["manual_verification_command"] = (
        "Add or repair backend/shopify_sync/sync_helpers.py shopify_get support, then call "
        "GET https://{shop}/admin/oauth/access_scopes.json with X-Shopify-Access-Token. "
        "Do not print the token."
    )
    finish()
    raise SystemExit(0)

try:
    installation = ShopifyInstallation.objects.filter(shop=shop).first() or ShopifyInstallation.objects.first()
    if not installation:
        result["scope_verification_status"] = "shopify_installation_missing"
        result["failure_type"] = "shopify_installation_missing"
        result["next_admin_action"] = "Install or reauthorize the Shopify app so a local installation record exists."
        finish()
        raise SystemExit(0)

    result["shopify_installation_found"] = True
    configured_scopes = split_scopes(getattr(installation, "scope", "") or "")
    result["configured_scope_source"] = "ShopifyInstallation.scope"
    result["configured_read_orders_present"] = "read_orders" in configured_scopes
    result["configured_read_all_orders_present"] = "read_all_orders" in configured_scopes

    access_token = getattr(installation, "access_" + "token")
    result["shopify_credentials_found"] = bool(access_token)
    if not access_token:
        result["scope_verification_status"] = "missing_shopify_access_token"
        result["failure_type"] = "missing_shopify_access_token"
        result["next_admin_action"] = "Reauthorize the Shopify app and save the new access token before sending."
        finish()
        raise SystemExit(0)

    scopes_url = "https://" + installation.shop + "/admin/oauth/access_scopes.json"
    try:
        result["shopify_api_call_performed"] = True
        response = shopify_get(
            scopes_url,
            access_token,
            timeout=20,
            max_retries=2,
            request_context="shopify_review_request_access_scope_verification",
            stop_on_429=False,
        )
        result["shopify_http_status"] = response.status_code
        data = response.json()
    except Exception as exc:
        result["scope_verification_status"] = "access_scope_endpoint_unavailable"
        result["failure_type"] = "access_scope_endpoint_unavailable"
        result["shopify_api_response_error_count"] = 1
        result["shopify_api_response_errors_sanitized"].append(sanitize(exc))
        result["next_admin_action"] = (
            "Run the scope verification again after confirming network access; if it still fails, "
            "manually verify /admin/oauth/access_scopes.json without printing the token."
        )
        result["manual_verification_command"] = (
            "python remote_approval_runner.py --task shopify_review_request_shopify_scope_verification "
            "--mode dry-run --approval local"
        )
        finish()
        raise SystemExit(0)

    handles = {
        str(scope.get("handle") or "").strip()
        for scope in data.get("access_scopes", [])
        if isinstance(scope, dict) and str(scope.get("handle") or "").strip()
    }
    result["token_scope_source"] = "shopify_access_scopes_endpoint"
    result["read_orders_present"] = "read_orders" in handles
    result["read_all_orders_present"] = "read_all_orders" in handles
    result["reauthorization_required"] = not all(scope in handles for scope in required_scopes)
    if result["read_orders_present"] and result["read_all_orders_present"]:
        result["scope_verification_status"] = "active_token_scope_verified"
        result["success"] = True
        result["next_admin_action"] = "No reauthorization needed for Review Request customer history reads."
    elif result["read_orders_present"]:
        result["scope_verification_status"] = "read_all_orders_missing_reauthorization_required"
        result["next_admin_action"] = "Reauthorize or reinstall the Shopify app, then save the new access token before sending."
    else:
        result["scope_verification_status"] = "read_orders_scope_missing_reauthorization_required"
        result["next_admin_action"] = "Reauthorize or reinstall the Shopify app with read_orders and read_all_orders before sending."
    finish()
    raise SystemExit(0)
except Exception as exc:
    result["scope_verification_status"] = "scope_verification_exception"
    result["failure_type"] = "scope_verification_exception"
    result["error_sanitized"] = sanitize(exc)
    finish()
    raise SystemExit(0)
'''
    return (
        template.replace("__SHOP_LITERAL__", json.dumps(SHOP_DOMAIN))
        .replace("__REQUIRED_SCOPES_LITERAL__", json.dumps(list(REQUIRED_SCOPES)))
        .replace("__JSON_BEGIN__", JSON_BEGIN)
        .replace("__JSON_END__", JSON_END)
    )


def _build_payload(verification: dict, duration_seconds: float) -> dict:
    status = _safe_text(verification.get("scope_verification_status") or "scope_check_not_available", 120)
    read_orders_present = verification.get("read_orders_present") is True
    read_all_orders_present = verification.get("read_all_orders_present") is True
    reauthorization_required = verification.get("reauthorization_required") is True
    next_admin_action = _safe_text(verification.get("next_admin_action"), 400)
    if not next_admin_action:
        next_admin_action = (
            "No reauthorization needed for Review Request customer history reads."
            if read_orders_present and read_all_orders_present
            else REAUTHORIZE_MESSAGE
        )
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.31D",
        "mode": "dry-run-read-only-shopify-scope-verification",
        "command_label": COMMAND_LABEL,
        "scope_verification_status": status,
        "success": bool(read_orders_present and read_all_orders_present and not reauthorization_required),
        "shopify_api_call_performed": verification.get("shopify_api_call_performed") is True,
        "read_orders_present": read_orders_present,
        "read_all_orders_present": read_all_orders_present,
        "token_scope_source": _safe_text(verification.get("token_scope_source"), 120) or "unavailable",
        "configured_scope_source": _safe_text(verification.get("configured_scope_source"), 120) or "unavailable",
        "configured_read_orders_present": verification.get("configured_read_orders_present") is True,
        "configured_read_all_orders_present": verification.get("configured_read_all_orders_present") is True,
        "reauthorization_required": reauthorization_required,
        "next_admin_action": next_admin_action,
        "shop_domain": SHOP_DOMAIN,
        "shopify_installation_found": verification.get("shopify_installation_found") is True,
        "shopify_credentials_found": verification.get("shopify_credentials_found") is True,
        "scope_check_helper_available": verification.get("scope_check_helper_available") is True,
        "manual_verification_command": _safe_text(verification.get("manual_verification_command"), 600),
        "shopify_http_status": verification.get("shopify_http_status"),
        "shopify_api_response_error_count": _int_or_zero(verification.get("shopify_api_response_error_count")),
        "shopify_api_response_errors_sanitized": [
            _safe_text(item, 300) for item in (verification.get("shopify_api_response_errors_sanitized") or [])[:10]
        ],
        "failure_type": _safe_text(verification.get("failure_type"), 120),
        "error_sanitized": _safe_text(verification.get("error_sanitized"), 600),
        "stdout_tail": _safe_text(verification.get("stdout_tail"), 800),
        "stderr_tail": _safe_text(verification.get("stderr_tail"), 800),
        "report_json_path": str(REPORT_JSON_PATH),
        "report_html_path": str(REPORT_HTML_PATH),
        "json_shopify_scope_verification_path": str(REPORT_JSON_PATH),
        "html_shopify_scope_verification_path": str(REPORT_HTML_PATH),
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "translations_register_called": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "no_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "raw_email_output": False,
        "full_note_output": False,
        "privacy_assertion_passed": True,
        "privacy_scan_summary": {},
        "detected_issue_summary": _issue_summary(status, read_orders_present, read_all_orders_present, reauthorization_required),
        "duration_seconds": duration_seconds,
    }
    return payload


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_shopify_scope_verification_path": str(json_path),
        "html_shopify_scope_verification_path": str(html_path),
        "scope_verification_status": payload["scope_verification_status"],
        "shopify_api_call_performed": payload["shopify_api_call_performed"],
        "read_orders_present": payload["read_orders_present"],
        "read_all_orders_present": payload["read_all_orders_present"],
        "token_scope_source": payload["token_scope_source"],
        "reauthorization_required": payload["reauthorization_required"],
        "next_admin_action": payload["next_admin_action"],
        "privacy_scan_summary": payload["privacy_scan_summary"],
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "raw_email_output": False,
        "full_note_output": False,
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
    rows = "\n".join(
        f"<tr><th>{escape(key)}</th><td>{escape(str(payload.get(key)))}</td></tr>"
        for key in (
            "scope_verification_status",
            "shopify_api_call_performed",
            "read_orders_present",
            "read_all_orders_present",
            "token_scope_source",
            "reauthorization_required",
            "next_admin_action",
            "privacy_scan_summary",
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Scope Verification</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; width: 280px; }}
    .warning {{ border-left: 4px solid #c2410c; background: #fff7ed; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Shopify Scope Verification</h1>
  <p class="warning">Read-only scope check. No Shopify write, no tag mutation, no Gmail API/send, no external review API call, and no token output.</p>
  <table><tbody>{rows}</tbody></table>
</body>
</html>"""


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 5.31D scope verification finished.\n"
        f"Scope verification status: {payload.get('scope_verification_status')}\n"
        f"Shopify scope API call performed: {payload.get('shopify_api_call_performed')}\n"
        f"read_orders present: {payload.get('read_orders_present')}\n"
        f"read_all_orders present: {payload.get('read_all_orders_present')}\n"
        f"Token scope source: {payload.get('token_scope_source')}\n"
        f"Reauthorization required: {payload.get('reauthorization_required')}\n"
        f"Next admin action: {payload.get('next_admin_action')}\n"
        f"Privacy scan summary: {payload.get('privacy_scan_summary')}\n"
        "Safety: no Shopify write, no tag mutation, no Gmail API/send, no token output.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _extract_payload(stdout: str) -> dict:
    if JSON_BEGIN not in stdout or JSON_END not in stdout:
        return {}
    fragment = stdout.split(JSON_BEGIN, 1)[1].split(JSON_END, 1)[0].strip()
    try:
        data = json.loads(fragment)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _empty_verification() -> dict:
    return {
        "success": False,
        "scope_verification_status": "scope_check_not_available",
        "shopify_api_call_performed": False,
        "read_orders_present": False,
        "read_all_orders_present": False,
        "token_scope_source": "unavailable",
        "reauthorization_required": True,
        "next_admin_action": REAUTHORIZE_MESSAGE,
        "privacy_scan_summary": {},
    }


def _apply_self_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_emails = sorted(set(EMAIL_RE.findall(text)))
    secret_hits = SECRET_VALUE_RE.findall(text)
    payload["privacy_scan_summary"] = {
        "raw_customer_email_count": len(raw_emails),
        "token_secret_pattern_count": len(secret_hits),
        "raw_email_output": False,
        "token_output": False,
    }
    if raw_emails or secret_hits:
        payload["scope_verification_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["reauthorization_required"] = True
        payload["next_admin_action"] = "Privacy scan failed; review report generation before rerunning."
        payload["privacy_assertion_passed"] = False
    return payload


def _issue_summary(status: str, read_orders_present: bool, read_all_orders_present: bool, reauthorization_required: bool) -> str:
    return (
        f"Shopify scope verification status={status}; "
        f"read_orders present={read_orders_present}; "
        f"read_all_orders present={read_all_orders_present}; "
        f"reauthorization required={reauthorization_required}. "
        "No Shopify write, tag mutation, Gmail API/send, external review API call, token output, raw email output, or full note output."
    )


def _decode_bytes(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return value.decode("utf-8", errors="replace")


def _tail(text: str, max_chars: int = 1000) -> str:
    return _sanitize_text((text or "")[-max_chars:])


def _safe_text(value, max_length: int = 300) -> str:
    return _sanitize_text(str(value or ""), max_length=max_length)


def _sanitize_text(text: str, max_length: int = 300) -> str:
    redacted = SECRET_VALUE_RE.sub("[redacted]", str(text or ""))
    redacted = EMAIL_RE.sub("[masked-email]", redacted)
    return redacted[:max_length]


def _int_or_zero(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
