import json
import os
import re
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_post_send_tag_write"
COMMAND_LABEL = "shopify_review_request_trustpilot_post_send_tag_write"

SOURCE_POST_SEND_AUDIT_JSON_PATH = (
    LOG_DIR / "codex_runs" / "shopify_review_request_review_send_post_send_audit.json"
)
SOURCE_POST_SEND_AUDIT_LOGICAL_PATH = "logs/codex_runs/shopify_review_request_review_send_post_send_audit.json"
SOURCE_REVIEW_SEND_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_review_and_send_execute.json"
SOURCE_REVIEW_SEND_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_review_and_send_execute.html"
SOURCE_REVIEW_SEND_LOGICAL_PATH = "logs/shopify_review_request_trustpilot_review_and_send_execute.json"
SOURCE_REVIEW_SEND_HTML_LOGICAL_PATH = "logs/shopify_review_request_trustpilot_review_and_send_execute.html"
REPORT_JSON_PATH = LOG_DIR / "codex_runs" / "shopify_review_request_trustpilot_post_send_tag_write.json"
REPORT_HTML_PATH = LOG_DIR / "codex_runs" / "shopify_review_request_trustpilot_post_send_tag_write.html"

EXPECTED_POST_SEND_AUDIT_STATUS = "review_send_post_send_audit_passed"
APPROVAL_ENV = "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_WRITE"
APPROVAL_VALUE = "YES_I_APPROVE_TRUSTPILOT_TAG_WRITE_FOR_SENT_ORDER"
CANONICAL_TRUSTPILOT_TAG = "1: trustpilot"
REVIEW_REQUEST_REMOVE_ALIASES = [
    "1: review request",
    "1: reveiw request",
    "1:review request",
    "1:reveiw request",
    "1 : review request",
    "1 : reveiw request",
]
SUCCESS_STATUS = "trustpilot_tag_written_and_review_request_removed"
REVIEW_REQUEST_ALIAS_STILL_PRESENT_STATUS = "blocked_review_request_tag_still_present"
MISSING_APPROVAL_STATUS = "blocked_missing_tag_write_approval"
INVALID_APPROVAL_STATUS = "blocked_invalid_tag_write_approval"
EBAY_BLOCK_REASON = "eBay order 鈥?Trustpilot email not allowed."

