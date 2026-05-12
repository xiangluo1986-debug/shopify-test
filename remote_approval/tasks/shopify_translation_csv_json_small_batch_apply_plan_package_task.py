import csv
import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_translation_csv_json_small_batch_apply_plan_package"
COMMAND_LABEL = "shopify_translation_csv_json_small_batch_apply_plan_package"
INPUT_DIR = PROJECT_ROOT / "remote_approval" / "inputs"
CSV_INPUT_PATH = INPUT_DIR / "shopify_translation_small_batch_input.csv"
JSON_INPUT_PATH = INPUT_DIR / "shopify_translation_small_batch_input.json"
CSV_JSON_SMALL_BATCH_APPLY_PLAN_JSON_PATH = (
    LOG_DIR / "shopify_translation_csv_json_small_batch_apply_plan_package.json"
)
CSV_JSON_SMALL_BATCH_APPLY_PLAN_HTML_PATH = (
    LOG_DIR / "shopify_translation_csv_json_small_batch_apply_plan_package.html"
)

REQUIRED_FIELDS = ["product_id", "locale", "field", "proposed_value"]
ALLOWED_FIELDS = ["meta_title", "meta_description"]
FIELD_MAX_CHARS = {
    "meta_title": 60,
    "meta_description": 160,
}
MAX_ENTRIES = 5
SUPPORTED_LOCALE = "ja"
PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/\d+$")


def run_shopify_translation_csv_json_small_batch_apply_plan_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_errors = []
    input_source, input_path = _select_input_file()
    raw_entries = []

    if not input_path:
        validation_errors.append("missing_input_file")
    else:
        try:
            raw_entries = _load_input_entries(input_source, input_path)
        except ValueError as exc:
            parse_errors.append(str(exc))
            validation_errors.append("invalid_input_format")
        except (OSError, json.JSONDecodeError, csv.Error) as exc:
            parse_errors.append(f"Could not parse {input_source} input file: {exc}")
            validation_errors.append("invalid_input_format")

    if raw_entries:
        validation_errors.extend(_validate_raw_entries(raw_entries))
    elif input_path and "invalid_input_format" not in validation_errors:
        validation_errors.append("empty_input_entries")

    entries = _validated_entries(raw_entries)
    blocking_conditions = _blocking_conditions(validation_errors)
    plan_status = _plan_status(blocking_conditions)
    success = plan_status == "csv_json_small_batch_apply_plan_ready_for_manual_review"
    product_id = _single_value([entry.get("product_id", "") for entry in entries])
    locale = _single_value([entry.get("locale", "") for entry in entries])
    end_time = utc_now_iso()

    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "csv-json-small-batch-apply-plan-package-only",
        "command_label": COMMAND_LABEL,
        "csv_input_path": str(CSV_INPUT_PATH),
        "json_input_path": str(JSON_INPUT_PATH),
        "input_source": input_source,
        "input_path": str(input_path) if input_path else "",
        "json_csv_json_small_batch_apply_plan_package_path": str(CSV_JSON_SMALL_BATCH_APPLY_PLAN_JSON_PATH),
        "html_csv_json_small_batch_apply_plan_package_path": str(CSV_JSON_SMALL_BATCH_APPLY_PLAN_HTML_PATH),
        "success": success,
        "plan_status": plan_status,
        "product_id": product_id,
        "locale": locale,
        "entry_count": len(entries),
        "allowed_fields": ALLOWED_FIELDS,
        "max_entries": MAX_ENTRIES,
        "max_products": 1,
        "max_locales": 1,
        "entries": entries,
        "manual_review_required": True,
        "real_write_allowed": False,
        "next_step_requires_separate_execute_task": True,
        "input_selection_summary": _input_selection_summary(input_source, input_path),
        "plan_constraints": _plan_constraints(),
        "manual_review_checklist": _manual_review_checklist(),
        "forbidden_actions": _forbidden_actions(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(),
        "plan_package_only": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "publish_performed": False,
        "bulk_write_performed": False,
        "real_apply_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures": _unique(validation_errors),
        "parse_errors": parse_errors,
        "detected_issue_summary": _issue_summary(plan_status, blocking_conditions),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
    }
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return {
        "task_type": TASK_NAME,
        "success": success,
        "exit_code": 0 if success else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_csv_json_small_batch_apply_plan_package_path": str(json_path),
        "html_csv_json_small_batch_apply_plan_package_path": str(html_path),
        "plan_status": plan_status,
        "input_source": input_source,
        "input_path": str(input_path) if input_path else "",
        "product_id": product_id,
        "locale": locale,
        "entry_count": len(entries),
        "allowed_fields": ALLOWED_FIELDS,
        "manual_review_required": True,
        "real_write_allowed": False,
        "next_step_requires_separate_execute_task": True,
        "plan_package_only": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "publish_performed": False,
        "bulk_write_performed": False,
        "real_apply_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures_count": len(payload["validation_failures"]),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _select_input_file() -> tuple[str, Path | None]:
    if JSON_INPUT_PATH.exists():
        return "json", JSON_INPUT_PATH
    if CSV_INPUT_PATH.exists():
        return "csv", CSV_INPUT_PATH
    return "missing", None


def _load_input_entries(input_source: str, input_path: Path) -> list[dict]:
    if input_source == "json":
        data = json.loads(input_path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list):
            raise ValueError("JSON input must be a list of objects.")
        entries = []
        for index, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"JSON entry {index} is not an object.")
            entries.append(
                {
                    "entry_index": index,
                    "row_number": index,
                    **{field: _clean_value(item.get(field)) for field in REQUIRED_FIELDS},
                }
            )
        return entries

    with input_path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        if not reader.fieldnames:
            raise ValueError("CSV input is missing a header row.")
        normalized_headers = {header.strip() for header in reader.fieldnames if header}
        if any(field not in normalized_headers for field in REQUIRED_FIELDS):
            missing = [field for field in REQUIRED_FIELDS if field not in normalized_headers]
            raise ValueError(f"CSV input missing required columns: {', '.join(missing)}")
        entries = []
        for index, row in enumerate(reader, start=1):
            entries.append(
                {
                    "entry_index": index,
                    "row_number": index + 1,
                    **{field: _clean_value(row.get(field)) for field in REQUIRED_FIELDS},
                }
            )
        return entries


