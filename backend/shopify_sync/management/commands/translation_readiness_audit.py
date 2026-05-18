import json
import argparse
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path

try:
    from django.core.management.base import BaseCommand
except ModuleNotFoundError:
    BaseCommand = object


CODE_ROOT = None
WORKSPACE_ROOT = None
EXPECTED_LOCALES = ("ja", "de", "fr", "es", "it")
LONG_BODY_HTML_CHARS = 3000
MEDIA_ALT_DISABLED_REASONS = {
    "Media alt text update is not enabled yet.",
    "Media alt text update is not enabled.",
}
TECHNICAL_METAFIELD_MARKERS = (
    "google",
    "google_product_category",
    "product_seo_template",
    "json",
    "schema",
    "system",
    "rating",
    "review",
    "reviews",
    "inventory",
    " id",
    "_id",
    "sku",
    "barcode",
    "gid://",
    "_gid",
    "token",
    "sync",
    "feed",
    "feeds",
    "internal",
    "technical",
    "wishlist",
    "count",
)
CUSTOMER_FACING_METAFIELD_MARKERS = (
    "benefit",
    "bullet",
    "compat",
    "compatibility",
    "description",
    "feature",
    "features",
    "highlight",
    "highlights",
    "included",
    "material",
    "model",
    "package",
    "package_included",
    "package included",
    "scale",
    "short_description",
    "size",
    "spec",
    "specification",
    "specifications",
    "subtitle",
    "summary",
)


def _code_root():
    global CODE_ROOT
    if CODE_ROOT is not None:
        return CODE_ROOT
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "manage.py").exists():
            CODE_ROOT = parent
            return CODE_ROOT
    CODE_ROOT = current.parents[3]
    return CODE_ROOT


def _workspace_root():
    global WORKSPACE_ROOT
    if WORKSPACE_ROOT is not None:
        return WORKSPACE_ROOT
    code_root = _code_root()
    if (code_root.parent / "backend" / "manage.py").exists():
        WORKSPACE_ROOT = code_root.parent
    else:
        WORKSPACE_ROOT = code_root
    return WORKSPACE_ROOT


def _workspace_report_dirs():
    workspace_root = _workspace_root()
    code_root = _code_root()
    return _unique_paths(
        [
            workspace_root / "backend" / "logs" / "shopify_translation_workspace_jobs",
            workspace_root / "logs" / "shopify_translation_workspace_jobs",
            code_root / "logs" / "shopify_translation_workspace_jobs",
        ]
    )


def _update_report_dirs():
    workspace_root = _workspace_root()
    code_root = _code_root()
    return _unique_paths(
        [
            workspace_root / "backend" / "logs" / "shopify_translation_real_write",
            workspace_root / "logs" / "shopify_translation_real_write",
            code_root / "logs" / "shopify_translation_real_write",
        ]
    )


def _default_output_root():
    return _workspace_root() / "logs" / "codex_runs"


def _unique_paths(paths):
    unique = []
    seen = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return tuple(unique)


class Command(BaseCommand):
    help = (
        "Run a local-only Translation Workspace readiness audit from existing "
        "workspace and update reports."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            default="",
            help=(
                "Optional output directory for the JSON/HTML audit. Defaults to a "
                "timestamped logs/codex_runs directory."
            ),
        )
        parser.add_argument(
            "--sample-limit",
            type=int,
            default=6,
            help="Maximum representative products to include after required roles.",
        )

    def handle(self, *args, **options):
        payload = run_audit(
            output_dir=options.get("output_dir"),
            sample_limit=max(1, int(options.get("sample_limit") or 6)),
        )
        _print_summary(payload, self.stdout.write)


def run_audit(*, output_dir="", sample_limit=6):
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    workspace_reports = _latest_workspace_reports_by_product()
    update_reports = _latest_update_reports_by_product()
    product_facts = _product_facts(workspace_reports, update_reports)
    selected_products, role_map = _select_sample_products(
        product_facts,
        sample_limit=max(1, int(sample_limit or 6)),
    )
    product_audits = [
        _audit_product(product_gid, product_facts[product_gid], role_map.get(product_gid, []))
        for product_gid in selected_products
    ]
    media_rows = [
        row
        for product in product_audits
        for row in product.get("media_alt_mapping_result", {}).get("rows", [])
    ]
    variant_rows = [
        row
        for product in product_audits
        for row in product.get("variant_rows", [])
    ]
    metafield_rows = [
        row
        for product in product_audits
        for row in product.get("metafield_rows", [])
    ]
    media_summary = _media_alt_summary(media_rows)
    variant_metafield_summary = _variant_metafield_summary(variant_rows, metafield_rows)
    payload = {
        "audit_name": "translation_readiness_audit",
        "audit_status": "completed",
        "generated_at": generated_at,
        "report_source": "local_workspace_and_update_reports_only",
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
        "command_executed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "workspace_report_count": len(workspace_reports),
        "update_report_count": len(update_reports),
        "sampled_product_count": len(product_audits),
        "sampled_products": product_audits,
        "products_sample_types_audited": _sample_types_audited(product_audits),
        "existing_translation_workflow_readiness_summary": (
            _workflow_readiness_summary(product_audits)
        ),
        "media_alt_text_mapping_audit": media_summary,
        "variant_metafield_quick_audit": variant_metafield_summary,
    }
    payload["recommendation"] = _overall_recommendation(payload)
    report_dir = _output_dir(output_dir, generated_at)
    json_path = report_dir / "translation_readiness_audit.json"
    html_path = report_dir / "translation_readiness_audit.html"
    payload["json_report_path"] = _display_path(json_path)
    payload["html_report_path"] = _display_path(html_path)
    _write_reports(payload, json_path, html_path)
    return payload


