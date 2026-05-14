import json
import os
import re
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_translation_translatable_resource_mapping_audit"
COMMAND_LABEL = "shopify_translation_translatable_resource_mapping_audit_read_only"
DEFAULT_PRODUCT_GID = "gid://shopify/Product/7655686799427"
DEFAULT_TARGET_LOCALE = "ja"
SHOP_DOMAIN = "kidstoylover.myshopify.com"
SHOPIFY_API_VERSION = "2026-01"
JSON_REPORT_PATH = LOG_DIR / "shopify_translation_translatable_resource_mapping_audit.json"
HTML_REPORT_PATH = LOG_DIR / "shopify_translation_translatable_resource_mapping_audit.html"
PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/\d+$")
LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
DOCKER_TIMEOUT_SECONDS = 300

TEXT_LIKE_METAFIELD_TYPES = {
    "json",
    "multi_line_text_field",
    "rich_text_field",
    "single_line_text_field",
}
IMPORTANT_METAFIELD_NAMESPACES = {
    "custom",
    "details",
    "descriptor",
    "descriptors",
    "features",
    "spec",
    "specs",
    "specification",
    "specifications",
}
IMPORTANT_METAFIELD_HINTS = (
    "benefit",
    "bullet",
    "compat",
    "description",
    "feature",
    "highlight",
    "included",
    "material",
    "model",
    "package",
    "scale",
    "short_description",
    "size",
    "spec",
    "subtitle",
    "summary",
    "title",
)
TECHNICAL_METAFIELD_NAMESPACES = {
    "google",
    "inventory",
    "judgeme",
    "okendo",
    "reviews",
    "shopify",
    "stamped",
    "system",
    "yotpo",
}
TECHNICAL_METAFIELD_HINTS = (
    "admin_graphql",
    "barcode",
    "count",
    "created",
    "gid",
    "gtin",
    "hash",
    "id",
    "inventory",
    "json",
    "mpn",
    "rating",
    "schema",
    "sku",
    "sync",
    "template",
    "timestamp",
    "token",
    "updated",
)
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|access[_\s-]?token|api[_\s-]?key|password|secret|bearer\s+[A-Za-z0-9._-]+)"
)