def _clean_value(value) -> str:
    return str(value or "").strip()


def _validate_raw_entries(entries: list[dict]) -> list[str]:
    errors = []
    if not entries:
        errors.append("empty_input_entries")
    if len(entries) > MAX_ENTRIES:
        errors.append("too_many_entries")

    product_ids = {entry.get("product_id") for entry in entries if entry.get("product_id")}
    locales = {entry.get("locale") for entry in entries if entry.get("locale")}
    if len(product_ids) > 1:
        errors.append("multiple_products")
    if len(locales) > 1:
        errors.append("multiple_locales")

    for entry in entries:
        if _missing_required_field(entry):
            errors.append("missing_required_field")
            continue
        product_id = entry["product_id"]
        locale = entry["locale"]
        field = entry["field"]
        proposed_value = entry["proposed_value"]
        if not PRODUCT_GID_RE.match(product_id):
            errors.append("invalid_product_gid")
        if locale != SUPPORTED_LOCALE:
            errors.append("unsupported_locale_for_phase_14_0")
        if field not in ALLOWED_FIELDS:
            errors.append("invalid_field")
        if not proposed_value:
            errors.append("empty_proposed_value")
        max_chars = FIELD_MAX_CHARS.get(field)
        if max_chars is not None and len(proposed_value) > max_chars:
            errors.append("value_too_long")
    return _unique(errors)


def _missing_required_field(entry: dict) -> bool:
    return any(not entry.get(field) for field in REQUIRED_FIELDS)