def _print_summary(payload, write_line):
    write_line(f"Audit report: {payload.get('json_report_path', '')}")
    write_line(f"HTML report: {payload.get('html_report_path', '')}")
    write_line(
        "Products audited: "
        + ", ".join(
            product.get("product_gid", "")
            for product in payload.get("sampled_products", [])
        )
    )
    media_summary = payload.get("media_alt_text_mapping_audit") or {}
    write_line(
        "Media alt rows classified: "
        f"{media_summary.get('row_count', 0)}; "
        f"recommendation: {media_summary.get('recommendation', '')}"
    )
    variant_meta = payload.get("variant_metafield_quick_audit") or {}
    write_line(
        "Variants classified: "
        f"{variant_meta.get('variant_row_count', 0)}; "
        f"ready for next enablement: "
        f"{variant_meta.get('variant_ready_for_next_enablement_count', 0)}"
    )
    write_line(
        "Customer-facing metafields: "
        f"{variant_meta.get('customer_facing_metafield_ready_for_next_enablement_count', 0)} ready / "
        f"{variant_meta.get('customer_facing_metafield_blocked_count', 0)} blocked; "
        f"technical/internal: {variant_meta.get('technical_or_internal_metafield_count', 0)}"
    )


def _latest_workspace_reports_by_product():
    return _latest_reports_by_product(
        _workspace_report_dirs(),
        "translation_workspace_job_*.json",
    )


def _latest_update_reports_by_product():
    reports = _latest_reports_by_product(
        _update_report_dirs(),
        "translation_all_languages_update_*.json",
    )
    return {
        product_gid: report
        for product_gid, report in reports.items()
        if report.get("data", {}).get("action_name")
        in {"", "validate_and_update_all_languages_to_shopify"}
    }


def _latest_reports_by_product(report_dirs, pattern):
    candidates = []
    for report_dir in report_dirs:
        try:
            paths = list(report_dir.glob(pattern))
        except OSError:
            continue
        for path in paths:
            try:
                stat = path.stat()
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            product_gid = str(data.get("product_gid") or "").strip()
            if not product_gid:
                continue
            candidates.append(
                {
                    "path": path,
                    "mtime": stat.st_mtime,
                    "last_modified": datetime.fromtimestamp(
                        stat.st_mtime,
                        timezone.utc,
                    ).replace(microsecond=0).isoformat(),
                    "data": data,
                }
            )
    candidates.sort(key=lambda item: item["mtime"], reverse=True)
    latest = {}
    for item in candidates:
        product_gid = item["data"].get("product_gid")
        if product_gid not in latest:
            latest[product_gid] = item
    return latest


def _product_facts(workspace_reports, update_reports):
    facts = {}
    for product_gid, workspace in workspace_reports.items():
        update = update_reports.get(product_gid)
        rows = _rows(workspace.get("data", {}), "review_rows")
        entries = _rows((update or {}).get("data", {}), "entries")
        facts[product_gid] = {
            "product_gid": product_gid,
            "product_title": workspace.get("data", {}).get("product_title", "")
            or (update or {}).get("data", {}).get("product_title", ""),
            "workspace": workspace,
            "update": update,
            "review_rows": rows,
            "update_entries": entries,
            "row_count": len(rows),
            "option_count": _count_rows(rows, groups={"options"}),
            "media_count": _count_rows(rows, groups={"media", "media_alt_text"}, keys={"media.alt"}),
            "variant_count": _count_rows(rows, groups={"variants"}),
            "metafield_count": _count_rows(
                rows,
                groups={"metafields", "important_metafields", "technical_metafields"},
            ),
            "max_body_html_chars": _max_body_html_chars(rows),
            "workspace_mtime": workspace.get("mtime", 0),
            "update_exists": bool(update),
        }
    return facts


def _select_sample_products(product_facts, sample_limit):
    selected = []
    roles = {}

    def add(product_gid, role):
        if not product_gid:
            return
        roles.setdefault(product_gid, [])
        if role not in roles[product_gid]:
            roles[product_gid].append(role)
        if product_gid not in selected:
            selected.append(product_gid)

    facts = list(product_facts.values())
    if not facts:
        return [], {}
    facts_with_update = [item for item in facts if item.get("update_exists")]
    simple_pool = facts_with_update or facts
    simple = min(
        simple_pool,
        key=lambda item: (item.get("row_count", 0), item.get("media_count", 0)),
    )
    add(simple["product_gid"], "simple_product")
    option_pool = [item for item in facts if item.get("option_count", 0) > 0]
    if option_pool:
        add(
            max(
                option_pool,
                key=lambda item: (item.get("option_count", 0), item.get("update_exists", False)),
            )["product_gid"],
            "product_with_options",
        )
    media_pool = [item for item in facts if item.get("media_count", 0) > 0]
    if media_pool:
        add(
            max(
                media_pool,
                key=lambda item: (item.get("media_count", 0), item.get("update_exists", False)),
            )["product_gid"],
            "product_with_images_media_alt",
        )
    long_body_pool = [
        item for item in facts if item.get("max_body_html_chars", 0) >= LONG_BODY_HTML_CHARS
    ]
    if long_body_pool:
        add(
            max(
                long_body_pool,
                key=lambda item: (item.get("update_exists", False), item.get("max_body_html_chars", 0)),
            )["product_gid"],
            "product_with_long_body_html",
        )
    latest = max(facts, key=lambda item: item.get("workspace_mtime", 0))
    add(latest["product_gid"], "recently_seen_latest_local_report")

    for item in sorted(
        facts,
        key=lambda fact: (
            fact.get("update_exists", False),
            fact.get("workspace_mtime", 0),
        ),
        reverse=True,
    ):
        if len(selected) >= sample_limit:
            break
        add(item["product_gid"], "additional_recent_update_sample")
    return selected[:sample_limit], roles


