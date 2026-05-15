import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path


APPLY_PLAN_JSON_PATH = Path("logs/shopify_translation_selected_product_apply_plan_package.json")
APPLY_PLAN_HTML_PATH = Path("logs/shopify_translation_selected_product_apply_plan_package.html")
READY_DRAFT_STATUS = "selected_product_missing_translation_draft_ready_for_manual_review"


def build_selected_product_translation_apply_plan(draft_result, write_reports=True):
    draft_result = dict(draft_result or {})
    payload = _empty_apply_plan(draft_result)
    if not draft_result:
        payload["apply_plan_status"] = "blocked_missing_draft_package"
        payload["blocking_conditions"].append("blocked_missing_draft_package")
    elif draft_result.get("draft_status") != READY_DRAFT_STATUS:
        payload["apply_plan_status"] = "blocked_draft_package_not_ready"
        payload["blocking_conditions"].append("blocked_draft_package_not_ready")
    else:
        _collect_entries(payload, draft_result)
        if payload["entry_count"]:
            payload["apply_plan_status"] = "selected_product_translation_apply_plan_ready_for_manual_review"
            payload["success"] = True
        else:
            payload["apply_plan_status"] = "no_eligible_draft_entries_for_apply_plan"
            payload["success"] = True

    payload["timestamp"] = _utc_now()
    payload["generated_at"] = payload["timestamp"]
    payload["json_selected_product_apply_plan_package_path"] = str(APPLY_PLAN_JSON_PATH)
    payload["html_selected_product_apply_plan_package_path"] = str(APPLY_PLAN_HTML_PATH)

    if write_reports:
        _write_reports(payload)
    return payload


def _empty_apply_plan(draft_result):
    return {
        "success": False,
        "apply_plan_status": "",
        "apply_plan_only": True,
        "product_id": draft_result.get("product_id", ""),
        "product_title": draft_result.get("product_title", ""),
        "target_locales": list(draft_result.get("target_locales") or []),
        "requested_fields": list(draft_result.get("requested_fields") or []),
        "entry_count": 0,
        "skipped_count": 0,
        "apply_plan_entries": [],
        "skipped_entries": [],
        "source_draft_status": draft_result.get("draft_status", ""),
        "source_generated_draft_count": draft_result.get("generated_draft_count", 0),
        "source_eligible_apply_plan_count": draft_result.get("eligible_apply_plan_count", 0),
        "source_skipped_existing_translation_count": draft_result.get("skipped_existing_translation_count", 0),
        "source_skipped_outdated_translation_count": draft_result.get("skipped_outdated_translation_count", 0),
        "source_shopify_api_call_performed": draft_result.get("shopify_api_call_performed", False),
        "source_openai_call_performed": draft_result.get("openai_call_performed", False),
        "manual_review_required": True,
        "next_step_requires_separate_execute_task": True,
        "existing_translation_overwrite_allowed": False,
        "outdated_translation_overwrite_allowed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "rollback_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "blocking_conditions": [],
        "safety_summary": {
            "apply_plan_only": True,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "publish_performed": False,
            "apply_performed": False,
            "real_apply_performed": False,
            "rollback_performed": False,
            "existing_translation_overwrite_allowed": False,
            "outdated_translation_overwrite_allowed": False,
            "no_new_shopify_writes_performed": True,
            "all_new_actions_no_write_confirmed": True,
        },
    }


def _collect_entries(payload, draft_result):
    for entry in draft_result.get("entries", []):
        if _entry_is_apply_eligible(entry):
            payload["apply_plan_entries"].append(_apply_entry(payload, entry))
        else:
            payload["skipped_entries"].append(_skipped_entry(entry))
    payload["entry_count"] = len(payload["apply_plan_entries"])
    payload["skipped_count"] = len(payload["skipped_entries"])


def _entry_is_apply_eligible(entry):
    return (
        entry.get("eligible_for_apply_plan") is True
        and entry.get("validation_status") == "draft_ready_for_manual_review"
        and entry.get("seo_validation_status") == "seo_ready"
        and not entry.get("existing_translation_present")
        and entry.get("existing_translation_outdated") is not True
        and not entry.get("skip_reason")
        and not entry.get("future_write_needs_mapping")
        and entry.get("resource_group") in {"product_basics", "seo"}
        and entry.get("field") in {"title", "meta_title", "meta_description"}
        and bool(str(entry.get("draft_value") or "").strip())
    )