def _validated_entries(entries: list[dict]) -> list[dict]:
    validated_entries = []
    for index, entry in enumerate(entries, start=1):
        field = entry.get("field", "")
        proposed_value = entry.get("proposed_value", "")
        max_chars = FIELD_MAX_CHARS.get(field, 0)
        field_allowed = field in ALLOWED_FIELDS
        value_non_empty = bool(proposed_value)
        value_length_allowed = bool(max_chars and len(proposed_value) <= max_chars)
        product_gid_valid = bool(PRODUCT_GID_RE.match(entry.get("product_id", "")))
        locale_supported = entry.get("locale") == SUPPORTED_LOCALE
        validation_status = "valid"
        if _missing_required_field(entry):
            validation_status = "invalid_missing_required_field"
        elif not product_gid_valid:
            validation_status = "invalid_product_gid"
        elif not locale_supported:
            validation_status = "invalid_locale"
        elif not field_allowed:
            validation_status = "invalid_field"
        elif not value_non_empty:
            validation_status = "empty_proposed_value"
        elif not value_length_allowed:
            validation_status = "value_too_long"
        validated_entries.append(
            {
                "entry_index": int(entry.get("entry_index") or index),
                "row_number": int(entry.get("row_number") or index),
                "product_id": entry.get("product_id", ""),
                "locale": entry.get("locale", ""),
                "field": field,
                "proposed_value": proposed_value,
                "proposed_value_chars": len(proposed_value),
                "max_chars": max_chars,
                "field_allowed": field_allowed,
                "product_gid_valid": product_gid_valid,
                "locale_supported": locale_supported,
                "value_non_empty": value_non_empty,
                "value_length_allowed": value_length_allowed,
                "validation_status": validation_status,
            }
        )
    return validated_entries


def _single_value(values: list[str]) -> str:
    unique_values = _unique([value for value in values if value])
    return unique_values[0] if len(unique_values) == 1 else ""


def _blocking_conditions(validation_errors: list[str]) -> list[str]:
    mapping = {
        "missing_input_file": "blocked_missing_input_file",
        "invalid_input_format": "blocked_invalid_input_format",
        "missing_required_field": "blocked_missing_required_field",
        "empty_input_entries": "blocked_empty_input_entries",
        "too_many_entries": "blocked_too_many_entries",
        "multiple_products": "blocked_multiple_products",
        "multiple_locales": "blocked_multiple_locales",
        "invalid_field": "blocked_invalid_field",
        "empty_proposed_value": "blocked_empty_proposed_value",
        "value_too_long": "blocked_value_too_long",
        "invalid_product_gid": "blocked_invalid_product_gid",
        "unsupported_locale_for_phase_14_0": "blocked_unsupported_locale_for_phase_14_0",
    }
    return _unique([mapping.get(error, error) for error in validation_errors])


def _plan_status(blocking_conditions: list[str]) -> str:
    if not blocking_conditions:
        return "csv_json_small_batch_apply_plan_ready_for_manual_review"
    for status in [
        "blocked_missing_input_file",
        "blocked_invalid_input_format",
        "blocked_missing_required_field",
        "blocked_empty_input_entries",
        "blocked_too_many_entries",
        "blocked_multiple_products",
        "blocked_multiple_locales",
        "blocked_invalid_field",
        "blocked_empty_proposed_value",
        "blocked_value_too_long",
        "blocked_invalid_product_gid",
        "blocked_unsupported_locale_for_phase_14_0",
    ]:
        if status in blocking_conditions:
            return status
    return "csv_json_small_batch_apply_plan_blocked"


def _input_selection_summary(input_source: str, input_path: Path | None) -> dict:
    return {
        "json_input_exists": JSON_INPUT_PATH.exists(),
        "csv_input_exists": CSV_INPUT_PATH.exists(),
        "input_source": input_source,
        "input_path": str(input_path) if input_path else "",
        "json_preferred_when_both_exist": True,
    }


def _plan_constraints() -> dict:
    return {
        "max_entries": MAX_ENTRIES,
        "max_products": 1,
        "max_locales": 1,
        "supported_locale_for_phase_14_0": SUPPORTED_LOCALE,
        "allowed_fields": ALLOWED_FIELDS,
        "field_max_chars": FIELD_MAX_CHARS,
        "disallowed_fields": [
            "title",
            "body_html",
            "description",
            "handle",
            "tags",
            "image alt",
            "variants",
            "collections",
            "price",
            "inventory",
            "publish",
            "any non-translation field",
        ],
        "batch_mode_allowed": False,
        "full_store_scan_allowed": False,
    }


def _manual_review_checklist() -> list[str]:
    return [
        "Confirm the selected input file is intentional.",
        "Confirm exactly one Shopify product ID is present.",
        "Confirm the locale is ja.",
        "Confirm all fields are meta_title or meta_description.",
        "Confirm meta_title values are <= 60 characters.",
        "Confirm meta_description values are <= 160 characters.",
        "Confirm every proposed value is accurate and non-empty.",
        "Confirm a separate execute task is required before any Shopify write.",
    ]