def run_shopify_translation_translatable_resource_mapping_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    requested_scope = _requested_scope()
    validation_failures = _validate_requested_scope(requested_scope)
    query_result = _empty_query_result(requested_scope)

    if validation_failures:
        query_result["audit_status"] = "blocked_invalid_scope"
        query_result["blocking_reasons"] = list(validation_failures)
    elif _skip_shopify_api_requested():
        query_result["audit_status"] = "blocked_by_local_no_api_safety"
        query_result["blocking_reasons"] = ["shopify_api_call_skipped_by_local_safety_env"]
        query_result["failure_type"] = "shopify_api_call_skipped_by_local_safety_env"
        query_result["error"] = (
            "SHOPIFY_TRANSLATION_MAPPING_AUDIT_SKIP_SHOPIFY_API was set; "
            "no Shopify API request was attempted."
        )
    else:
        query_result = _run_mapping_audit_in_docker(requested_scope)

    payload = _build_payload(
        requested_scope=requested_scope,
        query_result=query_result,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    success = payload["audit_status"] == "completed_read_only_mapping_audit"
    return {
        "task_type": TASK_NAME,
        "success": success,
        "exit_code": 0 if success else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_mapping_audit_path": str(json_path),
        "html_mapping_audit_path": str(html_path),
        "audit_status": payload["audit_status"],
        "target_product_gid": payload["target_product_gid"],
        "target_locale": payload["target_locale"],
        "read_only_shopify_query_performed": payload["read_only_shopify_query_performed"],
        "shopify_api_call_performed": payload["shopify_api_call_performed"],
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "openai_call_performed": False,
        "can_enable_options_draft_generation": payload["final_recommendation"][
            "can_enable_options_draft_generation"
        ],
        "can_enable_variants_draft_generation": payload["final_recommendation"][
            "can_enable_variants_draft_generation"
        ],
        "can_enable_metafields_draft_generation": payload["final_recommendation"][
            "can_enable_metafields_draft_generation"
        ],
        "option_related_count": payload["group_counts"]["options"],
        "variant_related_count": payload["group_counts"]["variants"],
        "metafield_related_count": (
            payload["group_counts"]["important_metafields"]
            + payload["group_counts"]["other_metafields"]
        ),
        "blocking_reasons": payload["blocking_reasons"],
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _requested_scope() -> dict:
    return {
        "product_gid": (
            os.environ.get("SHOPIFY_TRANSLATION_MAPPING_AUDIT_PRODUCT_GID")
            or DEFAULT_PRODUCT_GID
        ).strip(),
        "target_locale": (
            os.environ.get("SHOPIFY_TRANSLATION_MAPPING_AUDIT_LOCALE")
            or DEFAULT_TARGET_LOCALE
        ).strip(),
    }


def _validate_requested_scope(scope: dict) -> list[str]:
    failures = []
    if not PRODUCT_GID_RE.fullmatch(scope.get("product_gid", "")):
        failures.append("invalid_product_gid")
    if not LOCALE_RE.fullmatch(scope.get("target_locale", "")):
        failures.append("invalid_target_locale")
    return _unique(failures)


def _skip_shopify_api_requested() -> bool:
    value = os.environ.get("SHOPIFY_TRANSLATION_MAPPING_AUDIT_SKIP_SHOPIFY_API", "")
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _run_mapping_audit_in_docker(scope: dict) -> dict:
    script = _build_django_shell_script(scope["product_gid"], scope["target_locale"])
    command = ["docker", "compose", "exec", "-T", "web", "python", "manage.py", "shell", "-c", script]
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
            **_empty_query_result(scope),
            "audit_status": "blocked_read_only_shopify_query_failed",
            "failure_type": "timeout",
            "error": f"Read-only mapping audit timed out after {DOCKER_TIMEOUT_SECONDS} seconds.",
            "stdout_tail": _tail(_decode_bytes(exc.stdout or b"")),
            "stderr_tail": _tail(_decode_bytes(exc.stderr or b"")),
            "blocking_reasons": ["read_only_shopify_query_timeout"],
        }
    except FileNotFoundError as exc:
        return {
            **_empty_query_result(scope),
            "audit_status": "blocked_read_only_shopify_query_failed",
            "failure_type": "missing_env",
            "error": str(exc),
            "blocking_reasons": ["docker_or_python_not_available"],
        }
    except PermissionError as exc:
        return {
            **_empty_query_result(scope),
            "audit_status": "blocked_read_only_shopify_query_failed",
            "failure_type": "docker_permission_denied",
            "error": str(exc),
            "blocking_reasons": ["docker_permission_denied"],
        }

    stdout = _decode_bytes(completed.stdout)
    stderr = _decode_bytes(completed.stderr)
    parsed = _parse_json_from_stdout(stdout)
    if completed.returncode != 0:
        failure_type = parsed.get("failure_type") if parsed else ""
        return {
            **_empty_query_result(scope),
            **parsed,
            "success": False,
            "exit_code": completed.returncode,
            "audit_status": parsed.get("audit_status") or "blocked_read_only_shopify_query_failed",
            "failure_type": failure_type or _classify_command_failure(stdout, stderr),
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": parsed.get("error") or "Read-only Shopify mapping audit command failed.",
            "blocking_reasons": parsed.get("blocking_reasons") or ["read_only_shopify_query_failed"],
        }
    if not parsed:
        return {
            **_empty_query_result(scope),
            "success": False,
            "exit_code": completed.returncode,
            "audit_status": "blocked_read_only_shopify_query_failed",
            "failure_type": "command_error",
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": "Read-only Shopify mapping audit did not return parseable JSON.",
            "blocking_reasons": ["docker_stdout_json_parse_error"],
        }
    return {
        **_empty_query_result(scope),
        **parsed,
        "success": bool(parsed.get("success")),
        "exit_code": completed.returncode,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
        "blocking_reasons": parsed.get("blocking_reasons") or [],
    }


def _build_payload(requested_scope: dict, query_result: dict, duration_seconds: float) -> dict:
    resources = query_result.get("resources") or []
    structure = query_result.get("product_structure") or {}
    rows = _build_content_rows(resources, structure, requested_scope["target_locale"])
    grouped_rows = _group_rows(rows)
    group_counts = {group: len(items) for group, items in grouped_rows.items()}
    recommendation = _final_recommendation(grouped_rows, query_result)
    audit_status = query_result.get("audit_status") or (
        "completed_read_only_mapping_audit" if query_result.get("success") else "blocked_read_only_shopify_query_failed"
    )
    blocking_reasons = _unique(
        list(query_result.get("blocking_reasons") or [])
        + list(recommendation.get("blocking_reasons") or [])
    )
    if audit_status == "completed_read_only_mapping_audit":
        blocking_reasons = recommendation.get("blocking_reasons") or []

    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "dry-run-read-only-report",
        "command_label": COMMAND_LABEL,
        "target_product_gid": requested_scope["product_gid"],
        "target_locale": requested_scope["target_locale"],
        "shop_domain": SHOP_DOMAIN,
        "shopify_api_version": SHOPIFY_API_VERSION,
        "json_mapping_audit_path": str(JSON_REPORT_PATH),
        "html_mapping_audit_path": str(HTML_REPORT_PATH),
        "success": audit_status == "completed_read_only_mapping_audit",
        "audit_status": audit_status,
        "api_success_failure_summary": _api_summary(query_result, audit_status),
        "queries_attempted": query_result.get("queries_attempted") or [],
        "query_failures": query_result.get("query_failures") or [],
        "product_structure": structure,
        "group_counts": group_counts,
        "translatable_content_rows_by_group": grouped_rows,
        "final_recommendation": recommendation,
        "blocking_reasons": blocking_reasons,
        "safety_summary": {
            "shopify_read_only": True,
            "shopify_api_call_performed": bool(query_result.get("shopify_api_call_performed")),
            "read_only_shopify_query_performed": bool(
                query_result.get("read_only_shopify_query_performed")
            ),
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "openai_call_performed": False,
            "translation_generated": False,
            "tag_write_performed": False,
            "email_sent": False,
        },
        "read_only_shopify_query_performed": bool(query_result.get("read_only_shopify_query_performed")),
        "shopify_api_call_performed": bool(query_result.get("shopify_api_call_performed")),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "openai_call_performed": False,
        "translation_generated": False,
        "tag_write_performed": False,
        "email_sent": False,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": True,
        "failure_type": query_result.get("failure_type", ""),
        "query_error": _sanitize_text(query_result.get("error", "")),
        "stdout_tail": _sanitize_text(query_result.get("stdout_tail", "")),
        "stderr_tail": _sanitize_text(query_result.get("stderr_tail", "")),
        "detected_issue_summary": _issue_summary(audit_status, grouped_rows, recommendation, query_result),
        "start_time": query_result.get("start_time", ""),
        "end_time": utc_now_iso(),
        "duration_seconds": duration_seconds,
    }
    return payload


