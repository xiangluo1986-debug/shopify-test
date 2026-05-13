import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path


FINAL_REVIEW_JSON_PATH = Path("logs/shopify_translation_selected_product_final_review_package.json")
FINAL_REVIEW_HTML_PATH = Path("logs/shopify_translation_selected_product_final_review_package.html")
READY_APPLY_PLAN_STATUS = "selected_product_translation_apply_plan_ready_for_manual_review"
ALLOWED_FIELDS = {"title", "meta_title", "meta_description"}


def build_selected_product_translation_final_review(apply_plan_result, write_reports=True):
    apply_plan_result = dict(apply_plan_result or {})
    payload = _empty_final_review(apply_plan_result)
    if not apply_plan_result:
        payload["final_review_status"] = "blocked_missing_apply_plan"
        payload["blocking_conditions"].append("blocked_missing_apply_plan")
    elif apply_plan_result.get("apply_plan_status") != READY_APPLY_PLAN_STATUS:
        payload["final_review_status"] = "blocked_apply_plan_not_ready"
        payload["blocking_conditions"].append("blocked_apply_plan_not_ready")
    else:
        _collect_final_entries(payload, apply_plan_result)
        _collect_skipped_summary(payload, apply_plan_result)
        if payload["entry_count"] == 0:
            payload["final_review_status"] = "blocked_no_final_review_entries"
            payload["blocking_conditions"].append("blocked_no_final_review_entries")
        elif payload["rejected_count"]:
            payload["final_review_status"] = "final_review_blocked_by_entry_risks"
            payload["blocking_conditions"].append("final_review_blocked_by_entry_risks")
        else:
            payload["final_review_status"] = "selected_product_translation_final_review_ready_for_manual_approval"
            payload["success"] = True

    payload["timestamp"] = _utc_now()
    payload["generated_at"] = payload["timestamp"]
    payload["final_review_report_path"] = str(FINAL_REVIEW_JSON_PATH)
    payload["json_selected_product_final_review_package_path"] = str(FINAL_REVIEW_JSON_PATH)
    payload["html_selected_product_final_review_package_path"] = str(FINAL_REVIEW_HTML_PATH)

    if write_reports:
        _write_reports(payload)
    return payload


def _empty_final_review(apply_plan_result):
    return {
        "success": False,
        "final_review_status": "",
        "final_review_only": True,
        "apply_plan_only": True,
        "product_id": apply_plan_result.get("product_id", ""),
        "product_title": apply_plan_result.get("product_title", ""),
        "entry_count": 0,
        "skipped_count": int(apply_plan_result.get("skipped_count") or 0),
        "rejected_count": 0,
        "target_locales": list(apply_plan_result.get("target_locales") or []),
        "requested_fields": list(apply_plan_result.get("requested_fields") or []),
        "apply_plan_status": apply_plan_result.get("apply_plan_status", ""),
        "apply_plan_report_path": apply_plan_result.get(
            "json_selected_product_apply_plan_package_path",
            "logs/shopify_translation_selected_product_apply_plan_package.json",
        ),
        "final_review_report_path": str(FINAL_REVIEW_JSON_PATH),
        "final_review_entries": [],
        "skipped_entries": list(apply_plan_result.get("skipped_entries") or []),
        "skipped_rejected_summary": _empty_skipped_summary(),
        "blocking_conditions": [],
        "manual_review_required": True,
        "manual_ack_required_for_future_write": True,
        "future_write_requires_separate_phase": True,
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
        "safety_summary": {
            "final_review_only": True,
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
            "manual_ack_required_for_future_write": True,
        },
    }


def _collect_final_entries(payload, apply_plan_result):
    for entry in apply_plan_result.get("apply_plan_entries", []):
        final_entry = _final_entry(entry)
        payload["final_review_entries"].append(final_entry)
        if final_entry["risk_flags"]:
            payload["rejected_count"] += 1
            _increment_rejected_summary(payload["skipped_rejected_summary"], final_entry["risk_flags"])
    payload["entry_count"] = len(payload["final_review_entries"])


def _final_entry(entry):
    risk_flags = _risk_flags(entry)
    return {
        "product_id": entry.get("product_id", ""),
        "product_title": entry.get("product_title", ""),
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "source_value": entry.get("source_value", ""),
        "proposed_translation": entry.get("proposed_translation") or entry.get("proposed_value", ""),
        "digest": entry.get("digest") or entry.get("source_digest", ""),
        "current_translation_state": entry.get("current_translation_state", {}),
        "validation_status": entry.get("validation_status", ""),
        "seo_validation_status": entry.get("seo_validation_status", ""),
        "risk_flags": risk_flags,
        "final_review_status": "ready_for_final_manual_review" if not risk_flags else "rejected_by_final_review_gate",
        "manual_review_required": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
    }