def _audit_product(product_gid, fact, roles):
    workspace = fact.get("workspace") or {}
    update = fact.get("update") or {}
    rows = fact.get("review_rows") or []
    entries = fact.get("update_entries") or []
    media_source_rows = entries if entries else rows
    variant_rows = _variant_rows(entries or rows, product_gid)
    metafield_rows = _metafield_rows(entries or rows, product_gid)
    return {
        "sample_types": roles,
        "product_gid": product_gid,
        "product_title": fact.get("product_title", ""),
        "latest_translation_report_exists": bool(workspace),
        "latest_translation_report_path": _display_path(workspace.get("path")),
        "latest_translation_report_updated_at": workspace.get("last_modified", ""),
        "five_languages_status": _five_language_status(rows),
        "translated_count": _translated_count(rows),
        "needs_review_count": _needs_review_count(rows),
        "skipped_count": _skipped_count(rows),
        "latest_shopify_update_report_exists": bool(update),
        "latest_shopify_update_report_path": _display_path(update.get("path")),
        "latest_shopify_update_report_updated_at": update.get("last_modified", ""),
        "updated_count": _int_from_report(update, "updated_count", entries, "written_verified", "readback_mismatch"),
        "verified_count": _int_from_report(update, "verified_count", entries, "written_verified"),
        "rollback_needed": bool((update.get("data") or {}).get("rollback_needed")),
        "not_updated_count": _not_updated_count(update.get("data") or {}, entries),
        "top_not_updated_reasons": _top_not_updated_reasons(entries),
        "body_html_validation_result": _body_html_result(entries or rows),
        "options_mapping_result": _option_mapping_result(update.get("data") or {}, entries or rows),
        "media_alt_mapping_result": _media_alt_mapping_result(media_source_rows, product_gid),
        "variant_rows": variant_rows,
        "metafield_rows": metafield_rows,
    }


def _five_language_status(rows):
    locales = sorted({str(row.get("locale") or row.get("target_locale") or "") for row in rows if row})
    missing = [locale for locale in EXPECTED_LOCALES if locale not in locales]
    return {
        "status": "complete_5_languages" if not missing else "missing_languages",
        "expected_locales": list(EXPECTED_LOCALES),
        "locales_found": locales,
        "missing_locales": missing,
    }


def _translated_count(rows):
    count = 0
    for row in rows:
        status = str(row.get("status") or "")
        if status in {
            "already_translated_skipped",
            "missing_translation_draft_ready",
            "outdated_translation_update_draft_ready",
        }:
            count += 1
        elif _text(row.get("proposed_translation_value") or row.get("proposed_translation")):
            count += 1
    return count


def _needs_review_count(rows):
    return sum(1 for row in rows if _row_needs_review(row))


def _skipped_count(rows):
    return sum(
        1
        for row in rows
        if "skipped" in str(row.get("status") or "")
        or str(row.get("validation_status") or "") == "skipped"
    )


def _row_needs_review(row):
    values = [
        row.get("status"),
        row.get("validation_status"),
        row.get("seo_validation_status"),
        row.get("blocking_reason"),
        row.get("block_reason"),
    ]
    tokens = {str(value or "").strip().lower() for value in values if str(value or "").strip()}
    neutral_ready_tokens = {
        "already_translated_skipped",
        "draft_ready_for_manual_review",
        "missing_translation_draft_ready",
        "outdated_translation_update_draft_ready",
        "seo_ready",
        "skipped",
    }
    review_tokens = tokens - neutral_ready_tokens
    return (
        any("needs_review" in token for token in review_tokens)
        or any("manual_review_required" in token for token in review_tokens)
        or any("draft_needs_manual_review" in token for token in review_tokens)
        or bool(row.get("draft_blocked"))
        or bool(row.get("product_identity_mismatch"))
    )


def _int_from_report(report, key, entries, *statuses):
    value = (report.get("data") or {}).get(key)
    if isinstance(value, int):
        return value
    return sum(1 for entry in entries if entry.get("status") in set(statuses))


def _not_updated_count(report, entries):
    value = report.get("not_updated_count")
    if isinstance(value, int):
        return value
    statuses = {"blocked", "skipped", "write_failed", "readback_mismatch"}
    return sum(1 for entry in entries if entry.get("status") in statuses)


def _top_not_updated_reasons(entries):
    reasons = Counter()
    for entry in entries:
        if entry.get("status") not in {"blocked", "skipped", "write_failed", "readback_mismatch"}:
            continue
        reason = (
            _first_text(entry.get("human_blocking_reasons"))
            or _text(entry.get("blocking_reason"))
            or _first_text(entry.get("blocking_reasons"))
            or _text(entry.get("status"))
        )
        if reason:
            reasons[reason] += 1
    return [
        {"reason": reason, "count": count}
        for reason, count in reasons.most_common(5)
    ]


def _body_html_result(rows):
    body_rows = [row for row in rows if str(row.get("key") or row.get("field_key") or "") == "body_html"]
    status_counts = Counter(str(row.get("status") or "unknown") for row in body_rows)
    validation_counts = Counter(
        str(row.get("validation_status") or "unknown") for row in body_rows
    )
    blocker_counts = Counter()
    for row in body_rows:
        for reason in row.get("blocking_reasons") or []:
            blocker_counts[str(reason)] += 1
        if not row.get("blocking_reasons") and row.get("blocking_reason"):
            blocker_counts[str(row.get("blocking_reason"))] += 1
    hard_blocked = sum(
        count
        for status, count in status_counts.items()
        if status in {"blocked", "write_failed", "readback_mismatch"}
    )
    return {
        "present": bool(body_rows),
        "row_count": len(body_rows),
        "status_counts": _counter_rows(status_counts),
        "validation_status_counts": _counter_rows(validation_counts),
        "html_validation_result": (
            "passed_or_already_current"
            if body_rows and hard_blocked == 0
            else "needs_review_or_blocked"
            if body_rows
            else "not_present"
        ),
        "top_blocking_reasons": _counter_rows(blocker_counts, limit=5),
    }


