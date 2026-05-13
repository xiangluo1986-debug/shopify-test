import json
from pathlib import Path


DEFAULT_SELECTED_PRODUCT_ID = "gid://shopify/Product/7655686799427"
CONFIGURED_LOCALE_SCOPE = ["ja", "de", "fr", "es", "it"]
CONFIGURED_FIELDS = ["title", "meta_title", "meta_description"]

MODULE_PATH = Path(__file__).resolve()
PROJECT_ROOT = MODULE_PATH.parents[2]
REPORT_FILENAMES = [
    "shopify_translation_remaining_title_batch_post_write_audit.json",
    "shopify_translation_next_batch_post_write_audit.json",
    "shopify_translation_small_batch_post_write_audit.json",
    "shopify_translation_selected_product_real_write_execute.json",
]
LOG_DIR_CANDIDATES = [
    Path.cwd() / "logs",
    PROJECT_ROOT / "logs",
    MODULE_PATH.parents[1] / "logs",
]
AUDIT_REPORT_CANDIDATES = [
    path
    for log_dir in LOG_DIR_CANDIDATES
    for path in (log_dir / filename for filename in REPORT_FILENAMES)
]


def load_translation_workflow_status(product_id: str) -> dict:
    selected_product_id = (product_id or "").strip() or DEFAULT_SELECTED_PRODUCT_ID
    report, report_path, warnings = _load_latest_report()
    workflow_status = _workflow_status_from_report(report)

    return {
        "product_id": selected_product_id,
        "workflow_status": workflow_status,
        "configured_locale_scope": list(CONFIGURED_LOCALE_SCOPE),
        "configured_fields": list(CONFIGURED_FIELDS),
        "remaining_eligible_count": _remaining_eligible_count(report),
        "duplicate_write_protection_status": report.get(
            "duplicate_write_protection_status", ""
        ),
        "latest_audit_report_path": _relative_report_path(report_path),
        "latest_audit_generated_at": report.get("generated_at", ""),
        "read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "warnings": warnings,
    }


def _load_latest_report() -> tuple[dict, Path | None, list[str]]:
    warnings = []
    for path in _unique_paths(AUDIT_REPORT_CANDIDATES):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"{path.name}: {exc.__class__.__name__}")
            continue
        if isinstance(data, dict):
            return data, path, warnings
        warnings.append(f"{path.name}: not_a_json_object")
    if not warnings:
        warnings.append("no_translation_workflow_audit_report_found")
    return {}, None, warnings


def _workflow_status_from_report(report: dict) -> str:
    if not report:
        return "unknown"

    explicit_status = report.get("selected_product_seo_fields_completion_status", "")
    if explicit_status:
        return explicit_status

    if (
        _remaining_eligible_count(report) == 0
        and report.get("duplicate_write_protection_status") == "duplicate_write_prevented"
    ):
        return "completed_for_configured_fields"

    blocking = report.get("blocking_conditions") or report.get(
        "completion_blocking_conditions"
    )
    if blocking:
        return "needs_review"

    review_markers = [
        report.get("readback_audit_status", ""),
        report.get("duplicate_write_protection_status", ""),
        report.get("audit_status", ""),
        report.get("execution_status", ""),
    ]
    if any("needs_review" in str(value) or "failed" in str(value) for value in review_markers):
        return "needs_review"

    return "in_progress"


def _remaining_eligible_count(report: dict):
    if not report:
        return None
    value = report.get("remaining_eligible_count")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _relative_report_path(path: Path | None) -> str:
    if path is None:
        return ""
    for root in _unique_paths([Path.cwd(), PROJECT_ROOT, MODULE_PATH.parents[1]]):
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            continue
    return str(path)


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