SHOP_DOMAIN = "kidstoylover.myshopify.com"
SHOPIFY_API_VERSION = "2026-01"
SHOPIFY_TAG_WRITE_TIMEOUT_SECONDS = 150

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_RE = re.compile(
    r"(?i)("
    r"bearer\s+[A-Za-z0-9._-]{8,}|"
    r"ya29\.[A-Za-z0-9._-]+|"
    r"shpat_[A-Za-z0-9_]+|"
    r"x-shopify-access-token\s*[:=]\s*[A-Za-z0-9._-]+|"
    r"access[_\s-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"refresh[_\s-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"client[_\s-]?secret\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"api[_\s-]?key\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"password\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{8,}|"
    r"secret\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{8,}"
    r")"
)


def run_shopify_review_request_trustpilot_post_send_tag_write_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_report, source_error, source_diagnostics = _read_source_post_send_audit()
    source_blockers = _source_blocking_conditions(source_report, source_error)
    approval = _approval_gate()
    write_result = _write_result(source_report, source_blockers, approval)
    blocking_conditions = [*source_blockers, *write_result.get("blocking_conditions", [])]
    status = write_result["tag_write_status"]

    payload = _build_payload(
        source_report=source_report,
        source_error=source_error,
        source_diagnostics=source_diagnostics,
        approval=approval,
        source_blockers=source_blockers,
        blocking_conditions=blocking_conditions,
        write_result=write_result,
        status=status,
        duration_seconds=round(time.time() - started, 3),
    )
    payload["privacy_scan_summary"] = _privacy_scan(payload)
    if not payload["privacy_scan_summary"]["passed"]:
        payload["tag_write_status"] = "blocked_privacy_scan_failed"
        payload["report_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["shopify_api_call_performed"] = False
        payload["shopify_write_performed"] = False
        payload["shopify_tag_write_performed"] = False
        payload["mutation_performed"] = False
        payload["tags_add_performed"] = False
        payload["tags_remove_performed"] = False
        payload["blocking_conditions"].append(
            {
                "status": "blocked_privacy_scan_failed",
                "detail": "Privacy scan found raw email or secret-like output.",
            }
        )

    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_source_post_send_audit() -> tuple[dict, str, dict]:
    diagnostics = _source_diagnostics()
    candidates = []

    host_candidate = _load_host_post_send_audit_source(diagnostics)
    if host_candidate:
        candidates.append(host_candidate)

    if not _has_ready_source(candidates):
        django_candidate = _load_django_post_send_audit_source(diagnostics)
        if django_candidate:
            candidates.append(django_candidate)

    if not _has_ready_source(candidates):
        candidates.extend(_load_history_ledger_sources(diagnostics))

    selected = _select_source_candidate(candidates)
    diagnostics["source_candidates"] = [_source_candidate_summary(candidate) for candidate in candidates]
    diagnostics["selected_source"] = _safe_text((selected or {}).get("source_name"), max_length=120)
    diagnostics["selected_source_path"] = _safe_text((selected or {}).get("source_path"), max_length=180)
    diagnostics["source_selection_why_not_ready"] = (selected or {}).get("blocking_statuses") or []

    if selected and selected.get("payload"):
        return selected["payload"], selected.get("error", ""), diagnostics
    return {}, "blocked_missing_post_send_audit_report", diagnostics


def _source_diagnostics() -> dict:
    return {
        "source_paths_checked": [],
        "source_candidates": [],
        "host_report_found": False,
        "django_audit_source_found": False,
        "django_audit_error": "",
        "latest_review_send_report_found": False,
        "latest_post_send_audit_found": False,
        "history_ledger_error": "",
        "selected_source": "",
        "selected_source_path": "",
        "source_selection_why_not_ready": [],
    }


def _record_source_path(diagnostics: dict, value: str) -> None:
    text = _safe_text(value, max_length=180)
    if text and text not in diagnostics["source_paths_checked"]:
        diagnostics["source_paths_checked"].append(text)


def _load_host_post_send_audit_source(diagnostics: dict) -> dict:
    _record_source_path(diagnostics, SOURCE_POST_SEND_AUDIT_LOGICAL_PATH)
    if not SOURCE_POST_SEND_AUDIT_JSON_PATH.exists():
        return {}
    diagnostics["host_report_found"] = True
    diagnostics["latest_post_send_audit_found"] = True
    try:
        payload = json.loads(SOURCE_POST_SEND_AUDIT_JSON_PATH.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _source_candidate(
            source_name="host_post_send_audit_report",
            payload={},
            error=_sanitize_text(f"blocked_post_send_audit_unreadable: {exc}"),
            source_path=SOURCE_POST_SEND_AUDIT_LOGICAL_PATH,
        )
    if not isinstance(payload, dict):
        return _source_candidate(
            source_name="host_post_send_audit_report",
            payload={},
            error="blocked_post_send_audit_not_object",
            source_path=SOURCE_POST_SEND_AUDIT_LOGICAL_PATH,
        )
    return _source_candidate(
        source_name="host_post_send_audit_report",
        payload=payload,
        error="",
        source_path=SOURCE_POST_SEND_AUDIT_LOGICAL_PATH,
    )


def _load_django_post_send_audit_source(diagnostics: dict) -> dict:
    _record_source_path(
        diagnostics,
        "django_web_container:build_review_request_review_send_post_send_audit_report",
    )
    try:
        from remote_approval.tasks.shopify_review_request_review_send_post_send_audit_task import (
            load_review_send_post_send_audit_payload_from_django,
        )
    except ImportError as exc:
        return _source_candidate(
            source_name="django_web_container_post_send_audit_builder",
            payload={},
            error=_sanitize_text(f"django_audit_import_failed: {exc}"),
            source_path="django_web_container:build_review_request_review_send_post_send_audit_report",
        )

    result = load_review_send_post_send_audit_payload_from_django()
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    if payload:
        diagnostics["django_audit_source_found"] = True
        if payload.get("source_review_send_report_found") is True:
            diagnostics["latest_review_send_report_found"] = True
        source_path = _safe_text(payload.get("source_review_send_json_path"), max_length=180)
        if source_path:
            _record_source_path(diagnostics, source_path)
        return _source_candidate(
            source_name="django_web_container_post_send_audit_builder",
            payload=payload,
            error="",
            source_path=source_path or "django_web_container:post_send_audit_payload",
        )
    error = _safe_text(
        " | ".join(
            _dedupe_text(
                [
                    result.get("failure_type"),
                    result.get("error"),
                ]
            )
        ),
        max_length=300,
    ) or "django_post_send_audit_unavailable"
    diagnostics["django_audit_error"] = error
    return _source_candidate(
        source_name="django_web_container_post_send_audit_builder",
        payload={},
        error=error,
        source_path="django_web_container:build_review_request_review_send_post_send_audit_report",
    )


def _load_history_ledger_sources(diagnostics: dict) -> list[dict]:
    _record_source_path(diagnostics, "history_ledger:load_history_source_reports")
    try:
        from backend.shopify_sync.review_request_history_ledger import load_history_source_reports
        from remote_approval.tasks.shopify_review_request_review_send_post_send_audit_task import (
            build_review_send_post_send_audit_payload_from_source_report,
        )
    except ImportError as exc:
        diagnostics["history_ledger_error"] = _sanitize_text(f"history_ledger_import_failed: {exc}")
        return [
            _source_candidate(
                source_name="history_ledger_local_report_loader",
                payload={},
                error=_sanitize_text(f"history_ledger_import_failed: {exc}"),
                source_path="history_ledger:load_history_source_reports",
            )
        ]

    try:
        reports = load_history_source_reports(LOG_DIR)
    except Exception as exc:
        diagnostics["history_ledger_error"] = _sanitize_text(f"history_ledger_load_failed: {exc}")
        return [
            _source_candidate(
                source_name="history_ledger_local_report_loader",
                payload={},
                error=_sanitize_text(f"history_ledger_load_failed: {exc}"),
                source_path="history_ledger:load_history_source_reports",
            )
        ]

    candidates = []
    for report in reports:
        key = report.get("key")
        if key not in {"review_send_post_send_audit", "trustpilot_review_and_send_execute"}:
            continue
        relative_path = _safe_text(report.get("relative_path"), max_length=180)
        if relative_path:
            _record_source_path(diagnostics, relative_path)
        if key == "review_send_post_send_audit" and report.get("loaded"):
            diagnostics["latest_post_send_audit_found"] = True
            candidates.append(
                _source_candidate(
                    source_name="history_ledger_post_send_audit_report",
                    payload=report.get("data") or {},
                    error="",
                    source_path=relative_path or SOURCE_POST_SEND_AUDIT_LOGICAL_PATH,
                )
            )
        elif key == "trustpilot_review_and_send_execute" and report.get("loaded"):
            diagnostics["latest_review_send_report_found"] = True
            payload = build_review_send_post_send_audit_payload_from_source_report(
                report.get("data") or {},
                source_error="",
                source_html="",
                source_json_path=relative_path or SOURCE_REVIEW_SEND_LOGICAL_PATH,
                source_html_path=SOURCE_REVIEW_SEND_HTML_LOGICAL_PATH,
                source_html_found=SOURCE_REVIEW_SEND_HTML_PATH.exists(),
            )
            candidates.append(
                _source_candidate(
                    source_name="history_ledger_latest_review_send_report",
                    payload=payload,
                    error="",
                    source_path=relative_path or SOURCE_REVIEW_SEND_LOGICAL_PATH,
                )
            )
    return candidates


def _source_candidate(source_name: str, payload: dict, error: str, source_path: str) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    error = _sanitize_text(error)
    blockers = _source_blocking_conditions(payload, error) if payload or error else []
    return {
        "source_name": _safe_text(source_name, max_length=120),
        "source_path": _safe_text(source_path, max_length=180),
        "payload": payload,
        "error": error,
        "found": bool(payload),
        "ready": bool(payload) and not blockers,
        "blocking_statuses": _dedupe_text(item.get("status") for item in blockers),
        "audit_status": _safe_text(payload.get("audit_status") or payload.get("report_status"), max_length=120),
        "selected_order": _canonical_order_name(payload.get("selected_order")),
        "email_sent_confirmed": payload.get("email_sent_confirmed") is True,
        "sent_count": _safe_int(payload.get("sent_count")),
    }


def _source_candidate_summary(candidate: dict) -> dict:
    return {
        "source_name": _safe_text(candidate.get("source_name"), max_length=120),
        "source_path": _safe_text(candidate.get("source_path"), max_length=180),
        "found": candidate.get("found") is True,
        "ready": candidate.get("ready") is True,
        "audit_status": _safe_text(candidate.get("audit_status"), max_length=120),
        "selected_order": _canonical_order_name(candidate.get("selected_order")),
        "email_sent_confirmed": candidate.get("email_sent_confirmed") is True,
        "sent_count": _safe_int(candidate.get("sent_count")),
        "blocking_statuses": [_safe_text(item, max_length=120) for item in candidate.get("blocking_statuses") or []],
        "error": _safe_text(candidate.get("error"), max_length=180),
    }


def _has_ready_source(candidates: list[dict]) -> bool:
    return any(candidate.get("ready") is True for candidate in candidates)


def _select_source_candidate(candidates: list[dict]) -> dict:
    for candidate in candidates:
        if candidate.get("ready") is True:
            return candidate
    for candidate in candidates:
        if candidate.get("found") is True:
            return candidate
    for candidate in candidates:
        if candidate.get("error"):
            return candidate
    return {}


def _source_blocking_conditions(source_report: dict, source_error: str) -> list[dict]:
    conditions = []
    if source_error:
        return [{"status": source_error, "detail": "Post-send audit report was not available."}]

    selected_order = _canonical_order_name(source_report.get("selected_order"))
    audit_status = _safe_text(source_report.get("audit_status") or source_report.get("report_status"))
    sent_count = _safe_int(source_report.get("sent_count"))
    pending_count = _pending_tag_write_count(source_report)
    if not selected_order:
        conditions.append(
            {
                "status": "blocked_missing_selected_order",
                "detail": "The source post-send audit must include one selected order.",
            }
        )
    if audit_status != EXPECTED_POST_SEND_AUDIT_STATUS or source_report.get("success") is not True:
        conditions.append(
            {
                "status": "blocked_post_send_audit_not_passed",
                "detail": "The source post-send audit must have passed before Shopify tag write.",
            }
        )
    if source_report.get("email_sent_confirmed") is not True:
        conditions.append(
            {
                "status": "blocked_email_not_confirmed",
                "detail": "Post-send audit must confirm email_sent_confirmed=true.",
            }
        )
    if sent_count != 1:
        conditions.append({"status": "blocked_unexpected_sent_count", "detail": "sent_count must equal 1."})
    if source_report.get("ready_for_shopify_tag_write_next_phase") is not True:
        conditions.append(
            {
                "status": "blocked_not_ready_for_shopify_tag_write",
                "detail": "Post-send audit did not mark the order ready for the tag-write phase.",
            }
        )
    if source_report.get("shopify_tag_write_confirmed_false") is not True:
        conditions.append(
            {
                "status": "blocked_source_tag_write_already_confirmed",
                "detail": "Post-send audit does not confirm that Shopify tag write is still pending.",
            }
        )
    if source_report.get("shopify_write_confirmed_false") is not True:
        conditions.append(
            {
                "status": "blocked_source_shopify_write_not_false",
                "detail": "Post-send audit must confirm no Shopify write happened during email send.",
            }
        )
    if source_report.get("ebay_tag_detected") is True:
        conditions.append({"status": "blocked_ebay_order", "detail": EBAY_BLOCK_REASON})
    if pending_count > 1:
        conditions.append(
            {
                "status": "blocked_multiple_pending_tag_write_orders",
                "detail": "This phase supports exactly one post-send audited order.",
            }
        )
    return conditions


def _pending_tag_write_count(source_report: dict) -> int:
    for key in ("pending_tag_write_orders", "sent_orders_pending_tag_write", "already_sent_rows"):
        rows = source_report.get(key)
        if not isinstance(rows, list):
            continue
        pending = [
            row
            for row in rows
            if isinstance(row, dict)
            and (
                row.get("shopify_tag_pending") is True
                or row.get("tag_write_pending") is True
                or row.get("shopify_tag_status_label") == "Tag pending"
            )
        ]
        if pending:
            return len({_canonical_order_name(row.get("order") or row.get("order_name")) for row in pending})
    return 1 if source_report.get("ready_for_shopify_tag_write_next_phase") is True else 0


def _approval_gate() -> dict:
    raw_value = os.environ.get(APPROVAL_ENV, "").strip()
    return {
        "approval_env_name": APPROVAL_ENV,
        "approval_env_present": bool(raw_value),
        "approval_env_valid": raw_value == APPROVAL_VALUE,
        "approval_value_expected_label": APPROVAL_VALUE,
    }


def _write_result(source_report: dict, source_blockers: list[dict], approval: dict) -> dict:
    base = {
        "tag_write_status": "",
        "mode": "dry-run-approval-missing",
        "blocking_conditions": [],
        "tag_write_ready": not source_blockers,
        "selected_order": _canonical_order_name(source_report.get("selected_order")),
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "readback_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "translations_register_called": False,
        "tag_write_already_complete": False,
        "tag_write_attempted": False,
        "tag_write_performed": False,
        "written_tag_count": 0,
        "removed_tag_count": 0,
        "tag_count_before": 0,
        "tag_count_after": 0,
        "tags_before": [],
        "tags_to_write": [],
        "tags_after_readback": [],
        "matched_review_request_tags_to_remove": [],
        "removed_tag_values": [],
        "trustpilot_tag_present_before": False,
        "trustpilot_tag_present_after": False,
        "review_request_tag_present_after": False,
        "typo_review_request_tag_present_after": False,
        "all_review_request_aliases_removed": False,
        "local_shopify_tags_updated": False,
        "local_tags_after_update": [],
        "local_shopify_tags_update_error_sanitized": "",
        "ebay_tag_detected_from_shopify": False,
        "matched_ebay_tag_value": "",
        "shopify_order_name_confirmed": "",
        "shopify_tag_write_error_sanitized": "",
    }
    if not approval["approval_env_present"]:
        base["tag_write_status"] = MISSING_APPROVAL_STATUS
        base["blocking_conditions"].append(
            {
                "status": MISSING_APPROVAL_STATUS,
                "detail": f"{APPROVAL_ENV} must equal the exact approval phrase before any Shopify API call.",
            }
        )
        return base
    if not approval["approval_env_valid"]:
        base["tag_write_status"] = INVALID_APPROVAL_STATUS
        base["blocking_conditions"].append(
            {"status": INVALID_APPROVAL_STATUS, "detail": f"{APPROVAL_ENV} did not match the required phrase."}
        )
        return base
    if source_blockers:
        base["mode"] = "real-write-blocked-before-shopify"
        base["tag_write_status"] = source_blockers[0]["status"]
        return base

    base["mode"] = "real-run"
    mutation_result = _execute_shopify_tag_write(base["selected_order"], source_report)
    base.update(mutation_result)
    if base.get("tag_write_status") != SUCCESS_STATUS:
        base["blocking_conditions"].append(
            {
                "status": base.get("tag_write_status") or "blocked_shopify_tag_write_failed",
                "detail": base.get("shopify_tag_write_error_sanitized") or "Shopify tag write did not complete.",
            }
        )
    return base


def _execute_shopify_tag_write(order_name: str, source_report: dict) -> dict:
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
            _shopify_tag_write_script(order_name, source_report),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=SHOPIFY_TAG_WRITE_TIMEOUT_SECONDS,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "tag_write_status": "blocked_shopify_tag_write_failed",
            "shopify_tag_write_error_sanitized": f"Shopify tag write timed out after {SHOPIFY_TAG_WRITE_TIMEOUT_SECONDS} seconds.",
        }
    except (FileNotFoundError, PermissionError) as exc:
        return {
            "tag_write_status": "blocked_shopify_tag_write_failed",
            "shopify_tag_write_error_sanitized": _sanitize_text(str(exc)),
        }

    parsed = _parse_json_from_stdout(completed.stdout)
    if not parsed:
        return {
            "tag_write_status": "blocked_shopify_tag_write_failed",
            "shopify_tag_write_error_sanitized": _sanitize_text(
                completed.stderr or completed.stdout or "Shopify tag write did not return parseable JSON."
            ),
        }
    if completed.returncode != 0 and not parsed.get("shopify_tag_write_error_sanitized"):
        parsed["shopify_tag_write_error_sanitized"] = _sanitize_text(
            completed.stderr or "Shopify tag write command failed."
        )
    return parsed


def _shopify_tag_write_script(order_name: str, source_report: dict) -> str:
    audit_json = json.dumps(source_report if isinstance(source_report, dict) else {}, ensure_ascii=True)
    template = r'''
import json

from shopify_sync.review_request_workbench import execute_trustpilot_post_send_tag_write

selected_order = __ORDER_NAME_LITERAL__
audit_data = json.loads(__AUDIT_DATA_JSON_LITERAL__)
result = execute_trustpilot_post_send_tag_write(
    selected_order=selected_order,
    verified_post_send_audit_data=audit_data,
    approval_source="manual_runner",
    allow_auto_after_send=False,
)
print(json.dumps(result, ensure_ascii=True, sort_keys=True))
raise SystemExit(0 if result.get("tag_write_status") == "trustpilot_tag_written_and_review_request_removed" else 1)
'''
    return (
        template.replace("__ORDER_NAME_LITERAL__", json.dumps(order_name))
        .replace("__AUDIT_DATA_JSON_LITERAL__", json.dumps(audit_json))
    )


def _parse_json_from_stdout(stdout: str) -> dict:
    for line in reversed((stdout or "").splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{") or not stripped.endswith("}"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        return payload if isinstance(payload, dict) else {}
    return {}


def _build_payload(
    source_report: dict,
    source_error: str,
    source_diagnostics: dict,
    approval: dict,
    source_blockers: list[dict],
    blocking_conditions: list[dict],
    write_result: dict,
    status: str,
    duration_seconds: float,
) -> dict:
    selected_order = _canonical_order_name(source_report.get("selected_order"))
    safety = _safety_summary(write_result)
    source_diagnostics = source_diagnostics or {}
    why_not_ready = _why_not_ready(blocking_conditions, source_diagnostics)
    payload = {
        "timestamp": utc_now_iso(),
        "report_generated_at": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.29C",
        "mode": write_result.get("mode", "dry-run-approval-missing"),
        "command_label": COMMAND_LABEL,
        "tag_write_status": status,
        "report_status": status,
        "success": status in {SUCCESS_STATUS, MISSING_APPROVAL_STATUS},
        "source_post_send_audit_json_path": SOURCE_POST_SEND_AUDIT_LOGICAL_PATH,
        "source_post_send_audit_found": bool(source_report),
        "source_post_send_audit_error": _sanitize_text(source_error),
        "source_paths_checked": source_diagnostics.get("source_paths_checked") or [],
        "host_report_found": source_diagnostics.get("host_report_found") is True,
        "django_audit_source_found": source_diagnostics.get("django_audit_source_found") is True,
        "django_audit_error": _safe_text(source_diagnostics.get("django_audit_error"), max_length=300),
        "latest_review_send_report_found": source_diagnostics.get("latest_review_send_report_found") is True,
        "latest_post_send_audit_found": source_diagnostics.get("latest_post_send_audit_found") is True,
        "history_ledger_error": _safe_text(source_diagnostics.get("history_ledger_error"), max_length=300),
        "selected_source": _safe_text(source_diagnostics.get("selected_source"), max_length=120),
        "selected_source_path": _safe_text(source_diagnostics.get("selected_source_path"), max_length=180),
        "source_candidate_summaries": source_diagnostics.get("source_candidates") or [],
        "why_not_ready": why_not_ready,
        "source_audit_status": _safe_text(source_report.get("audit_status") or source_report.get("report_status")),
        "selected_order": selected_order,
        "expected_order": selected_order,
        "target_order_locked": bool(selected_order),
        "email_sent_confirmed": source_report.get("email_sent_confirmed") is True,
        "sent_count": _safe_int(source_report.get("sent_count")),
        "shopify_tag_write_confirmed_false": source_report.get("shopify_tag_write_confirmed_false") is True,
        "shopify_write_confirmed_false": source_report.get("shopify_write_confirmed_false") is True,
        "ready_for_shopify_tag_write_next_phase": source_report.get("ready_for_shopify_tag_write_next_phase") is True,
        "tag_write_ready": write_result.get("tag_write_ready") is True,
        "source_ebay_tag_detected": source_report.get("ebay_tag_detected") is True,
        "source_matched_ebay_tag_value": _safe_text(source_report.get("matched_ebay_tag_value"), max_length=120),
        "approval_env_name": APPROVAL_ENV,
        "approval_env_present": approval["approval_env_present"],
        "approval_env_valid": approval["approval_env_valid"],
        "approval_value_expected_label": APPROVAL_VALUE,
        "canonical_trustpilot_tag": CANONICAL_TRUSTPILOT_TAG,
        "review_request_remove_aliases": REVIEW_REQUEST_REMOVE_ALIASES,
        "source_blocking_conditions": source_blockers,
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "tag_write_already_complete": write_result.get("tag_write_already_complete") is True,
        "tag_write_attempted": write_result.get("tag_write_attempted") is True,
        "tag_write_performed": write_result.get("tag_write_performed") is True,
        "written_tag_count": _safe_int(write_result.get("written_tag_count")),
        "removed_tag_count": _safe_int(write_result.get("removed_tag_count")),
        "tag_count_before": _safe_int(write_result.get("tag_count_before")),
        "tag_count_after": _safe_int(write_result.get("tag_count_after")),
        "tags_before": [_safe_text(tag, max_length=120) for tag in (write_result.get("tags_before") or [])],
        "tags_to_write": [_safe_text(tag, max_length=120) for tag in (write_result.get("tags_to_write") or [])],
        "tags_after_readback": [
            _safe_text(tag, max_length=120) for tag in (write_result.get("tags_after_readback") or [])
        ],
        "matched_review_request_tags_to_remove": [
            _safe_text(tag, max_length=120)
            for tag in (write_result.get("matched_review_request_tags_to_remove") or [])
        ],
        "removed_tag_values": [
            _safe_text(tag, max_length=120) for tag in (write_result.get("removed_tag_values") or [])
        ],
        "trustpilot_tag_present_before": write_result.get("trustpilot_tag_present_before") is True,
        "trustpilot_tag_present_after": write_result.get("trustpilot_tag_present_after") is True,
        "trustpilot_tag_added": write_result.get("trustpilot_tag_added") is True,
        "review_request_tag_removed": write_result.get("review_request_tag_removed") is True,
        "typo_review_request_tag_removed": write_result.get("typo_review_request_tag_removed") is True,
        "all_review_request_aliases_removed": write_result.get("all_review_request_aliases_removed") is True,
        "readback_verified": write_result.get("readback_verified") is True,
        "tag_write_readback_verified": write_result.get("readback_verified") is True
        or write_result.get("tag_write_readback_verified") is True,
        "review_request_tag_present_after": write_result.get("review_request_tag_present_after") is True,
        "typo_review_request_tag_present_after": write_result.get("typo_review_request_tag_present_after") is True,
        "local_shopify_tags_updated": write_result.get("local_shopify_tags_updated") is True,
        "local_tags_after_update": [
            _safe_text(tag, max_length=120) for tag in (write_result.get("local_tags_after_update") or [])
        ],
        "local_shopify_tags_update_error_sanitized": _sanitize_text(
            write_result.get("local_shopify_tags_update_error_sanitized", "")
        ),
        "ebay_tag_detected_from_shopify": write_result.get("ebay_tag_detected_from_shopify") is True,
        "matched_ebay_tag_value": _safe_text(write_result.get("matched_ebay_tag_value"), max_length=120),
        "shopify_order_name_confirmed": _safe_text(write_result.get("shopify_order_name_confirmed"), max_length=80),
        "shopify_tag_write_error_sanitized": _sanitize_text(
            write_result.get("shopify_tag_write_error_sanitized", "")
        ),
        "shopify_tags_add_user_errors": write_result.get("shopify_tags_add_user_errors") or [],
        "shopify_tags_remove_user_errors": write_result.get("shopify_tags_remove_user_errors") or [],
        "safety_summary": safety,
        **safety,
        "json_path": str(REPORT_JSON_PATH),
        "html_path": str(REPORT_HTML_PATH),
        "json_trustpilot_post_send_tag_write_path": str(REPORT_JSON_PATH),
        "html_trustpilot_post_send_tag_write_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(status, selected_order, blocking_conditions, write_result),
        "duration_seconds": duration_seconds,
    }
    if status == SUCCESS_STATUS:
        payload["shopify_tag_write_confirmed"] = True
        payload["shopify_tag_status_label"] = "Tag written"
    return payload


def _why_not_ready(blocking_conditions: list[dict], source_diagnostics: dict) -> list[str]:
    reasons = _dedupe_text(
        item.get("status")
        for item in blocking_conditions or []
        if isinstance(item, dict) and item.get("status")
    )
    if reasons:
        return reasons
    return _dedupe_text(source_diagnostics.get("source_selection_why_not_ready") or [])


def _safety_summary(write_result: dict) -> dict:
    return {
        "shopify_api_call_performed": write_result.get("shopify_api_call_performed") is True,
        "shopify_write_performed": write_result.get("shopify_write_performed") is True,
        "shopify_tag_write_performed": write_result.get("shopify_tag_write_performed") is True,
        "mutation_performed": write_result.get("mutation_performed") is True,
        "tags_add_performed": write_result.get("tags_add_performed") is True,
        "tags_remove_performed": write_result.get("tags_remove_performed") is True,
        "tagsAdd_performed": write_result.get("tagsAdd_performed") is True,
        "tagsRemove_performed": write_result.get("tagsRemove_performed") is True,
        "readback_performed": write_result.get("readback_performed") is True,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "external_review_api_call_performed": False,
        "translations_register_called": False,
    }


def _write_json_report(payload: dict) -> Path:
    REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=True, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    REPORT_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    summary_rows = "\n".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in (
            ("Tag write status", payload.get("tag_write_status")),
            ("Selected order", payload.get("selected_order")),
            ("Source audit status", payload.get("source_audit_status")),
            ("Selected source", payload.get("selected_source")),
            ("Host report found", payload.get("host_report_found")),
            ("Django audit source found", payload.get("django_audit_source_found")),
            ("Django audit error", payload.get("django_audit_error")),
            ("Latest Review & Send report found", payload.get("latest_review_send_report_found")),
            ("Latest post-send audit found", payload.get("latest_post_send_audit_found")),
            ("History ledger error", payload.get("history_ledger_error")),
            ("Source paths checked", ", ".join(payload.get("source_paths_checked") or [])),
            ("Why not ready", ", ".join(payload.get("why_not_ready") or [])),
            ("Email sent confirmed", payload.get("email_sent_confirmed")),
            ("Sent count", payload.get("sent_count")),
            ("Tag write ready", payload.get("tag_write_ready")),
            ("Approval env present", payload.get("approval_env_present")),
            ("Approval env valid", payload.get("approval_env_valid")),
            ("Shopify API call performed", payload.get("shopify_api_call_performed")),
            ("Shopify write performed", payload.get("shopify_write_performed")),
            ("Gmail API call performed", payload.get("gmail_api_call_performed")),
            ("Trustpilot tag present after", payload.get("trustpilot_tag_present_after")),
            ("Review request tag present after", payload.get("review_request_tag_present_after")),
            ("Typo review request tag present after", payload.get("typo_review_request_tag_present_after")),
            ("All review request aliases removed", payload.get("all_review_request_aliases_removed")),
            ("Readback verified", payload.get("readback_verified")),
            ("Local ShopifyOrder tags updated", payload.get("local_shopify_tags_updated")),
            ("Tags before", ", ".join(payload.get("tags_before") or [])),
            ("Tags to write", ", ".join(payload.get("tags_to_write") or [])),
            ("Tags after readback", ", ".join(payload.get("tags_after_readback") or [])),
            ("Local tags after update", ", ".join(payload.get("local_tags_after_update") or [])),
        )
    )
    blocker_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(item.get('status', '')))}</td>"
        f"<td>{escape(str(item.get('detail', '')))}</td>"
        "</tr>"
        for item in payload.get("blocking_conditions") or []
    ) or '<tr><td colspan="2">None</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Post-Send Shopify Tag Write</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 24px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ width: 300px; background: #f0f4f8; }}
  </style>