def _option_mapping_result(report, rows):
    audit = report.get("option_mapping_audit") or {}
    if audit:
        return {
            "present": bool(audit.get("row_count")),
            "row_count": int(audit.get("row_count") or 0),
            "mapping_safe_count": int(audit.get("mapping_safe_count") or 0),
            "future_update_ready_count": int(audit.get("future_update_ready_count") or 0),
            "blocked_count": int(audit.get("blocked_count") or 0),
            "all_future_update_ready": bool(audit.get("all_future_update_ready")),
            "plain_summary": audit.get("plain_summary", ""),
        }
    option_rows = [
        row
        for row in rows
        if str(row.get("group_key") or row.get("field_group") or "") == "options"
    ]
    safe_count = sum(1 for row in option_rows if _real_shopify_gid(row.get("resource_id")) and _text(row.get("digest")))
    return {
        "present": bool(option_rows),
        "row_count": len(option_rows),
        "mapping_safe_count": safe_count,
        "future_update_ready_count": 0,
        "blocked_count": max(0, len(option_rows) - safe_count),
        "all_future_update_ready": False,
        "plain_summary": (
            "Option rows have resource IDs and digests."
            if option_rows and safe_count == len(option_rows)
            else "Option mapping needs review."
            if option_rows
            else "No option rows found."
        ),
    }


def _media_alt_mapping_result(rows, product_gid):
    media_rows = [
        _media_alt_row(row, product_gid)
        for row in rows
        if _is_media_alt_row(row)
    ]
    return _media_alt_summary(media_rows)


def _media_alt_summary(media_rows):
    classifications = Counter(row.get("classification", "") for row in media_rows)
    safe_mapping_count = sum(1 for row in media_rows if row.get("mapping_safe"))
    input_ready_count = sum(1 for row in media_rows if row.get("registration_input_ready"))
    readback_count = sum(1 for row in media_rows if row.get("readback_method_available"))
    all_safe = bool(media_rows) and safe_mapping_count == len(media_rows)
    if not media_rows:
        recommendation = "No sampled media alt rows were found; empty media alt values stay skipped."
    elif all_safe and input_ready_count == len(media_rows) and readback_count == len(media_rows):
        recommendation = (
            "All sampled media alt rows have safe resource mapping for the existing "
            "enabled write path when validation passes."
        )
    else:
        recommendation = (
            "Only media alt rows with resource ID, key, digest, proposed text, and "
            "readback mapping can use the existing enabled write path."
        )
    return {
        "row_count": len(media_rows),
        "classification_counts": _counter_rows(classifications),
        "safe_mapping_count": safe_mapping_count,
        "registration_input_ready_count": input_ready_count,
        "readback_method_available_count": readback_count,
        "all_sampled_rows_mapping_safe": all_safe,
        "recommendation": recommendation,
        "rows": media_rows,
    }


def _media_alt_row(row, product_gid):
    resource_id = _text(row.get("resource_id"))
    source_key = _text(row.get("source_key") or row.get("shopify_key") or row.get("key"))
    digest = _text(row.get("digest") or row.get("source_digest"))
    source_value = _text(row.get("source_value"))
    proposed_value = _text(
        row.get("proposed_translation_value")
        or row.get("proposed_translation")
        or row.get("manual_edit_value")
        or row.get("generated_draft_display")
    )
    locale = _text(row.get("locale") or row.get("target_locale"))
    resource_type = _gid_type(resource_id)
    key_safe = source_key == "alt" or _text(row.get("key")) == "media.alt"
    real_gid = _real_shopify_gid(resource_id)
    maps_to_media = resource_type in {"MediaImage", "Image"} and key_safe
    mapping_safe = real_gid and maps_to_media
    registration_input_ready = mapping_safe and bool(digest) and key_safe
    readback_available = mapping_safe and bool(locale)
    needs_review = _row_needs_review(row)
    status = _text(row.get("status"))
    blocking_reason = _text(row.get("blocking_reason") or row.get("block_reason"))
    if not mapping_safe or not key_safe:
        classification = "media_alt_missing_mapping"
    elif not digest:
        classification = "media_alt_missing_digest"
    elif not proposed_value:
        classification = "media_alt_empty_translation"
    elif needs_review:
        classification = "media_alt_needs_review"
    elif status == "blocked" or blocking_reason in MEDIA_ALT_DISABLED_REASONS:
        classification = "media_alt_update_not_enabled"
    else:
        classification = "media_alt_write_ready"
    return {
        "product_gid": product_gid,
        "locale": locale,
        "media_resource_type": resource_type or _text(row.get("resource_type")),
        "resource_id": resource_id,
        "resource_id_exists": bool(resource_id),
        "resource_id_is_real_shopify_gid": real_gid,
        "resource_id_is_visible_or_local_only": resource_id.startswith("visible://"),
        "key": "alt" if key_safe else source_key,
        "key_exists": key_safe,
        "digest": digest,
        "digest_exists": bool(digest),
        "source_alt_text_exists": bool(source_value),
        "proposed_translation_exists": bool(proposed_value),
        "existing_translation_state": _existing_translation_state(row),
        "readback_method_available": readback_available,
        "registration_input_ready": registration_input_ready,
        "maps_to_correct_media_object": maps_to_media,
        "mapping_safe": mapping_safe,
        "status": status,
        "blocking_reason": blocking_reason,
        "classification": classification,
    }