def _apply_entry(payload, entry):
    return {
        "product_id": payload.get("product_id", ""),
        "product_title": payload.get("product_title", ""),
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "source_key": entry.get("source_key", entry.get("field", "")),
        "resource_id": entry.get("resource_id", ""),
        "resource_group": entry.get("resource_group", ""),
        "source_value": entry.get("source_value", ""),
        "proposed_translation": entry.get("draft_value", ""),
        "proposed_value": entry.get("draft_value", ""),
        "proposed_value_chars": entry.get("draft_value_chars", len(str(entry.get("draft_value") or ""))),
        "digest": entry.get("source_digest", ""),
        "source_digest": entry.get("source_digest", ""),
        "current_translation_state": {
            "existing_translation_present": entry.get("existing_translation_present", False),
            "existing_translation_outdated": entry.get("existing_translation_outdated"),
            "skip_reason": entry.get("skip_reason", ""),
        },
        "validation_status": entry.get("validation_status", ""),
        "quality_notes": entry.get("quality_notes", []),
        "seo_validation_status": entry.get("seo_validation_status", ""),
        "seo_notes": entry.get("seo_notes", []),
        "eligible_for_apply_plan": True,
        "manual_review_required": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
    }


def _skipped_entry(entry):
    reason = entry.get("skip_reason") or "not_eligible_for_apply_plan"
    if entry.get("existing_translation_present"):
        reason = "already_translated"
    if entry.get("existing_translation_outdated") is True:
        reason = "existing_translation_outdated_manual_review_required"
    if entry.get("validation_status") != "draft_ready_for_manual_review" and not entry.get("skip_reason"):
        reason = "draft_not_ready_for_manual_review"
    if entry.get("seo_validation_status") != "seo_ready" and not entry.get("skip_reason"):
        reason = "seo_not_ready_for_apply_plan"
    if entry.get("future_write_needs_mapping"):
        reason = entry.get("apply_plan_blocked_reason") or "future_write_needs_resource_mapping"
    return {
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "resource_id": entry.get("resource_id", ""),
        "resource_group": entry.get("resource_group", ""),
        "source_value": entry.get("source_value", ""),
        "draft_value": entry.get("draft_value", ""),
        "validation_status": entry.get("validation_status", ""),
        "seo_validation_status": entry.get("seo_validation_status", ""),
        "eligible_for_apply_plan": bool(entry.get("eligible_for_apply_plan")),
        "skip_reason": reason,
        "existing_translation_present": entry.get("existing_translation_present", False),
        "existing_translation_outdated": entry.get("existing_translation_outdated"),
    }


def _write_reports(payload):
    APPLY_PLAN_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    APPLY_PLAN_JSON_PATH.write_text(text, encoding="utf-8")
    APPLY_PLAN_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")


def _render_html(payload):
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Apply Plan Status", "apply_plan_status"),
            ("Product ID", "product_id"),
            ("Product Title", "product_title"),
            ("Entry Count", "entry_count"),
            ("Skipped Count", "skipped_count"),
            ("Target Locales", "target_locales"),
            ("Requested Fields", "requested_fields"),
            ("Source Draft Status", "source_draft_status"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("translationsRegister Called", "translations_register_called"),
            ("Publish Performed", "publish_performed"),
            ("Apply Performed", "apply_performed"),
            ("Rollback Performed", "rollback_performed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    entry_rows = "\n".join(_entry_row(entry) for entry in payload.get("apply_plan_entries", []))
    skipped_rows = "\n".join(_skipped_row(entry) for entry in payload.get("skipped_entries", []))
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Selected Product Translation Apply Plan</title></head>
<body>
  <h1>Selected Product Translation Apply Plan</h1>
  <p>Apply plan only. No Shopify write, mutation, translationsRegister, publish, apply, rollback, or existing translation overwrite was performed.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Apply Plan Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Source value</th><th>Proposed translation</th><th>Digest</th><th>Validation</th><th>SEO validation</th></tr></thead>
    <tbody>{entry_rows}</tbody>
  </table>
  <h2>Skipped Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Skip reason</th><th>Validation</th><th>SEO validation</th></tr></thead>
    <tbody>{skipped_rows}</tbody>
  </table>
</body>
</html>
"""


def _row(label, value):
    return f"<tr><th>{escape(str(label))}</th><td>{escape(str(value))}</td></tr>"


def _entry_row(entry):
    return (
        "<tr>"
        f"<td>{escape(str(entry.get('locale', '')))}</td>"
        f"<td>{escape(str(entry.get('field', '')))}</td>"
        f"<td>{escape(str(entry.get('source_value', '')))}</td>"
        f"<td>{escape(str(entry.get('proposed_translation', '')))}</td>"
        f"<td>{escape(str(entry.get('digest', '')))}</td>"
        f"<td>{escape(str(entry.get('validation_status', '')))}</td>"
        f"<td>{escape(str(entry.get('seo_validation_status', '')))}</td>"
        "</tr>"
    )


def _skipped_row(entry):
    return (
        "<tr>"
        f"<td>{escape(str(entry.get('locale', '')))}</td>"
        f"<td>{escape(str(entry.get('field', '')))}</td>"
        f"<td>{escape(str(entry.get('skip_reason', '')))}</td>"
        f"<td>{escape(str(entry.get('validation_status', '')))}</td>"
        f"<td>{escape(str(entry.get('seo_validation_status', '')))}</td>"
        "</tr>"
    )


def _utc_now():
    return datetime.now(timezone.utc).isoformat()