def _risk_flags(entry):
    flags = []
    field = entry.get("field", "")
    state = entry.get("current_translation_state") or {}
    if field not in ALLOWED_FIELDS:
        flags.append("unsupported_field")
    if not str(entry.get("digest") or entry.get("source_digest") or "").strip():
        flags.append("missing_digest")
    if not str(entry.get("proposed_translation") or entry.get("proposed_value") or "").strip():
        flags.append("missing_value")
    if state.get("existing_translation_present"):
        flags.append("already_translated")
    if state.get("existing_translation_outdated") is True:
        flags.append("outdated_translation")
    if entry.get("validation_status") != "draft_ready_for_manual_review":
        flags.append("draft_needs_manual_review")
    if entry.get("seo_validation_status") != "seo_ready":
        flags.append("seo_needs_manual_review")
    return _unique(flags)


def _collect_skipped_summary(payload, apply_plan_result):
    summary = payload["skipped_rejected_summary"]
    for entry in apply_plan_result.get("skipped_entries", []):
        reason = entry.get("skip_reason") or "not_eligible_for_apply_plan"
        if reason == "already_translated":
            summary["already_translated"] += 1
        elif reason == "existing_translation_outdated_manual_review_required":
            summary["outdated_translation"] += 1
        elif reason == "draft_not_ready_for_manual_review":
            summary["draft_needs_manual_review"] += 1
        elif reason == "seo_not_ready_for_apply_plan":
            summary["seo_needs_manual_review"] += 1
        elif reason in summary:
            summary[reason] += 1
        else:
            summary["not_eligible_for_apply_plan"] += 1


def _increment_rejected_summary(summary, risk_flags):
    for flag in risk_flags:
        if flag in summary:
            summary[flag] += 1
        else:
            summary["not_eligible_for_apply_plan"] += 1


def _empty_skipped_summary():
    return {
        "already_translated": 0,
        "outdated_translation": 0,
        "draft_needs_manual_review": 0,
        "seo_needs_manual_review": 0,
        "missing_digest": 0,
        "missing_value": 0,
        "unsupported_field": 0,
        "not_eligible_for_apply_plan": 0,
    }


def _write_reports(payload):
    FINAL_REVIEW_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    FINAL_REVIEW_JSON_PATH.write_text(text, encoding="utf-8")
    FINAL_REVIEW_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")


def _render_html(payload):
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Final Review Status", "final_review_status"),
            ("Product ID", "product_id"),
            ("Product Title", "product_title"),
            ("Entry Count", "entry_count"),
            ("Skipped Count", "skipped_count"),
            ("Rejected Count", "rejected_count"),
            ("Target Locales", "target_locales"),
            ("Requested Fields", "requested_fields"),
            ("Apply Plan Report Path", "apply_plan_report_path"),
            ("Final Review Report Path", "final_review_report_path"),
            ("Blocking Conditions", "blocking_conditions"),
            ("Manual ACK Required For Future Write", "manual_ack_required_for_future_write"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("translationsRegister Called", "translations_register_called"),
            ("Publish Performed", "publish_performed"),
            ("Apply Performed", "apply_performed"),
            ("Rollback Performed", "rollback_performed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No Write Confirmed", "all_new_actions_no_write_confirmed"),
        ]
    )
    entry_rows = "\n".join(_entry_row(entry) for entry in payload.get("final_review_entries", []))
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Selected Product Translation Final Review</title></head>
<body>
  <h1>Selected Product Translation Final Review</h1>
  <p>This is the final no-write review gate. Real Shopify writes require a separate future phase and explicit manual ACK.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Skipped / Rejected Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{_row("Skipped / Rejected Summary", payload.get("skipped_rejected_summary", {}))}</tbody></table>
  <h2>Final Review Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Source value</th><th>Proposed translation</th><th>Digest</th><th>Risk flags</th><th>Final review status</th></tr></thead>
    <tbody>{entry_rows}</tbody>
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
        f"<td>{escape(str(entry.get('risk_flags', [])))}</td>"
        f"<td>{escape(str(entry.get('final_review_status', '')))}</td>"
        "</tr>"
    )


def _unique(values):
    output = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output


def _utc_now():
    return datetime.now(timezone.utc).isoformat()
