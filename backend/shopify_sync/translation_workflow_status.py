import json
import os
from pathlib import Path


DEFAULT_SELECTED_PRODUCT_ID = "gid://shopify/Product/7655686799427"
CONFIGURED_LOCALE_SCOPE = ["ja", "de", "fr", "es", "it"]
CONFIGURED_FIELDS = ["title", "meta_title", "meta_description"]

MODULE_PATH = Path(__file__).resolve()
PROJECT_ROOT = MODULE_PATH.parents[2]
ENV_LOG_DIR = "SHOPIFY_TRANSLATION_WORKFLOW_LOG_DIR"
REPORT_FILENAMES = [
    "shopify_translation_remaining_title_batch_post_write_audit.json",
    "shopify_translation_next_batch_post_write_audit.json",
    "shopify_translation_small_batch_post_write_audit.json",
    "shopify_translation_selected_product_real_write_execute.json",
]
STATIC_LOG_DIR_CANDIDATES = [
    ("cwd_logs", Path.cwd() / "logs"),
    ("project_root_logs", PROJECT_ROOT / "logs"),
    ("backend_logs", MODULE_PATH.parents[1] / "logs"),
    ("app_logs", Path("/app/logs")),
    ("workflow_logs_mount", Path("/app/workflow_logs")),
]
AUDIT_REPORT_CANDIDATES = []


def load_translation_workflow_status(product_id: str) -> dict:
    selected_product_id = (product_id or "").strip() or DEFAULT_SELECTED_PRODUCT_ID
    report, report_path, report_source, warnings = _load_latest_report()
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
        "latest_audit_report_source": report_source,
        "latest_audit_generated_at": report.get("generated_at", ""),
        "read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "warnings": warnings,
    }


def _load_latest_report() -> tuple[dict, Path | None, str, list[str]]:
    warnings = []
    candidate_paths = _audit_report_candidates()
    for path, source in candidate_paths:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"{path.name}: {exc.__class__.__name__}")
            continue
        if isinstance(data, dict):
            return data, path, source, warnings
        warnings.append(f"{path.name}: not_a_json_object")
    if not warnings:
        searched = ", ".join(
            _relative_report_path(path.parent) or str(path.parent)
            for path, _source in candidate_paths[:8]
        )
        warnings.append(
            "no_translation_workflow_audit_report_found_in_container_visible_paths"
        )
        if searched:
            warnings.append(f"searched_paths={searched}")
    return {}, None, "", warnings


def _audit_report_candidates() -> list[tuple[Path, str]]:
    if AUDIT_REPORT_CANDIDATES:
        return _unique_path_records(
            (Path(path), "custom_candidate") for path in AUDIT_REPORT_CANDIDATES
        )

    log_dirs = []
    env_log_dir = (os.getenv(ENV_LOG_DIR) or "").strip()
    if env_log_dir:
        log_dirs.append(("env_log_dir", Path(env_log_dir)))
    log_dirs.extend(STATIC_LOG_DIR_CANDIDATES)

    candidates = []
    for source, log_dir in log_dirs:
        for filename in REPORT_FILENAMES:
            candidates.append((log_dir / filename, source))
    return _unique_path_records(candidates)


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


def _unique_path_records(records) -> list[tuple[Path, str]]:
    seen = set()
    unique = []
    for path, source in records:
        resolved = str(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append((path, source))
    return unique


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