def _forbidden_actions() -> list[str]:
    return [
        "Shopify API call in this phase",
        "Shopify write in this phase",
        "mutation in this phase",
        "translationsRegister in this phase",
        "readback in this phase",
        "rollback in this phase",
        "publish in this phase",
        "real apply in this phase",
        "batch execution",
        "full-store scan",
        "multiple products",
        "multiple locales",
        "unsupported fields",
        "git push",
    ]


def _safety_summary() -> dict:
    return {
        "plan_package_only": True,
        "manual_review_required": True,
        "real_write_allowed": False,
        "next_step_requires_separate_execute_task": True,
        "shopify_api_call_allowed": False,
        "shopify_write_allowed": False,
        "mutation_allowed": False,
        "translations_register_allowed": False,
        "readback_allowed": False,
        "rollback_allowed": False,
        "publish_allowed": False,
        "bulk_write_allowed": False,
        "real_apply_allowed": False,
        "max_entries": MAX_ENTRIES,
        "max_products": 1,
        "max_locales": 1,
        "allowed_fields": ALLOWED_FIELDS,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    CSV_JSON_SMALL_BATCH_APPLY_PLAN_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(CSV_JSON_SMALL_BATCH_APPLY_PLAN_JSON_PATH.read_text(encoding="utf-8"))
    return CSV_JSON_SMALL_BATCH_APPLY_PLAN_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    CSV_JSON_SMALL_BATCH_APPLY_PLAN_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return CSV_JSON_SMALL_BATCH_APPLY_PLAN_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Plan Status", "plan_status"),
            ("Input Source", "input_source"),
            ("Input Path", "input_path"),
            ("Product ID", "product_id"),
            ("Locale", "locale"),
            ("Entry Count", "entry_count"),
            ("Allowed Fields", "allowed_fields"),
            ("Manual Review Required", "manual_review_required"),
            ("Real Write Allowed", "real_write_allowed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Entries", payload.get("entries", [])),
            ("Input Selection Summary", payload.get("input_selection_summary", {})),
            ("Plan Constraints", payload.get("plan_constraints", {})),
            ("Manual Review Checklist", payload.get("manual_review_checklist", [])),
            ("Forbidden Actions", payload.get("forbidden_actions", [])),
            ("Safety Summary", payload.get("safety_summary", {})),
            ("Validation Failures", payload.get("validation_failures", [])),
            ("Parse Errors", payload.get("parse_errors", [])),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify CSV/JSON Small Batch Apply Plan Package</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; background: #fff; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f6f8fa; width: 320px; }}
    .status {{ padding: 12px 14px; border-radius: 6px; font-weight: 700; margin: 12px 0; }}
    .status.pass {{ background: #dafbe1; color: #116329; }}
    .status.fail {{ background: #ffebe9; color: #82071e; }}
  </style>
</head>
<body>
  <h1>Shopify CSV/JSON Small Batch Apply Plan Package</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Plan Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local CSV/JSON input only.</li>
    <li>No Shopify API call, write, mutation, translationsRegister, readback, rollback, publish, bulk write, or apply was performed.</li>
    <li>Any future execution requires a separate execute task and human approval.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(plan_status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "CSV/JSON small batch apply plan blocked: " + ", ".join(blocking_conditions)
    return f"CSV/JSON small batch apply plan generated with status {plan_status}. No Shopify action performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify CSV/JSON small batch apply plan package generated.\n"
        f"Plan status: {payload.get('plan_status')}\n"
        f"Input source: {payload.get('input_source')}\n"
        f"Input path: {payload.get('input_path')}\n"
        f"Product ID: {payload.get('product_id')}\n"
        f"Locale: {payload.get('locale')}\n"
        f"Entry count: {payload.get('entry_count')}\n"
        f"Allowed fields: {payload.get('allowed_fields')}\n"
        f"No new Shopify writes performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "CSV/JSON small batch apply plan JSON:\n"
        f"{json_path}\n\n"
        "CSV/JSON small batch apply plan HTML:\n"
        f"{html_path}\n"
        "Plan package only. No Shopify API call, mutation, translationsRegister, readback, rollback, publish, bulk write, apply, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep CSV/JSON small batch apply plan files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Do not push from this task."
    )


def _unique(values: list[str]) -> list[str]:
    unique_values = []
    for value in values:
        if value and value not in unique_values:
            unique_values.append(value)
    return unique_values