</head>
<body>
  <h1>Trustpilot Post-Send Shopify Tag Write</h1>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocker_rows}</tbody></table>
</body>
</html>"""


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload.get("success") is True,
        "exit_code": 0 if payload.get("success") is True else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "html_review_path": str(html_path),
        "json_trustpilot_post_send_tag_write_path": str(json_path),
        "html_trustpilot_post_send_tag_write_path": str(html_path),
        "tag_write_status": payload.get("tag_write_status"),
        "source_audit_status": payload.get("source_audit_status"),
        "source_paths_checked": payload.get("source_paths_checked"),
        "host_report_found": payload.get("host_report_found"),
        "django_audit_source_found": payload.get("django_audit_source_found"),
        "django_audit_error": payload.get("django_audit_error"),
        "latest_review_send_report_found": payload.get("latest_review_send_report_found"),
        "latest_post_send_audit_found": payload.get("latest_post_send_audit_found"),
        "history_ledger_error": payload.get("history_ledger_error"),
        "selected_source": payload.get("selected_source"),
        "why_not_ready": payload.get("why_not_ready"),
        "selected_order": payload.get("selected_order"),
        "email_sent_confirmed": payload.get("email_sent_confirmed"),
        "sent_count": payload.get("sent_count"),
        "tag_write_ready": payload.get("tag_write_ready"),
        "approval_env_present": payload.get("approval_env_present"),
        "approval_env_valid": payload.get("approval_env_valid"),
        "trustpilot_tag_present_after": payload.get("trustpilot_tag_present_after"),
        "review_request_tag_present_after": payload.get("review_request_tag_present_after"),
        "typo_review_request_tag_present_after": payload.get("typo_review_request_tag_present_after"),
        "trustpilot_tag_added": payload.get("trustpilot_tag_added"),
        "review_request_tag_removed": payload.get("review_request_tag_removed"),
        "typo_review_request_tag_removed": payload.get("typo_review_request_tag_removed"),
        "all_review_request_aliases_removed": payload.get("all_review_request_aliases_removed"),
        "readback_verified": payload.get("readback_verified"),
        "tag_write_readback_verified": payload.get("tag_write_readback_verified"),
        "local_shopify_tags_updated": payload.get("local_shopify_tags_updated"),
        "local_tags_after_update": payload.get("local_tags_after_update"),
        "tag_write_attempted": payload.get("tag_write_attempted"),
        "tag_write_performed": payload.get("tag_write_performed"),
        "shopify_tag_write_performed": payload.get("shopify_tag_write_performed"),
        "shopify_write_performed": payload.get("shopify_write_performed"),
        "shopify_api_call_performed": payload.get("shopify_api_call_performed"),
        "gmail_api_call_performed": payload.get("gmail_api_call_performed"),
        "email_sent": payload.get("email_sent"),
        "blocking_condition_count": payload.get("blocking_condition_count"),
        "blocking_conditions": payload.get("blocking_conditions"),
        "detected_issue_summary": payload.get("detected_issue_summary"),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Trustpilot post-send Shopify tag-write task completed.\n"
        f"Status: {payload.get('tag_write_status')}\n"
        f"Selected order: {payload.get('selected_order')}\n"
        f"Source audit status: {payload.get('source_audit_status')}\n"
        f"Selected source: {payload.get('selected_source')}\n"
        f"Source paths checked: {', '.join(payload.get('source_paths_checked') or [])}\n"
        f"Host report found: {payload.get('host_report_found')}\n"
        f"Django audit source found: {payload.get('django_audit_source_found')}\n"
        f"Django audit error: {payload.get('django_audit_error')}\n"
        f"Latest Review & Send report found: {payload.get('latest_review_send_report_found')}\n"
        f"Latest post-send audit found: {payload.get('latest_post_send_audit_found')}\n"
        f"History ledger error: {payload.get('history_ledger_error')}\n"
        f"Why not ready: {', '.join(payload.get('why_not_ready') or [])}\n"
        f"Email sent confirmed: {payload.get('email_sent_confirmed')}\n"
        f"Sent count: {payload.get('sent_count')}\n"
        f"Tag write ready: {payload.get('tag_write_ready')}\n"
        f"Approval env valid: {payload.get('approval_env_valid')}\n"
        f"Shopify API call performed: {payload.get('shopify_api_call_performed')}\n"
        f"Shopify write performed: {payload.get('shopify_write_performed')}\n"
        f"Gmail API call performed: {payload.get('gmail_api_call_performed')}\n"
        f"All review request aliases removed: {payload.get('all_review_request_aliases_removed')}\n"
        f"Readback verified: {payload.get('readback_verified')}\n"
        f"Local ShopifyOrder tags updated: {payload.get('local_shopify_tags_updated')}\n"
        f"JSON: {json_path}\n"
        f"HTML: {html_path}\n"
    )


def _issue_summary(status: str, selected_order: str, blockers: list[dict], write_result: dict) -> str:
    if status == SUCCESS_STATUS:
        if write_result.get("tag_write_already_complete") is True:
            return (
                f"{selected_order} already had the Trustpilot completion tag and no review-request trigger aliases. "
                "No Gmail or external review API call was performed."
            )
        return (
            f"{selected_order} has Trustpilot tag present and review-request trigger aliases absent after readback. "
            "No Gmail or external review API call was performed."
        )
    if status == MISSING_APPROVAL_STATUS:
        return (
            f"{selected_order} is gated for Shopify tag write. Missing exact approval env; "
            "no Shopify API call or write was performed."
        )
    if status == REVIEW_REQUEST_ALIAS_STILL_PRESENT_STATUS:
        return (
            f"{selected_order} still has a review-request trigger alias after Shopify readback. "
            "Local tags were not marked written; no Gmail or external review API call was performed."
        )
    first = blockers[0]["status"] if blockers else status
    return f"Trustpilot post-send tag write blocked: {first}. No Gmail or external review API call was performed."


def _privacy_scan(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_emails = []
    for match in EMAIL_RE.finditer(text):
        value = match.group(0).lower()
        if value == "info@kidstoylover.com" or "***" in value:
            continue
        raw_emails.append(_mask_email(value))
    secret_count = 1 if SECRET_RE.search(text) else 0
    return {
        "scan_performed": True,
        "passed": not raw_emails and not secret_count,
        "raw_customer_email_count": len(set(raw_emails)),
        "masked_raw_customer_email_findings": sorted(set(raw_emails))[:5],
        "secret_pattern_count": secret_count,
    }


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _canonical_order_name(value) -> str:
    text = _safe_text(value, max_length=80)
    match = re.fullmatch(r"#?(\d{3,})", text)
    return f"#{match.group(1)}" if match else text


def _safe_text(value, max_length: int = 300) -> str:
    text = _sanitize_text(value)
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


def _dedupe_text(values) -> list[str]:
    seen = set()
    result = []
    for value in values or []:
        text = _safe_text(value, max_length=180)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _sanitize_text(value) -> str:
    text = str(value or "").replace("\x00", "")
    text = EMAIL_RE.sub(lambda match: _mask_email(match.group(0)), text)
    text = SECRET_RE.sub("[redacted-secret-marker]", text)
    return " ".join(text.split())


def _mask_email(email: str) -> str:
    value = str(email or "").strip()
    if "@" not in value:
        return ""
    local, domain = value.split("@", 1)
    suffix = domain.split(".")[-1] if "." in domain else ""
    head = domain.split(".", 1)[0] if domain else ""
    if suffix:
        return f"{local[:1]}***@{head[:1]}***.{suffix}"
    return f"{local[:1]}***@***"