def _variant_rows(rows, product_gid):
    variants = []
    for row in rows:
        group = str(row.get("group_key") or row.get("field_group") or "")
        key = str(row.get("key") or row.get("field_key") or "")
        if group != "variants" and not key.startswith("variant."):
            continue
        resource_id = _text(row.get("resource_id"))
        locale = _text(row.get("locale") or row.get("target_locale"))
        digest = _text(row.get("digest") or row.get("source_digest"))
        proposed = _proposed_translation(row)
        marker_text = " ".join(
            _text(value).lower()
            for value in (
                key,
                row.get("field_label"),
                row.get("context_label"),
                row.get("resource_note"),
            )
        )
        technical = any(marker in marker_text for marker in ("sku", "barcode"))
        missing = _missing_enablement_requirements(
            resource_id=resource_id,
            key=key,
            digest=digest,
            locale=locale,
            proposed=proposed,
        )
        empty_value = not bool(proposed)
        ready_later = not technical and not missing and not empty_value
        variants.append(
            {
                "product_gid": product_gid,
                "locale": locale,
                "locale_exists": bool(locale),
                "key": key,
                "key_exists": bool(key),
                "resource_id": resource_id,
                "resource_id_exists": bool(resource_id),
                "resource_id_is_real_shopify_gid": _real_shopify_gid(resource_id),
                "digest": digest,
                "digest_exists": bool(digest),
                "proposed_translation_exists": bool(proposed),
                "readback_method_available": bool(resource_id and locale),
                "customer_facing": not technical,
                "technical_or_sku": technical,
                "missing_requirements": missing,
                "missing_mapping": _missing_mapping_blocked(missing),
                "empty_value_skipped": empty_value,
                "ready_for_next_enablement_task": ready_later,
                "safe_to_write_now": False,
                "write_disabled": True,
                "classification": _future_enablement_classification(
                    ready_later=ready_later,
                    technical=technical,
                    empty_value=empty_value,
                    missing=missing,
                ),
            }
        )
    return variants


def _metafield_rows(rows, product_gid):
    metafields = []
    for row in rows:
        group = str(row.get("group_key") or row.get("field_group") or "")
        resource_id = _text(row.get("resource_id"))
        if "metafield" not in group and _gid_type(resource_id) != "Metafield":
            continue
        namespace, key = _metafield_namespace_key(row)
        marker_text = f"{namespace} {key} {_text(row.get('resource_note'))} {_text(row.get('context_label'))}".lower()
        technical = _is_technical_metafield(marker_text)
        customer_candidate = (
            not technical
            and any(marker in marker_text for marker in CUSTOMER_FACING_METAFIELD_MARKERS)
        )
        locale = _text(row.get("locale") or row.get("target_locale"))
        digest = _text(row.get("digest") or row.get("source_digest"))
        proposed = _proposed_translation(row)
        missing = _missing_enablement_requirements(
            resource_id=resource_id,
            key=key,
            digest=digest,
            locale=locale,
            proposed=proposed,
        )
        empty_value = not bool(proposed)
        ready_later = customer_candidate and not missing and not empty_value
        metafields.append(
            {
                "product_gid": product_gid,
                "locale": locale,
                "locale_exists": bool(locale),
                "namespace": namespace,
                "key": key,
                "key_exists": bool(key),
                "resource_id": resource_id,
                "resource_id_exists": bool(resource_id),
                "resource_id_is_real_shopify_gid": _real_shopify_gid(resource_id),
                "digest": digest,
                "digest_exists": bool(digest),
                "proposed_translation_exists": bool(proposed),
                "readback_method_available": bool(resource_id and locale),
                "missing_requirements": missing,
                "missing_mapping": _missing_mapping_blocked(missing),
                "empty_value_skipped": empty_value,
                "customer_facing_candidate": customer_candidate,
                "technical_or_internal": technical,
                "ready_for_next_enablement_task": ready_later,
                "safe_to_write_now": False,
                "write_disabled": True,
                "classification": _future_enablement_classification(
                    ready_later=ready_later,
                    technical=technical,
                    empty_value=empty_value,
                    missing=missing,
                ),
            }
        )
    return metafields


def _variant_metafield_summary(variant_rows, metafield_rows):
    variant_count = len(variant_rows)
    variants_with_mapping = sum(
        1
        for row in variant_rows
        if row.get("resource_id_is_real_shopify_gid") and row.get("digest_exists") and row.get("key")
    )
    unique_metafields = {}
    for row in metafield_rows:
        namespace_key = f"{row.get('namespace', '')}.{row.get('key', '')}".strip(".")
        unique_metafields.setdefault(namespace_key, row)
    blocked = sorted(
        key
        for key, row in unique_metafields.items()
        if row.get("technical_or_internal")
    )
    candidates = sorted(
        key
        for key, row in unique_metafields.items()
        if row.get("customer_facing_candidate")
    )
    variant_ready = sum(
        1 for row in variant_rows if row.get("ready_for_next_enablement_task")
    )
    customer_metafield_ready = sum(
        1 for row in metafield_rows if row.get("ready_for_next_enablement_task")
    )
    customer_metafield_blocked = sum(
        1
        for row in metafield_rows
        if row.get("customer_facing_candidate")
        and not row.get("ready_for_next_enablement_task")
        and not row.get("empty_value_skipped")
    )
    missing_mapping = sum(
        1 for row in variant_rows + metafield_rows if row.get("missing_mapping")
    )
    empty_values = sum(
        1 for row in variant_rows + metafield_rows if row.get("empty_value_skipped")
    )
    return {
        "variant_row_count": variant_count,
        "variant_rows_with_resource_key_digest": variants_with_mapping,
        "variant_ready_for_next_enablement_count": variant_ready,
        "variant_status": (
            "ready_for_next_enablement_task"
            if variant_ready
            else "no_rows_found"
            if not variant_count
            else "not_ready"
        ),
        "variant_writes_enabled": False,
        "metafield_row_count": len(metafield_rows),
        "unique_metafield_count": len(unique_metafields),
        "technical_or_internal_metafield_count": sum(
            1 for row in metafield_rows if row.get("technical_or_internal")
        ),
        "customer_facing_future_candidate_count": sum(
            1 for row in metafield_rows if row.get("customer_facing_candidate")
        ),
        "customer_facing_metafield_ready_for_next_enablement_count": (
            customer_metafield_ready
        ),
        "customer_facing_metafield_blocked_count": customer_metafield_blocked,
        "missing_mapping_blocked_count": missing_mapping,
        "empty_value_skipped_count": empty_values,
        "permanently_blocked_namespaces_keys": blocked,
        "future_candidate_namespaces_keys": candidates,
        "ready_for_next_enablement_namespaces_keys": sorted(
            {
                f"{row.get('namespace', '')}.{row.get('key', '')}".strip(".")
                for row in metafield_rows
                if row.get("ready_for_next_enablement_task")
            }
        ),
        "ready_for_next_enablement_variant_row_count": variant_ready,
        "summary": (
            "Variants and metafields remain write-disabled in this audit. "
            "Rows marked ready still require a separate enablement task before "
            "any Shopify write path is opened."
        ),
        "variant_rows": variant_rows,
        "metafield_rows": metafield_rows,
    }