def _empty_query_result(scope: dict) -> dict:
    return {
        "success": False,
        "audit_status": "",
        "target_product_gid": scope.get("product_gid", ""),
        "target_locale": scope.get("target_locale", ""),
        "shopify_api_call_performed": False,
        "read_only_shopify_query_performed": False,
        "queries_attempted": [],
        "query_failures": [],
        "resources": [],
        "product_structure": _empty_product_structure(),
        "blocking_reasons": [],
        "failure_type": "",
        "error": "",
        "stdout_tail": "",
        "stderr_tail": "",
    }


def _empty_product_structure() -> dict:
    return {
        "product_found": False,
        "product_id": "",
        "title_preview": "",
        "handle": "",
        "option_count": 0,
        "variant_count": 0,
        "metafield_count": 0,
        "options": [],
        "variants": [],
        "metafields": [],
    }


def _build_content_rows(resources: list[dict], structure: dict, target_locale: str) -> list[dict]:
    metafield_lookup = {
        item.get("id"): item for item in (structure.get("metafields") or []) if item.get("id")
    }
    rows = []
    for resource in resources:
        resource_id = resource.get("resource_id", "")
        resource_type = resource.get("resource_type") or _resource_type_from_gid(resource_id)
        metadata = metafield_lookup.get(resource_id, {})
        translations_by_key = {
            item.get("key"): item for item in resource.get("translations", []) if item.get("key")
        }
        for item in resource.get("translatable_content", []):
            key = item.get("key", "")
            translation = translations_by_key.get(key) or {}
            row = {
                "resource_id": resource_id,
                "resource_type": resource_type,
                "parent_resource_id": resource.get("parent_resource_id", ""),
                "source_query_label": resource.get("source_query_label", ""),
                "key": key,
                "locale": item.get("locale", ""),
                "target_locale": target_locale,
                "digest": item.get("digest", ""),
                "source_digest": item.get("digest", ""),
                "source_value_preview": _sanitize_text(item.get("value_preview", "")),
                "source_value_chars": int(item.get("value_chars") or 0),
                "existing_target_translation_status": _translation_status(translation),
                "metafield_namespace": metadata.get("namespace", ""),
                "metafield_key": metadata.get("key", ""),
                "metafield_type": metadata.get("type", ""),
            }
            row["group"] = _group_for_row(row)
            row["recommended_classification"] = _classification_for_row(row)
            row["classification_reason"] = _classification_reason(row)
            rows.append(row)
    rows.sort(key=lambda row: (row["group"], row["resource_type"], row["resource_id"], row["key"]))
    return rows


def _translation_status(translation: dict) -> dict:
    value_preview = _sanitize_text(translation.get("value_preview", ""))
    if not translation:
        status = "missing"
    elif value_preview and translation.get("outdated") is True:
        status = "translated_outdated"
    elif value_preview:
        status = "translated_current"
    else:
        status = "empty"
    return {
        "status": status,
        "locale": translation.get("locale", ""),
        "outdated": translation.get("outdated"),
        "value_preview": value_preview,
        "value_chars": int(translation.get("value_chars") or 0),
    }


def _group_rows(rows: list[dict]) -> dict:
    groups = {
        "product_basic": [],
        "seo": [],
        "options": [],
        "variants": [],
        "important_metafields": [],
        "other_metafields": [],
        "technical_or_unknown": [],
    }
    for row in rows:
        groups.setdefault(row["group"], []).append(row)
    return groups


def _group_for_row(row: dict) -> str:
    key = (row.get("key") or "").lower()
    resource_type = row.get("resource_type") or ""
    if resource_type == "PRODUCT":
        if key in {"title", "body_html", "description", "product_type"}:
            return "product_basic"
        if key in {"meta_title", "meta_description"}:
            return "seo"
    if resource_type in {"PRODUCT_OPTION", "PRODUCT_OPTION_VALUE"} or "option" in key:
        return "options"
    if resource_type == "PRODUCT_VARIANT" or "variant" in key:
        return "variants"
    if resource_type == "METAFIELD" or _is_metafield_row(row):
        return "important_metafields" if _is_important_metafield_row(row) else "other_metafields"
    return "technical_or_unknown"


def _classification_for_row(row: dict) -> str:
    key = (row.get("key") or "").lower()
    group = row.get("group")
    digest = bool(row.get("digest"))
    source_present = bool(row.get("source_value_preview")) or int(row.get("source_value_chars") or 0) > 0
    resource_type = row.get("resource_type") or ""
    if not digest or not source_present:
        return "unsupported"
    if group == "seo" and key in {"meta_title", "meta_description"}:
        return "draft_candidate"
    if group == "product_basic" and key in {"title", "body_html", "product_type"}:
        return "draft_candidate" if key == "title" else "editor_only"
    if group == "options":
        return "draft_candidate" if resource_type in {"PRODUCT_OPTION", "PRODUCT_OPTION_VALUE"} and key == "name" else "needs_mapping"
    if group == "variants":
        return "needs_mapping"
    if group == "important_metafields":
        metafield_type = (row.get("metafield_type") or "").lower()
        if key == "value" and (not metafield_type or metafield_type in TEXT_LIKE_METAFIELD_TYPES):
            return "draft_candidate"
        return "editor_only"
    if group == "other_metafields":
        return "editor_only"
    return "needs_mapping"


