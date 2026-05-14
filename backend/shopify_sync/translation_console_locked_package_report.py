import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path


REPORT_DIR = Path("logs")
REPORT_PREFIX = "translation_console_locked_package_dry_run"


def generate_translation_console_locked_package_dry_run_report(
    apply_plan_preview_result: dict,
) -> dict:
    preview = apply_plan_preview_result or {}
    candidates = list(preview.get("candidate_entries") or [])
    blocked_entries = list(preview.get("blocked_entries") or [])
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    blocking_conditions = list(preview.get("blocking_conditions") or [])
    if not candidates:
        blocking_conditions.append("no_apply_plan_preview_candidates")

    report_status = (
        "translation_console_locked_package_dry_run_ready"
        if candidates and not blocking_conditions
        else "translation_console_locked_package_dry_run_blocked"
    )
    payload = {
        "report_status": report_status,
        "generated_at": generated_at,
        "product_gid": preview.get("product_id", ""),
        "product_title": preview.get("product_title", ""),
        "configured_locale_scope": preview.get("configured_locale_scope") or [],
        "configured_fields": preview.get("configured_fields") or [],
        "entry_count": len(candidates),
        "candidate_entries": [_report_candidate_entry(entry) for entry in candidates],
        "blocked_or_needs_review_count": len(blocked_entries),
        "blocked_or_needs_review_summary": [
            _report_blocked_entry(entry) for entry in blocked_entries
        ],
        "blocking_conditions": blocking_conditions,
        "approval_notes": [
            "This is a dry-run locked package report only.",
            "Real writes require explicit ACK and remote approval runner.",
        ],
        "dry_run_only": True,
        "preview_only": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "no_new_shopify_writes_performed": True,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.replace(":", "").replace("-", "").replace(".", "")
    stamp = stamp.replace("Z", "")
    json_path = REPORT_DIR / f"{REPORT_PREFIX}_{stamp}.json"
    html_path = REPORT_DIR / f"{REPORT_PREFIX}_{stamp}.html"
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(json_text, encoding="utf-8")
    html_path.write_text(_render_html(payload), encoding="utf-8")

    return {
        "report_status": report_status,
        "generated_at": generated_at,
        "json_report_path": json_path.as_posix(),
        "html_report_path": html_path.as_posix(),
        "entry_count": len(candidates),
        "blocked_or_needs_review_count": len(blocked_entries),
        "blocking_conditions": blocking_conditions,
        "dry_run_only": True,
        "preview_only": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "no_new_shopify_writes_performed": True,
    }


def _report_candidate_entry(entry: dict) -> dict:
    planned_value = str(entry.get("planned_value") or "")
    return {
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "resource_key": entry.get("resource_key", ""),
        "proposed_translation": planned_value,
        "planned_value": planned_value,
        "chars": entry.get("chars", len(planned_value)),
        "source_preview": entry.get("source_preview", ""),
        "seo_status": entry.get("seo_status", ""),
        "validation_status": entry.get("validation_status", ""),
        "planned_value_source": entry.get("planned_value_source", ""),
        "digest": entry.get("digest", ""),
        "would_write": False,
        "dry_run_only": True,
        "safety_status": "dry_run_locked_package_only_no_write",
    }


def _report_blocked_entry(entry: dict) -> dict:
    return {
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "resource_key": entry.get("resource_key", ""),
        "reason": entry.get("reason", ""),
        "seo_warning": entry.get("seo_warning", ""),
        "validation_status": entry.get("validation_status", ""),
        "seo_status": entry.get("seo_status", ""),
        "blocking_reasons": entry.get("blocking_reasons", ""),
        "current_translation_present": entry.get("current_translation_present"),
        "outdated": entry.get("outdated"),
    }


def _render_html(payload: dict) -> str:
    rows = []
    for key in [
        "report_status",
        "generated_at",
        "product_gid",
        "product_title",
        "entry_count",
        "blocked_or_needs_review_count",
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
        "rollback_performed",
        "gmail_api_call_performed",
        "email_sent",
    ]:
        rows.append(
            f"<tr><th>{escape(str(key))}</th><td>{escape(str(payload.get(key, '')))}</td></tr>"
        )
    candidate_rows = "".join(
        "<tr>"
        f"<td>{escape(str(entry.get('locale', '')))}</td>"
        f"<td>{escape(str(entry.get('field', '')))}</td>"
        f"<td>{escape(str(entry.get('resource_key', '')))}</td>"
        f"<td>{escape(str(entry.get('planned_value', '')))}</td>"
        f"<td>{escape(str(entry.get('chars', '')))}</td>"
        f"<td>{escape(str(entry.get('seo_status', '')))}</td>"
        f"<td>{escape(str(entry.get('validation_status', '')))}</td>"
        f"<td>{escape(str(entry.get('digest', '')))}</td>"
        f"<td>{escape(str(entry.get('would_write', '')))}</td>"
        "</tr>"
        for entry in payload.get("candidate_entries", [])
    )
    candidate_rows = candidate_rows or "<tr><td colspan='9'>No candidate entries</td></tr>"
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Translation Console Locked Package Dry-Run Report</title>"
        "<style>body{font-family:Arial,sans-serif;margin:24px;}table{border-collapse:collapse;width:100%;}"
        "th,td{border:1px solid #ddd;padding:6px;text-align:left;vertical-align:top;}th{background:#f5f5f5;}</style>"
        "</head><body>"
        "<h1>Translation Console Locked Package Dry-Run Report</h1>"
        "<p><strong>Report generated only. No Shopify write performed.</strong></p>"
        "<p>This is a dry-run locked package report only. Real writes require explicit ACK and remote approval runner.</p>"
        f"<table><tbody>{''.join(rows)}</tbody></table>"
        "<h2>Candidate entries</h2>"
        "<table><thead><tr><th>Locale</th><th>Field</th><th>Resource key</th>"
        "<th>Planned value</th><th>Chars</th><th>SEO status</th><th>Validation</th>"
        "<th>Digest</th><th>would_write</th></tr></thead>"
        f"<tbody>{candidate_rows}</tbody></table>"
        "</body></html>"
    )