def _missing_enablement_requirements(*, resource_id, key, digest, locale, proposed):
    missing = []
    if not resource_id:
        missing.append("resource_id")
    elif not _real_shopify_gid(resource_id):
        missing.append("real Shopify resource_id")
    if not key:
        missing.append("key")
    if not digest:
        missing.append("digest")
    if not locale:
        missing.append("locale")
    if not proposed:
        missing.append("proposed translation")
    if not (resource_id and locale):
        missing.append("readback path")
    return _unique_strings(missing)


def _proposed_translation(row):
    return _text(
        row.get("proposed_translation_value")
        or row.get("proposed_translation")
        or row.get("manual_edit_value")
        or row.get("generated_draft_display")
        or row.get("draft_value")
    )


def _future_enablement_classification(*, ready_later, technical, empty_value, missing):
    if ready_later:
        return "ready_for_next_enablement_task"
    if technical:
        return "technical_or_internal_blocked"
    if empty_value:
        return "empty_value_skipped"
    if missing:
        return "missing_mapping_blocked"
    return "not_ready"


def _missing_mapping_blocked(missing):
    return any(item != "proposed translation" for item in missing or [])


def _unique_strings(values):
    unique = []
    seen = set()
    for value in values or []:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _workflow_readiness_summary(product_audits):
    products_with_update = [
        item for item in product_audits if item.get("latest_shopify_update_report_exists")
    ]
    verified_total = sum(int(item.get("verified_count") or 0) for item in products_with_update)
    rollback_count = sum(1 for item in products_with_update if item.get("rollback_needed"))
    option_ready = sum(
        1
        for item in product_audits
        if item.get("options_mapping_result", {}).get("all_future_update_ready")
    )
    body_passed = sum(
        1
        for item in product_audits
        if item.get("body_html_validation_result", {}).get("html_validation_result")
        == "passed_or_already_current"
    )
    return {
        "ready_now": [
            "Product title",
            "SEO title",
            "SEO description",
            "Product description when HTML validation passes",
            "Product options when Shopify mapping is confirmed",
            "Media alt text when validation passes",
        ],
        "sampled_products_with_update_report": len(products_with_update),
        "verified_update_count_across_sample": verified_total,
        "sampled_products_with_rollback_needed": rollback_count,
        "sampled_products_with_option_mapping_ready": option_ready,
        "sampled_products_with_body_html_validation_passed": body_passed,
        "summary": (
            "Existing safe-field flow is stable in sampled local reports when "
            "rollback_needed is false and verified_count matches updated_count."
        ),
    }


def _overall_recommendation(payload):
    media = payload.get("media_alt_text_mapping_audit") or {}
    variant_meta = payload.get("variant_metafield_quick_audit") or {}
    if media.get("all_sampled_rows_mapping_safe"):
        media_text = "Keep enabled with current mapping, validation, and readback gates."
    else:
        media_text = "Keep unsafe media alt rows blocked by the current gates."
    variant_ready = int(
        variant_meta.get("variant_ready_for_next_enablement_count") or 0
    )
    metafield_ready = int(
        variant_meta.get(
            "customer_facing_metafield_ready_for_next_enablement_count"
        )
        or 0
    )
    return {
        "existing_safe_fields": "Keep enabled with current validation gates.",
        "media_alt_text": media_text,
        "variants": (
            "Ready for a separate enablement task."
            if variant_ready
            else "Keep disabled."
        ),
        "metafields": (
            "Some customer-facing metafields are ready for a separate enablement task; "
            "technical/internal metafields stay blocked."
            if metafield_ready
            else "Keep technical/internal metafields blocked."
        ),
    }


def _sample_types_audited(product_audits):
    found = []
    for product in product_audits:
        for role in product.get("sample_types") or []:
            if role not in found:
                found.append(role)
    return found


def _count_rows(rows, *, groups=None, keys=None):
    groups = groups or set()
    keys = keys or set()
    return sum(
        1
        for row in rows
        if str(row.get("group_key") or row.get("field_group") or "") in groups
        or str(row.get("key") or row.get("field_key") or "") in keys
    )


def _max_body_html_chars(rows):
    values = []
    for row in rows:
        if str(row.get("key") or row.get("field_key") or "") != "body_html":
            continue
        values.append(len(_text(row.get("source_value"))))
        values.append(len(_text(row.get("proposed_translation_value") or row.get("proposed_translation"))))
    return max(values or [0])


def _is_media_alt_row(row):
    group = str(row.get("group_key") or row.get("field_group") or "")
    key = str(row.get("key") or row.get("field_key") or "")
    return group in {"media", "media_alt_text"} or key == "media.alt"


def _existing_translation_state(row):
    existing_value = _text(
        row.get("previous_translation_value")
        or row.get("existing_translation_value")
        or row.get("translation_value")
    )
    outdated = row.get("previous_translation_outdated")
    if outdated is None:
        outdated = row.get("existing_translation_outdated")
    if existing_value and outdated is True:
        return "existing_outdated"
    if existing_value:
        return "existing_current_or_unknown"
    return "missing"


