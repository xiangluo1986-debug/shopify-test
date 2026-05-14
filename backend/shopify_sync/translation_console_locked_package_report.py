import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path


REPORT_DIR = Path("logs")
REPORT_PREFIX = "translation_console_locked_package_dry_run"
REPORT_GLOB = f"{REPORT_PREFIX}_*.json"
REPORT_DIR_CANDIDATES = [REPORT_DIR, Path("backend/logs"), Path("/app/logs")]
FALSE_SAFETY_FLAGS = [
    "shopify_api_call_performed",
    "shopify_write_performed",
    "mutation_performed",
    "translations_register_called",
    "rollback_performed",
    "publish_performed",
    "apply_performed",
    "gmail_api_call_performed",
    "email_sent",
]


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


def load_latest_translation_console_locked_package_report(
    selected_product_gid: str = "",
    preferred_json_path: str = "",
) -> dict:
    loaded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    json_path = _resolve_locked_report_path(preferred_json_path)
    if not json_path:
        return _empty_approval_checklist(
            "locked_package_report_missing",
            selected_product_gid,
            loaded_at,
        )
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result = _empty_approval_checklist(
            "locked_package_report_read_failed",
            selected_product_gid,
            loaded_at,
        )
        result["read_error"] = f"{exc.__class__.__name__}: {exc}"
        result["json_report_path"] = _display_path(json_path)
        return result
    if not isinstance(payload, dict):
        result = _empty_approval_checklist(
            "locked_package_report_not_json_object",
            selected_product_gid,
            loaded_at,
        )
        result["json_report_path"] = _display_path(json_path)
        return result
    return build_locked_report_approval_checklist(
        payload=payload,
        json_path=json_path,
        selected_product_gid=selected_product_gid,
        loaded_at=loaded_at,
    )


def build_locked_report_approval_checklist(
    payload: dict,
    json_path: Path | None = None,
    selected_product_gid: str = "",
    loaded_at: str = "",
) -> dict:
    payload = payload or {}
    loaded_at = loaded_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report_product_gid = str(payload.get("product_gid") or "").strip()
    selected_product_gid = (selected_product_gid or "").strip()
    entry_count = _safe_int(payload.get("entry_count"))
    candidate_entries = [
        _approval_entry(entry) for entry in (payload.get("candidate_entries") or [])
        if isinstance(entry, dict)
    ]
    blocked_count = _safe_int(payload.get("blocked_or_needs_review_count"))
    missing_safety_flags = [
        flag for flag in FALSE_SAFETY_FLAGS if payload.get(flag) is not False
    ]
    safety_flags = {flag: bool(payload.get(flag)) for flag in FALSE_SAFETY_FLAGS}
    safety_flags_all_false = not any(safety_flags.values())
    checklist_items = [
        _check_item(
            "Report status is ready",
            payload.get("report_status")
            == "translation_console_locked_package_dry_run_ready",
        ),
        _check_item("Entry count is greater than zero", entry_count > 0),
        _check_item(
            "Product gid matches selected product",
            bool(selected_product_gid)
            and bool(report_product_gid)
            and selected_product_gid == report_product_gid,
        ),
        _check_item(
            "All performed safety flags are false",
            safety_flags_all_false and not missing_safety_flags,
        ),
        _check_item("No Shopify write was performed", not safety_flags["shopify_write_performed"]),
        _check_item("No mutation was performed", not safety_flags["mutation_performed"]),
        _check_item(
            "Translation registration API was not called",
            not safety_flags["translations_register_called"],
        ),
        _check_item("Rollback was not performed", not safety_flags["rollback_performed"]),
        _check_item(
            "Mail delivery was not used",
            not safety_flags["gmail_api_call_performed"] and not safety_flags["email_sent"],
        ),
        _check_item("Report is dry-run only", payload.get("dry_run_only") is True),
        _check_item(
            "Real writes still require explicit ACK and remote approval runner",
            True,
        ),
    ]
    warnings = []
    if selected_product_gid and report_product_gid and selected_product_gid != report_product_gid:
        warnings.append("selected_product_mismatch")
    if not safety_flags_all_false:
        warnings.append("safety_flag_not_false")
    if missing_safety_flags:
        warnings.append("missing_or_nonfalse_safety_flags")
    if entry_count <= 0:
        warnings.append("entry_count_zero")
    if payload.get("report_status") != "translation_console_locked_package_dry_run_ready":
        warnings.append("report_status_not_ready")

    safe_for_manual_review = all(item["passed"] for item in checklist_items)
    html_path = _matching_html_path(json_path)
    return {
        "checklist_status": (
            "locked_report_approval_checklist_ready"
            if safe_for_manual_review
            else "locked_report_approval_checklist_needs_review"
        ),
        "report_available": True,
        "report_status": payload.get("report_status", ""),
        "product_gid": report_product_gid,
        "selected_product_gid": selected_product_gid,
        "generated_at": payload.get("generated_at", ""),
        "loaded_at": loaded_at,
        "entry_count": entry_count,
        "candidate_entries_count": len(candidate_entries),
        "blocked_or_needs_review_count": blocked_count,
        "json_report_path": _display_path(json_path),
        "html_report_path": _display_path(html_path),
        "report_freshness": "latest_loaded_from_local_logs",
        "safe_for_manual_review": safe_for_manual_review,
        "safety_flags": safety_flags,
        "missing_safety_flags": missing_safety_flags,
        "safety_flags_all_false": safety_flags_all_false,
        "checklist_items": checklist_items,
        "candidate_entries": candidate_entries,
        "warnings": warnings,
        "read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
    }