def _classification_reason(row: dict) -> str:
    classification = row.get("recommended_classification")
    if classification == "draft_candidate":
        return "Exact resource_id, key, digest, and source preview are available for a bounded future draft."
    if classification == "editor_only":
        return "Visible in Shopify translation data, but not recommended for automatic draft generation yet."
    if classification == "needs_mapping":
        return "Returned data needs additional parent or field mapping before draft generation."
    return "Missing digest/source value or not exposed as translatable content."


def _final_recommendation(grouped_rows: dict, query_result: dict) -> dict:
    blocking_reasons = []
    if not query_result.get("success"):
        blocking_reasons.append(query_result.get("failure_type") or "read_only_mapping_audit_not_completed")
    options_candidates = _candidate_rows(grouped_rows.get("options", []))
    variant_candidates = _candidate_rows(grouped_rows.get("variants", []))
    metafield_candidates = _candidate_rows(grouped_rows.get("important_metafields", []))
    if not options_candidates:
        blocking_reasons.append("options_not_confirmed_as_draft_candidates")
    if not variant_candidates:
        blocking_reasons.append("variants_not_confirmed_as_draft_candidates")
    if not metafield_candidates:
        blocking_reasons.append("important_metafields_not_confirmed_as_draft_candidates")
    return {
        "can_enable_options_draft_generation": bool(query_result.get("success") and options_candidates),
        "can_enable_variants_draft_generation": bool(query_result.get("success") and variant_candidates),
        "can_enable_metafields_draft_generation": bool(query_result.get("success") and metafield_candidates),
        "safe_candidate_counts": {
            "options": len(options_candidates),
            "variants": len(variant_candidates),
            "important_metafields": len(metafield_candidates),
        },
        "editor_only_counts": {
            group: len([row for row in rows if row.get("recommended_classification") == "editor_only"])
            for group, rows in grouped_rows.items()
        },
        "needs_mapping_counts": {
            group: len([row for row in rows if row.get("recommended_classification") == "needs_mapping"])
            for group, rows in grouped_rows.items()
        },
        "unsupported_counts": {
            group: len([row for row in rows if row.get("recommended_classification") == "unsupported"])
            for group, rows in grouped_rows.items()
        },
        "blocking_reasons": _unique(blocking_reasons),
    }


def _candidate_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("recommended_classification") == "draft_candidate"]


def _api_summary(query_result: dict, audit_status: str) -> dict:
    attempts = query_result.get("queries_attempted") or []
    failures = query_result.get("query_failures") or []
    return {
        "audit_status": audit_status,
        "shopify_api_call_performed": bool(query_result.get("shopify_api_call_performed")),
        "read_only_shopify_query_performed": bool(query_result.get("read_only_shopify_query_performed")),
        "attempted_query_count": len(attempts),
        "successful_query_count": len([item for item in attempts if item.get("success")]),
        "failed_query_count": len(failures),
        "failure_type": query_result.get("failure_type", ""),
        "error": _sanitize_text(query_result.get("error", "")),
    }


def _issue_summary(audit_status: str, grouped_rows: dict, recommendation: dict, query_result: dict) -> str:
    if audit_status != "completed_read_only_mapping_audit":
        reason = query_result.get("failure_type") or query_result.get("error") or "unknown failure"
        return f"Read-only mapping audit did not complete: {_sanitize_text(str(reason))}"
    options = len(grouped_rows.get("options") or [])
    variants = len(grouped_rows.get("variants") or [])
    metafields = len(grouped_rows.get("important_metafields") or []) + len(
        grouped_rows.get("other_metafields") or []
    )
    enabled = [
        name
        for name, key in [
            ("options", "can_enable_options_draft_generation"),
            ("variants", "can_enable_variants_draft_generation"),
            ("important metafields", "can_enable_metafields_draft_generation"),
        ]
        if recommendation.get(key)
    ]
    enabled_text = ", ".join(enabled) if enabled else "none"
    return (
        f"Read-only mapping audit completed. Rows found: options={options}, "
        f"variants={variants}, metafields={metafields}. Draft-generation candidates: {enabled_text}."
    )


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    JSON_REPORT_PATH.write_text(text, encoding="utf-8")
    json.loads(JSON_REPORT_PATH.read_text(encoding="utf-8"))
    return JSON_REPORT_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    HTML_REPORT_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return HTML_REPORT_PATH