def _metafield_namespace_key(row):
    namespace = _text(row.get("metafield_namespace"))
    key = _text(row.get("metafield_key"))
    if namespace or key:
        return namespace, key
    context = _text(row.get("context_label"))
    if "|" in context:
        parts = [part.strip() for part in context.split("|", 1)]
        return parts[0], parts[1]
    field_key = _text(row.get("key") or row.get("field_key"))
    if field_key.startswith("metafield."):
        parts = field_key.split(".")
        if len(parts) >= 3:
            return parts[1], ".".join(parts[2:])
    return "", context or field_key


def _is_technical_metafield(marker_text):
    return any(marker in marker_text for marker in TECHNICAL_METAFIELD_MARKERS)


def _real_shopify_gid(value):
    return _text(value).startswith("gid://shopify/")


def _gid_type(value):
    text = _text(value)
    if not text.startswith("gid://shopify/"):
        return ""
    rest = text[len("gid://shopify/") :]
    return rest.split("/", 1)[0]


def _rows(data, key):
    rows = data.get(key) if isinstance(data, dict) else []
    return [row for row in rows or [] if isinstance(row, dict)]


def _counter_rows(counter, limit=None):
    rows = [
        {"name": str(name), "count": count}
        for name, count in counter.most_common(limit)
    ]
    return rows


def _first_text(value):
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _text(item)
            if text:
                return text
    return _text(value)


def _text(value):
    return str(value or "").strip()


def _display_path(path):
    if not path:
        return ""
    path = Path(path)
    for root in (_workspace_root(), _code_root()):
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def _output_dir(option_value, generated_at):
    if option_value:
        path = Path(option_value)
        if not path.is_absolute():
            path = _workspace_root() / path
        return path
    stamp = generated_at.replace(":", "").replace("-", "")
    return _default_output_root() / f"{stamp}_translation_readiness_audit"


def _write_reports(payload, json_path, html_path):
    json_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    json.loads(text)
    json_path.write_text(text, encoding="utf-8")
    html_path.write_text(_render_html(payload), encoding="utf-8")