def _empty_approval_checklist(reason: str, selected_product_gid: str, loaded_at: str) -> dict:
    return {
        "checklist_status": "locked_report_approval_checklist_empty",
        "report_available": False,
        "report_status": "",
        "product_gid": "",
        "selected_product_gid": selected_product_gid,
        "generated_at": "",
        "loaded_at": loaded_at,
        "entry_count": 0,
        "candidate_entries_count": 0,
        "blocked_or_needs_review_count": 0,
        "json_report_path": "",
        "html_report_path": "",
        "report_freshness": "",
        "safe_for_manual_review": False,
        "safety_flags": {flag: False for flag in FALSE_SAFETY_FLAGS},
        "missing_safety_flags": [],
        "safety_flags_all_false": True,
        "checklist_items": [
            _check_item("Generate locked package dry-run report first", False)
        ],
        "candidate_entries": [],
        "warnings": [reason],
        "read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
    }


def _resolve_locked_report_path(preferred_json_path: str = "") -> Path | None:
    candidates = []
    preferred = Path(str(preferred_json_path or "").strip()) if preferred_json_path else None
    if preferred:
        candidates.append(preferred)
    for report_dir in REPORT_DIR_CANDIDATES:
        if not report_dir.exists():
            continue
        candidates.extend(
            sorted(
                report_dir.glob(REPORT_GLOB),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        )
    for path in _unique_paths(candidates):
        if path.exists() and path.is_file():
            return path
    return None


def _approval_entry(entry: dict) -> dict:
    planned_value = str(entry.get("planned_value") or entry.get("proposed_translation") or "")
    return {
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "resource_key": entry.get("resource_key", ""),
        "planned_value_preview": _preview_text(planned_value),
        "chars": entry.get("chars") or entry.get("proposed_value_chars") or len(planned_value),
        "seo_status": entry.get("seo_status", ""),
        "validation_status": entry.get("validation_status", ""),
        "digest": entry.get("digest", ""),
        "would_write": entry.get("would_write"),
        "dry_run_only": entry.get("dry_run_only"),
        "source_preview": _preview_text(entry.get("source_preview", "")),
    }


def _check_item(label: str, passed: bool) -> dict:
    return {"label": label, "passed": bool(passed)}


def _safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _matching_html_path(json_path: Path | None) -> Path | None:
    if not json_path:
        return None
    html_path = json_path.with_suffix(".html")
    return html_path if html_path.exists() else None


def _display_path(path: Path | None) -> str:
    if not path:
        return ""
    if not path.is_absolute():
        return path.as_posix()
    for root in _unique_paths([Path.cwd(), Path.cwd().parent]):
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            continue
    return path.name


def _unique_paths(paths) -> list[Path]:
    seen = set()
    unique = []
    for path in paths:
        resolved = str(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def _preview_text(value, max_chars: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


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