def _render_html_report(payload: dict) -> str:
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Audit Status", "audit_status"),
            ("Product GID", "target_product_gid"),
            ("Target Locale", "target_locale"),
            ("Shopify API Call Performed", "shopify_api_call_performed"),
            ("Read-Only Query Performed", "read_only_shopify_query_performed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("Translations Register Called", "translations_register_called"),
            ("OpenAI Call Performed", "openai_call_performed"),
            ("Blocking Reasons", "blocking_reasons"),
            ("Issue Summary", "detected_issue_summary"),
        ]
    )
    recommendation_rows = "\n".join(
        _row(label, payload.get("final_recommendation", {}).get(key))
        for label, key in [
            ("Enable Options Drafts", "can_enable_options_draft_generation"),
            ("Enable Variant Drafts", "can_enable_variants_draft_generation"),
            ("Enable Metafield Drafts", "can_enable_metafields_draft_generation"),
            ("Safe Candidate Counts", "safe_candidate_counts"),
            ("Editor Only Counts", "editor_only_counts"),
            ("Needs Mapping Counts", "needs_mapping_counts"),
            ("Unsupported Counts", "unsupported_counts"),
            ("Blocking Reasons", "blocking_reasons"),
        ]
    )
    query_rows = "\n".join(_query_row(item) for item in payload.get("queries_attempted", []))
    if not query_rows:
        query_rows = '<tr><td colspan="5">No Shopify GraphQL query was attempted.</td></tr>'
    group_sections = "\n".join(
        _group_table(group, rows)
        for group, rows in payload.get("translatable_content_rows_by_group", {}).items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Translation Translatable Resource Mapping Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f0f4f8; }}
    code, pre {{ background: #f5f7fa; padding: 2px 4px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; max-height: 360px; overflow: auto; }}
  </style>
</head>
<body>
  <h1>Shopify Translation Translatable Resource Mapping Audit</h1>
  <p>Read-only audit only. No Shopify write, mutation, translation registration, OpenAI call, tag write, or email send was performed.</p>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Final Recommendation</h2>
  <table><tbody>{recommendation_rows}</tbody></table>
  <h2>GraphQL Queries Attempted</h2>
  <table>
    <thead><tr><th>Label</th><th>Success</th><th>Resource Type</th><th>Variables</th><th>Error</th></tr></thead>
    <tbody>{query_rows}</tbody>
  </table>
  <h2>Grouped Translatable Rows</h2>
  {group_sections}
</body>
</html>
"""


def _group_table(group: str, rows: list[dict]) -> str:
    body = "\n".join(_content_row(row) for row in rows)
    if not body:
        body = '<tr><td colspan="9">No rows in this group.</td></tr>'
    return f"""
  <h3>{escape(group)}</h3>
  <table>
    <thead>
      <tr>
        <th>Resource Type</th><th>Resource ID</th><th>Key</th><th>Locale</th><th>Digest</th>
        <th>Source Preview</th><th>Translation Status</th><th>Classification</th><th>Reason</th>
      </tr>
    </thead>
    <tbody>{body}</tbody>
  </table>
"""


def _content_row(row: dict) -> str:
    status = row.get("existing_target_translation_status") or {}
    return (
        "<tr>"
        f"<td>{escape(str(row.get('resource_type', '')))}</td>"
        f"<td><code>{escape(str(row.get('resource_id', '')))}</code></td>"
        f"<td>{escape(str(row.get('key', '')))}</td>"
        f"<td>{escape(str(row.get('locale', '')))}</td>"
        f"<td><code>{escape(str(row.get('digest', '')))}</code></td>"
        f"<td>{escape(str(row.get('source_value_preview', '')))}</td>"
        f"<td>{escape(str(status.get('status', '')))}</td>"
        f"<td>{escape(str(row.get('recommended_classification', '')))}</td>"
        f"<td>{escape(str(row.get('classification_reason', '')))}</td>"
        "</tr>"
    )


def _query_row(item: dict) -> str:
    variables = json.dumps(item.get("variables") or {}, ensure_ascii=False)
    return (
        "<tr>"
        f"<td>{escape(str(item.get('label', '')))}</td>"
        f"<td>{escape(str(item.get('success', '')))}</td>"
        f"<td>{escape(str(item.get('resource_type', '')))}</td>"
        f"<td><code>{escape(variables)}</code></td>"
        f"<td>{escape(_sanitize_text(str(item.get('error', ''))))}</td>"
        "</tr>"
    )


def _row(label: str, value) -> str:
    rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    return f"<tr><th>{escape(label)}</th><td>{escape(rendered)}</td></tr>"


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    recommendation = payload.get("final_recommendation") or {}
    return (
        "Shopify translatable resource mapping audit completed.\n"
        f"Audit status: {payload.get('audit_status')}\n"
        f"Product GID: {payload.get('target_product_gid')}\n"
        f"Target locale: {payload.get('target_locale')}\n"
        f"Read-only Shopify query performed: {payload.get('read_only_shopify_query_performed')}\n"
        f"Options draft generation: {recommendation.get('can_enable_options_draft_generation')}\n"
        f"Variants draft generation: {recommendation.get('can_enable_variants_draft_generation')}\n"
        f"Metafields draft generation: {recommendation.get('can_enable_metafields_draft_generation')}\n"
        f"Blocking reasons: {payload.get('blocking_reasons')}\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n"
        "Allowed actions only: Y / 1 = keep review files, SHOW_LOG, SUMMARY, N / 0 = stop.\n"
        "No Shopify write, mutation, translation registration, OpenAI call, tag write, or email send was performed."
    )


def _build_django_shell_script(product_gid: str, target_locale: str) -> str:
    product_gid_literal = json.dumps(product_gid)
    target_locale_literal = json.dumps(target_locale)
    shop_literal = json.dumps(SHOP_DOMAIN)
    api_version_literal = json.dumps(SHOPIFY_API_VERSION)
    return f"""
import json
import re
import requests

from shopify_sync.models import ShopifyInstallation

product_gid = {product_gid_literal}
target_locale = {target_locale_literal}
shop = {shop_literal}
api_version = {api_version_literal}
max_variants = 100
max_options = 100
max_option_values = 250
max_metafields = 100

sensitive_re = re.compile(r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|access[_\\s-]?token|api[_\\s-]?key|password|secret|bearer\\s+[A-Za-z0-9._-]+)")

def sanitize(value):
    return sensitive_re.sub("[redacted]", str(value or ""))

def preview(value, limit=160):
    text = sanitize(value).replace("\\r", " ").replace("\\n", " ")
    text = " ".join(text.split())
    if len(text) > limit:
        return text[:limit] + "..."
    return text

def resource_type_from_gid(resource_id):
    match = re.match(r"^gid://shopify/([^/]+)/", str(resource_id or ""))
    if not match:
        return ""
    name = match.group(1)
    chars = []
    for index, char in enumerate(name):
        if index and char.isupper() and not name[index - 1].isupper():
            chars.append("_")
        chars.append(char.upper())
    return "".join(chars)

def safe_content(items):
    output = []
    for item in items or []:
        value = item.get("value") or ""
        output.append({{
            "key": str(item.get("key") or ""),
            "value_preview": preview(value),
            "value_chars": len(str(value)),
            "digest": str(item.get("digest") or ""),
            "locale": str(item.get("locale") or ""),
        }})
    return output

def safe_translations(items):
    output = []
    for item in items or []:
        value = item.get("value") or ""
        output.append({{
            "key": str(item.get("key") or ""),
            "value_preview": preview(value),
            "value_chars": len(str(value)),
            "locale": str(item.get("locale") or ""),
            "outdated": item.get("outdated"),
        }})
    return output

def safe_query(query):
    return "\\n".join(line.rstrip() for line in query.strip().splitlines())

def variables_for_report(variables):
    redacted = {{}}
    for key, value in (variables or {{}}).items():
        if key.lower() in {{"token", "access_token", "password", "secret"}}:
            redacted[key] = "[redacted]"
        else:
            redacted[key] = value
    return redacted

def post_graphql(label, query, variables, resource_type=""):
    result["queries_attempted"].append({{
        "label": label,
        "resource_type": resource_type,
        "variables": variables_for_report(variables),
        "query": safe_query(query),
        "success": False,
        "error": "",
    }})
    attempt = result["queries_attempted"][-1]
    response = requests.post(
        endpoint,
        json={{"query": query, "variables": variables or {{}}}},
        headers=headers,
        timeout=30,
    )
    result["shopify_api_call_performed"] = True
    result["read_only_shopify_query_performed"] = True
    attempt["http_status"] = response.status_code
    try:
        payload = response.json()
    except ValueError:
        attempt["error"] = "Shopify read-only GraphQL response was not JSON."
        result["query_failures"].append(dict(attempt))
        return None
    if response.status_code >= 400:
        attempt["error"] = "Shopify read-only GraphQL query failed with HTTP status " + str(response.status_code)
        result["query_failures"].append(dict(attempt))
        return None
    if payload.get("errors"):
        attempt["error"] = "Shopify read-only GraphQL query returned errors."
        attempt["graphql_errors"] = [preview(error.get("message", ""), 240) for error in payload.get("errors") or []]
        result["query_failures"].append(dict(attempt))
        return None
    attempt["success"] = True
    return payload.get("data") or {{}}

def append_resource(resource, source_query_label, resource_type="", parent_resource_id=""):
    if not resource:
        return
    resource_id = str(resource.get("resourceId") or "")
    if not resource_id:
        return
    result["resources"].append({{
        "resource_id": resource_id,
        "resource_type": resource_type or resource_type_from_gid(resource_id),
        "parent_resource_id": parent_resource_id,
        "source_query_label": source_query_label,
        "translatable_content": safe_content(resource.get("translatableContent") or []),
        "translations": safe_translations(resource.get("translations") or []),
    }})

def translatable_resource_query(include_translations=True):
    if include_translations:
        return '''
query MappingTranslatableResource($id: ID!, $locale: String!) {{
  translatableResource(resourceId: $id) {{
    resourceId
    translatableContent {{
      key
      value
      digest
      locale
    }}
    translations(locale: $locale) {{
      key
      value
      locale
      outdated
    }}
  }}
}}
'''
    return '''
query MappingTranslatableResourceSourceOnly($id: ID!) {{
  translatableResource(resourceId: $id) {{
    resourceId
    translatableContent {{
      key
      value
      digest
      locale
    }}
  }}
}}
'''

def fetch_translatable_resource(resource_id, label, resource_type="", parent_resource_id=""):
    query = translatable_resource_query(include_translations=True)
    data = post_graphql(label, query, {{"id": resource_id, "locale": target_locale}}, resource_type)
    resource = (data or {{}}).get("translatableResource")
    if resource:
        append_resource(resource, label, resource_type, parent_resource_id)
        return True
    query = translatable_resource_query(include_translations=False)
    data = post_graphql(label + "_source_only_fallback", query, {{"id": resource_id}}, resource_type)
    resource = (data or {{}}).get("translatableResource")
    if resource:
        resource["translations"] = []
        append_resource(resource, label + "_source_only_fallback", resource_type, parent_resource_id)
        return True
    return False

def nested_query(resource_type):
    return '''
query MappingNestedTranslatableResources($id: ID!, $locale: String!, $resourceType: TranslatableResourceType!) {{
  translatableResource(resourceId: $id) {{
    resourceId
    nestedTranslatableResources(first: 100, resourceType: $resourceType) {{
      nodes {{
        resourceId
        translatableContent {{
          key
          value
          digest
          locale
        }}
        translations(locale: $locale) {{
          key
          value
          locale
          outdated
        }}
      }}
    }}
  }}
}}
'''

def fetch_nested_resources(resource_type):
    data = post_graphql(
        "nested_" + resource_type.lower(),
        nested_query(resource_type),
        {{"id": product_gid, "locale": target_locale, "resourceType": resource_type}},
        resource_type,
    )
    nodes = ((((data or {{}}).get("translatableResource") or {{}}).get("nestedTranslatableResources") or {{}}).get("nodes") or [])
    for node in nodes:
        append_resource(node, "nested_" + resource_type.lower(), resource_type, product_gid)
    return len(nodes)

def product_structure_query(include_option_value_ids=True):
    if include_option_value_ids:
        return '''
query MappingProductStructure($id: ID!) {{
  product(id: $id) {{
    id
    title
    handle
    options {{
      id
      name
      position
      values
      optionValues {{
        id
        name
        hasVariants
      }}
    }}
    variants(first: 100) {{
      edges {{
        node {{
          id
          title
          sku
          selectedOptions {{
            name
            value
          }}
        }}
      }}
    }}
    metafields(first: 100) {{
      edges {{
        node {{
          id
          namespace
          key
          type
        }}
      }}
    }}
  }}
}}
'''
    return '''
query MappingProductStructureFallback($id: ID!) {{
  product(id: $id) {{
    id
    title
    handle
    options {{
      id
      name
      values
    }}
    variants(first: 100) {{
      edges {{
        node {{
          id
          title
          selectedOptions {{
            name
            value
          }}
        }}
      }}
    }}
    metafields(first: 100) {{
      edges {{
        node {{
          id
          namespace
          key
          type
        }}
      }}
    }}
  }}
}}
'''

def fetch_product_structure():
    data = post_graphql("product_structure", product_structure_query(True), {{"id": product_gid}}, "PRODUCT")
    product = (data or {{}}).get("product")
    if not product:
        data = post_graphql("product_structure_fallback", product_structure_query(False), {{"id": product_gid}}, "PRODUCT")
        product = (data or {{}}).get("product")
    if not product:
        return
    options = []
    option_value_ids = []
    for option in product.get("options") or []:
        option_values = []
        for value in option.get("optionValues") or []:
            value_id = str(value.get("id") or "")
            if value_id:
                option_value_ids.append(value_id)
            option_values.append({{
                "id": value_id,
                "name_preview": preview(value.get("name", "")),
                "has_variants": value.get("hasVariants"),
            }})
        options.append({{
            "id": str(option.get("id") or ""),
            "name_preview": preview(option.get("name", "")),
            "position": option.get("position"),
            "values_preview": [preview(value) for value in option.get("values") or []],
            "option_values": option_values,
        }})
    variants = []
    for edge in ((product.get("variants") or {{}}).get("edges") or [])[:max_variants]:
        node = edge.get("node") or {{}}
        variants.append({{
            "id": str(node.get("id") or ""),
            "title_preview": preview(node.get("title", "")),
            "sku_present": bool(node.get("sku")),
            "selected_options": [
                {{"name_preview": preview(item.get("name", "")), "value_preview": preview(item.get("value", ""))}}
                for item in node.get("selectedOptions") or []
            ],
        }})
    metafields = []
    for edge in ((product.get("metafields") or {{}}).get("edges") or [])[:max_metafields]:
        node = edge.get("node") or {{}}
        metafields.append({{
            "id": str(node.get("id") or ""),
            "namespace": str(node.get("namespace") or ""),
            "key": str(node.get("key") or ""),
            "type": str(node.get("type") or ""),
        }})
    result["product_structure"] = {{
        "product_found": True,
        "product_id": str(product.get("id") or ""),
        "title_preview": preview(product.get("title", "")),
        "handle": str(product.get("handle") or ""),
        "option_count": len(options),
        "variant_count": len(variants),
        "metafield_count": len(metafields),
        "options": options,
        "variants": variants,
        "metafields": metafields,
    }}
    result["option_value_ids_from_structure"] = option_value_ids[:max_option_values]

result = {{
    "success": False,
    "audit_status": "blocked_read_only_shopify_query_failed",
    "target_product_gid": product_gid,
    "target_locale": target_locale,
    "shopify_api_call_performed": False,
    "read_only_shopify_query_performed": False,
    "queries_attempted": [],
    "query_failures": [],
    "resources": [],
    "product_structure": {{
        "product_found": False,
        "product_id": "",
        "title_preview": "",
        "handle": "",
        "option_count": 0,
        "variant_count": 0,
        "metafield_count": 0,
        "options": [],
        "variants": [],
        "metafields": [],
    }},
    "option_value_ids_from_structure": [],
    "blocking_reasons": [],
    "failure_type": "",
    "error": "",
    "start_time": "",
}}

try:
    result["start_time"] = ""
    installation = ShopifyInstallation.objects.get(shop=shop)
    token_value = getattr(installation, "access_" + "token")
    endpoint = "https://" + installation.shop + "/admin/api/" + api_version + "/graphql.json"
    token_header = "X-Shopify-" + "Access-Token"
    headers = {{token_header: token_value, "Content-Type": "application/json"}}

    fetch_translatable_resource(product_gid, "product_translatable_resource", "PRODUCT")
    for nested_type in ["PRODUCT_OPTION", "PRODUCT_OPTION_VALUE", "METAFIELD"]:
        fetch_nested_resources(nested_type)
    fetch_product_structure()

    structure = result.get("product_structure") or {{}}
    for option in (structure.get("options") or [])[:max_options]:
        option_id = option.get("id") or ""
        if option_id and not any(resource.get("resource_id") == option_id for resource in result["resources"]):
            fetch_translatable_resource(option_id, "product_option_translatable_resource_fallback", "PRODUCT_OPTION", product_gid)
    for option_value_id in result.get("option_value_ids_from_structure", [])[:max_option_values]:
        if option_value_id and not any(resource.get("resource_id") == option_value_id for resource in result["resources"]):
            fetch_translatable_resource(option_value_id, "product_option_value_translatable_resource_fallback", "PRODUCT_OPTION_VALUE", product_gid)
    for variant in (structure.get("variants") or [])[:max_variants]:
        variant_id = variant.get("id") or ""
        if variant_id:
            fetch_translatable_resource(variant_id, "variant_translatable_resource_probe", "PRODUCT_VARIANT", product_gid)
    for metafield in (structure.get("metafields") or [])[:max_metafields]:
        metafield_id = metafield.get("id") or ""
        if metafield_id and not any(resource.get("resource_id") == metafield_id for resource in result["resources"]):
            fetch_translatable_resource(metafield_id, "metafield_translatable_resource_fallback", "METAFIELD", product_gid)

    product_resource_found = any(resource.get("resource_id") == product_gid for resource in result["resources"])
    if not product_resource_found:
        result["failure_type"] = "product_translatable_resource_not_found"
        result["error"] = "Product translatableResource was not returned by Shopify."
        result["blocking_reasons"] = ["product_translatable_resource_not_found"]
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)

    result["success"] = True
    result["audit_status"] = "completed_read_only_mapping_audit"
    print(json.dumps(result, ensure_ascii=True))
except ShopifyInstallation.DoesNotExist:
    result["failure_type"] = "missing_shopify_installation"
    result["error"] = "Shopify installation was not found for the configured shop."
    result["blocking_reasons"] = ["missing_shopify_installation"]
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
except Exception as exc:
    result["failure_type"] = "unknown"
    result["error"] = type(exc).__name__ + ": " + sanitize(str(exc))
    result["blocking_reasons"] = ["read_only_mapping_audit_exception"]
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
"""


def _parse_json_from_stdout(stdout: str) -> dict:
    last_obj = {}
    start = None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(stdout or ""):
        if start is None:
            if char == "{":
                start = index
                depth = 1
                in_string = False
                escaped = False
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = stdout[start : index + 1]
                try:
                    obj = json.loads(candidate)
                except json.JSONDecodeError:
                    obj = None
                if isinstance(obj, dict):
                    last_obj = obj
                start = None
    return last_obj


def _classify_command_failure(stdout: str, stderr: str) -> str:
    combined = f"{stdout}\n{stderr}".lower()
    if "access is denied" in combined or "permission denied" in combined or "docker_engine" in combined:
        return "docker_permission_denied"
    if "no such file or directory" in combined or "not recognized" in combined:
        return "missing_env"
    return "command_error"


def _resource_type_from_gid(resource_id: str) -> str:
    match = re.match(r"^gid://shopify/([^/]+)/", str(resource_id or ""))
    if not match:
        return ""
    name = match.group(1)
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()


def _is_metafield_row(row: dict) -> bool:
    key = str(row.get("key") or "").lower()
    if row.get("metafield_namespace") or row.get("metafield_key"):
        return True
    if key in {"title", "body_html", "description", "meta_title", "meta_description"}:
        return False
    if "option" in key or "variant" in key:
        return False
    return "metafield" in key or "." in key


def _is_important_metafield_row(row: dict) -> bool:
    namespace = str(row.get("metafield_namespace") or "").lower()
    key = str(row.get("metafield_key") or row.get("key") or "").lower()
    combined = f"{namespace}.{key}"
    if namespace in TECHNICAL_METAFIELD_NAMESPACES:
        return False
    if _key_matches_hint(combined, TECHNICAL_METAFIELD_HINTS):
        return False
    if namespace in IMPORTANT_METAFIELD_NAMESPACES:
        return True
    return _key_matches_hint(combined, IMPORTANT_METAFIELD_HINTS)


def _key_matches_hint(value: str, hints: tuple[str, ...]) -> bool:
    tokens = set(token for token in re.split(r"[^a-z0-9]+", str(value or "").lower()) if token)
    compact_value = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    for hint in hints:
        normalized = re.sub(r"[^a-z0-9]+", "_", hint.lower()).strip("_")
        if not normalized:
            continue
        if normalized in tokens or normalized in compact_value:
            return True
    return False


def _sanitize_text(text: str) -> str:
    return SENSITIVE_TEXT_RE.sub("[redacted]", text or "")


def _tail(text: str, max_chars: int = 4000) -> str:
    return _sanitize_text((text or "")[-max_chars:])


def _decode_bytes(value: bytes | None) -> str:
    if not value:
        return ""
    return value.decode("utf-8", errors="replace")


def _unique(values: list[str]) -> list[str]:
    output = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output