def _render_html(payload):
    product_rows = "\n".join(
        _product_html_row(product) for product in payload.get("sampled_products", [])
    ) or "<tr><td colspan='10'>No sampled products found.</td></tr>"
    media_rows = "\n".join(
        _media_html_row(row)
        for row in (payload.get("media_alt_text_mapping_audit") or {}).get("rows", [])
    ) or "<tr><td colspan='9'>No media alt rows found.</td></tr>"
    blocked_metafields = ", ".join(
        (payload.get("variant_metafield_quick_audit") or {}).get(
            "permanently_blocked_namespaces_keys",
            [],
        )
    )
    future_metafields = ", ".join(
        (payload.get("variant_metafield_quick_audit") or {}).get(
            "future_candidate_namespaces_keys",
            [],
        )
    )
    ready_metafields = ", ".join(
        (payload.get("variant_metafield_quick_audit") or {}).get(
            "ready_for_next_enablement_namespaces_keys",
            [],
        )
    )
    media = payload.get("media_alt_text_mapping_audit") or {}
    workflow = payload.get("existing_translation_workflow_readiness_summary") or {}
    variant_meta = payload.get("variant_metafield_quick_audit") or {}
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Translation readiness audit</title>
  <style>
    body {{ color: #111827; background: #ffffff; font-family: Arial, sans-serif; line-height: 1.45; }}
    table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
    th, td {{ border: 1px solid #dbe1e8; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f6fa; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; }}
    .card {{ border: 1px solid #dbe1e8; border-radius: 8px; padding: 10px; background: #fbfdff; }}
    details {{ margin: 12px 0; }}
    code {{ overflow-wrap: anywhere; }}
  </style>
</head>
<body>
  <h1>Translation readiness audit</h1>
  <p>Local report audit only. No Shopify API call, mutation, update action, or email action was run by this command.</p>
  <div class="grid">
    <div class="card"><strong>Products audited</strong><br>{escape(str(payload.get('sampled_product_count', 0)))}</div>
    <div class="card"><strong>Verified safe-field updates in sample</strong><br>{escape(str(workflow.get('verified_update_count_across_sample', 0)))}</div>
    <div class="card"><strong>Media alt rows classified</strong><br>{escape(str(media.get('row_count', 0)))}</div>
    <div class="card"><strong>Rollback needed products</strong><br>{escape(str(workflow.get('sampled_products_with_rollback_needed', 0)))}</div>
  </div>
  <h2>Plain-language summary</h2>
  <ul>
    <li>Ready now: {escape(', '.join(workflow.get('ready_now') or []))}</li>
    <li>Needs review: fields with validation blockers stay out of update.</li>
    <li>Not enabled here: variants and metafields remain disabled in this audit.</li>
    <li>Future candidate: {escape((payload.get('recommendation') or {}).get('media_alt_text', ''))}</li>
    <li>Blocked technical fields: {escape(blocked_metafields or 'None found in sample.')}</li>
  </ul>
  <h2>Product samples</h2>
  <table>
    <thead><tr><th>Sample type</th><th>Product</th><th>5 languages</th><th>Translated</th><th>Needs review</th><th>Skipped</th><th>Update report</th><th>Updated</th><th>Confirmed</th><th>Not updated</th></tr></thead>
    <tbody>{product_rows}</tbody>
  </table>
  <h2>Media alt text mapping</h2>
  <p>{escape(media.get('recommendation', ''))}</p>
  <table>
    <thead><tr><th>Product</th><th>Locale</th><th>Resource type</th><th>Real gid</th><th>Key</th><th>Digest</th><th>Source alt</th><th>Translation</th><th>Classification</th></tr></thead>
    <tbody>{media_rows}</tbody>
  </table>
  <details>
    <summary>Technical media IDs and digests</summary>
    <table>
      <thead><tr><th>Product</th><th>Locale</th><th>resource_id</th><th>key</th><th>digest</th><th>readback</th><th>registration input</th></tr></thead>
      <tbody>{_media_technical_rows(media.get('rows') or [])}</tbody>
    </table>
  </details>
  <h2>Variants and metafields</h2>
  <ul>
    <li>Variants: {escape(str(variant_meta.get('variant_status', 'not_ready')))}; rows: {escape(str(variant_meta.get('variant_row_count', 0)))}; ready for next enablement: {escape(str(variant_meta.get('variant_ready_for_next_enablement_count', 0)))}.</li>
    <li>Customer-facing metafields: {escape(str(variant_meta.get('customer_facing_metafield_ready_for_next_enablement_count', 0)))} ready / {escape(str(variant_meta.get('customer_facing_metafield_blocked_count', 0)))} blocked.</li>
    <li>Technical fields: blocked; technical/internal rows: {escape(str(variant_meta.get('technical_or_internal_metafield_count', 0)))}.</li>
    <li>Missing mapping: blocked; rows: {escape(str(variant_meta.get('missing_mapping_blocked_count', 0)))}.</li>
    <li>Empty values: skipped; rows: {escape(str(variant_meta.get('empty_value_skipped_count', 0)))}.</li>
    <li>Future candidate metafields: {escape(future_metafields or 'None found in sample.')}</li>
    <li>Ready for next enablement task: {escape(ready_metafields or 'None found in sample.')}</li>
    <li>Write status: variants and metafields remain disabled by this audit.</li>
  </ul>
  <details>
    <summary>Variant row classification</summary>
    <table>
      <thead><tr><th>Product</th><th>Locale</th><th>Key</th><th>Resource ID</th><th>Digest</th><th>Proposed text</th><th>Readback</th><th>Classification</th></tr></thead>
      <tbody>{_future_field_rows(variant_meta.get('variant_rows') or [])}</tbody>
    </table>
  </details>
  <details>
    <summary>Metafield row classification</summary>
    <table>
      <thead><tr><th>Product</th><th>Locale</th><th>Key</th><th>Resource ID</th><th>Digest</th><th>Proposed text</th><th>Readback</th><th>Classification</th></tr></thead>
      <tbody>{_future_field_rows(variant_meta.get('metafield_rows') or [])}</tbody>
    </table>
  </details>
</body>
</html>
"""


def _future_field_rows(rows):
    if not rows:
        return "<tr><td colspan='8'>No rows found.</td></tr>"
    return "\n".join(
        "<tr>"
        f"<td><code>{escape(row.get('product_gid', ''))}</code></td>"
        f"<td>{escape(row.get('locale', ''))}</td>"
        f"<td>{escape(row.get('key', ''))}</td>"
        f"<td><code>{escape(row.get('resource_id', ''))}</code></td>"
        f"<td>{escape('Yes' if row.get('digest_exists') else 'No')}</td>"
        f"<td>{escape('Yes' if row.get('proposed_translation_exists') else 'No')}</td>"
        f"<td>{escape('Yes' if row.get('readback_method_available') else 'No')}</td>"
        f"<td>{escape(row.get('classification', ''))}</td>"
        "</tr>"
        for row in rows
    )


def _product_html_row(product):
    language_status = product.get("five_languages_status") or {}
    roles = ", ".join(product.get("sample_types") or [])
    return (
        "<tr>"
        f"<td>{escape(roles)}</td>"
        f"<td>{escape(product.get('product_title', ''))}<br><code>{escape(product.get('product_gid', ''))}</code></td>"
        f"<td>{escape(language_status.get('status', ''))}</td>"
        f"<td>{escape(str(product.get('translated_count', 0)))}</td>"
        f"<td>{escape(str(product.get('needs_review_count', 0)))}</td>"
        f"<td>{escape(str(product.get('skipped_count', 0)))}</td>"
        f"<td>{escape('Yes' if product.get('latest_shopify_update_report_exists') else 'No')}</td>"
        f"<td>{escape(str(product.get('updated_count', 0)))}</td>"
        f"<td>{escape(str(product.get('verified_count', 0)))}</td>"
        f"<td>{escape(str(product.get('not_updated_count', 0)))}</td>"
        "</tr>"
    )


def _media_html_row(row):
    return (
        "<tr>"
        f"<td><code>{escape(row.get('product_gid', ''))}</code></td>"
        f"<td>{escape(row.get('locale', ''))}</td>"
        f"<td>{escape(row.get('media_resource_type', ''))}</td>"
        f"<td>{escape(str(row.get('resource_id_is_real_shopify_gid', False)))}</td>"
        f"<td>{escape(str(row.get('key_exists', False)))}</td>"
        f"<td>{escape(str(row.get('digest_exists', False)))}</td>"
        f"<td>{escape(str(row.get('source_alt_text_exists', False)))}</td>"
        f"<td>{escape(str(row.get('proposed_translation_exists', False)))}</td>"
        f"<td>{escape(row.get('classification', ''))}</td>"
        "</tr>"
    )


def _media_technical_rows(rows):
    return "\n".join(
        "<tr>"
        f"<td><code>{escape(row.get('product_gid', ''))}</code></td>"
        f"<td>{escape(row.get('locale', ''))}</td>"
        f"<td><code>{escape(row.get('resource_id', ''))}</code></td>"
        f"<td>{escape(row.get('key', ''))}</td>"
        f"<td><code>{escape(row.get('digest', ''))}</code></td>"
        f"<td>{escape(str(row.get('readback_method_available', False)))}</td>"
        f"<td>{escape(str(row.get('registration_input_ready', False)))}</td>"
        "</tr>"
        for row in rows
    ) or "<tr><td colspan='7'>No media technical rows.</td></tr>"


def main():
    parser = argparse.ArgumentParser(
        description="Run a local-only Translation Workspace readiness audit."
    )
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--sample-limit", type=int, default=6)
    args = parser.parse_args()
    payload = run_audit(
        output_dir=args.output_dir,
        sample_limit=args.sample_limit,
    )
    _print_summary(payload, print)


if __name__ == "__main__":
    main()
