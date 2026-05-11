import json
import re
import subprocess
import time
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, load_env, utc_now_iso


TASK_NAME = "shopify_translation_multi_locale_dry_run"
COMMAND_LABEL = "docker_compose_web_translate_shopify_product_multi_locale_dry_run"
REVIEW_PATH = LOG_DIR / "shopify_translation_multi_locale_dry_run_review.json"
DEFAULT_LOCALES = ["de", "fr", "es", "it", "ja"]
SUPPORTED_LOCALES = {
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "ja": "Japanese",
}
TIMEOUT_SECONDS = 420
TAIL_LINES = 120
PRODUCT_ID_RE = re.compile(r"^(?:\d+|gid://shopify/Product/\d+)$")
PERMISSION_DENIED_RE = re.compile(r"(access is denied|permission denied|docker_engine)", re.IGNORECASE)
DRY_RUN_NO_WRITE_PHRASE = "Dry run complete. No Shopify writes performed."
GLOSSARY_PATHS = {
    "de": PROJECT_ROOT / "backend" / "shopify_sync" / "translation_glossary_de.json",
    "fr": PROJECT_ROOT / "backend" / "shopify_sync" / "translation_glossary_fr.json",
    "es": PROJECT_ROOT / "backend" / "shopify_sync" / "translation_glossary_es.json",
    "it": PROJECT_ROOT / "backend" / "shopify_sync" / "translation_glossary_it.json",
    "ja": PROJECT_ROOT / "backend" / "shopify_sync" / "translation_glossary_ja.json",
}


def run_shopify_translation_multi_locale_dry_run_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    env = load_env(["SHOPIFY_TRANSLATION_TEST_PRODUCT_ID", "SHOPIFY_TRANSLATION_TEST_LOCALES"])
    product_id = (env.get("SHOPIFY_TRANSLATION_TEST_PRODUCT_ID") or "").strip()
    locales = _configured_locales(env.get("SHOPIFY_TRANSLATION_TEST_LOCALES", ""))
    locale_results = []

    for locale in locales:
        if locale not in SUPPORTED_LOCALES:
            locale_results.append(
                _failed_locale_result(
                    locale=locale,
                    language_name="",
                    failure_type="unsupported_locale",
                    failure_reason=(
                        f"Unsupported locale '{locale}'. Supported locales: "
                        f"{', '.join(DEFAULT_LOCALES)}."
                    ),
                )
            )
            continue

        review_paths = _review_paths(locale)
        glossary_error = _validate_glossary(locale)
        if glossary_error:
            locale_results.append(
                _failed_locale_result(
                    locale=locale,
                    language_name=SUPPORTED_LOCALES[locale],
                    failure_type="glossary_invalid",
                    failure_reason=glossary_error,
                    review_paths=review_paths,
                )
            )
            continue

        if not product_id:
            locale_results.append(
                _failed_locale_result(
                    locale=locale,
                    language_name=SUPPORTED_LOCALES[locale],
                    failure_type="missing_product_id",
                    failure_reason=(
                        "Missing SHOPIFY_TRANSLATION_TEST_PRODUCT_ID. "
                        "No Shopify translation dry-run command was executed."
                    ),
                    review_paths=review_paths,
                )
            )
            continue

        if not PRODUCT_ID_RE.match(product_id):
            locale_results.append(
                _failed_locale_result(
                    locale=locale,
                    language_name=SUPPORTED_LOCALES[locale],
                    failure_type="command_error",
                    failure_reason=(
                        "Invalid SHOPIFY_TRANSLATION_TEST_PRODUCT_ID format. "
                        "Use a numeric product ID or gid://shopify/Product/<id>."
                    ),
                    review_paths=review_paths,
                )
            )
            continue

        locale_results.append(_run_locale(product_id, locale))

    success_count = sum(1 for item in locale_results if item["success"])
    failed_count = len(locale_results) - success_count
    skipped_count = sum(1 for item in locale_results if item.get("skipped"))
    failed_locales = [item["locale"] for item in locale_results if not item["success"]]
    warning_locales = [item["locale"] for item in locale_results if item["warnings_count"]]
    all_success = bool(locale_results) and failed_count == 0
    successful_results = [item for item in locale_results if item["success"]]
    all_no_write_confirmed = bool(successful_results) and all(
        item["no_shopify_writes_confirmed"] for item in successful_results
    )
    detected_issue_summary = _build_issue_summary(locale_results, all_success, all_no_write_confirmed)

    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "mode": mode,
        "command_label": COMMAND_LABEL,
        "product_id": product_id or None,
        "locales": locales,
        "success_count": success_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "all_success": all_success,
        "failed_locales": failed_locales,
        "warning_locales": warning_locales,
        "results": locale_results,
        "warnings_count": sum(item["warnings_count"] for item in locale_results),
        "title_length_warnings": sum(item["title_length_warnings"] for item in locale_results),
        "meta_title_warnings": sum(item["meta_title_warnings"] for item in locale_results),
        "meta_description_warnings": sum(item["meta_description_warnings"] for item in locale_results),
        "removed_shipping_marketing_phrase_count": sum(
            item["removed_shipping_marketing_phrase_count"] for item in locale_results
        ),
        "removed_skipped_origin_field_count": sum(
            item["removed_skipped_origin_field_count"] for item in locale_results
        ),
        "all_no_write_confirmed": all_no_write_confirmed,
        "no_shopify_writes_performed": all_no_write_confirmed,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
        "detected_issue_summary": detected_issue_summary,
        "safety": {
            "dry_run_only": True,
            "shopify_writes_allowed": False,
            "register_translations_allowed": False,
            "publish_allowed": False,
            "database_writes_allowed": False,
            "git_push_allowed": False,
        },
    }
    review_path = _write_review(payload)
    return {
        "task_type": TASK_NAME,
        "success": all_success,
        "exit_code": 0 if all_success else 1,
        "products_checked": success_count,
        "warnings_count": payload["warnings_count"],
        "command_label": COMMAND_LABEL,
        "review_path": str(review_path),
        "detected_issue_summary": detected_issue_summary,
        "approval_message": _build_approval_message(payload, review_path),
    }


def _configured_locales(raw_value: str) -> list[str]:
    if not raw_value.strip():
        return DEFAULT_LOCALES[:]
    locales = []
    for item in raw_value.split(","):
        locale = item.strip().lower()
        if locale and locale not in locales:
            locales.append(locale)
    return locales or DEFAULT_LOCALES[:]


def _run_locale(product_id: str, locale: str) -> dict:
    started = time.time()
    review_paths = _review_paths(locale)
    container_review_path = review_paths["container_review_file_path"]
    host_review_path = Path(review_paths["host_review_file_path"])
    command = _build_command(product_id, locale, container_review_path)
    stdout = ""
    stderr = ""
    exit_code = 1
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=False,
            timeout=TIMEOUT_SECONDS,
            shell=False,
        )
        exit_code = completed.returncode
        stdout = _to_text(completed.stdout)
        stderr = _to_text(completed.stderr)
    except FileNotFoundError:
        exit_code = 127
        stderr = "Docker command was not found. Please install Docker Desktop and make sure it is available in PATH."
    except PermissionError:
        exit_code = 126
        stderr = "Docker permission denied. Stop here and use administrator PowerShell if needed."
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        stdout = _to_text(exc.stdout)
        stderr = _to_text(exc.stderr)
        stderr = (stderr + "\n" if stderr else "") + f"Locale {locale} timed out after {TIMEOUT_SECONDS} seconds."

    stdout_tail = _tail_lines(stdout, TAIL_LINES)
    stderr_tail = _tail_lines(stderr, TAIL_LINES)
    combined_tail = stdout_tail + "\n" + stderr_tail
    permission_denied = bool(PERMISSION_DENIED_RE.search(combined_tail))
    command_review, review_file_fresh = _parse_command_review(host_review_path, started)
    success = exit_code == 0
    no_write_confirmed = success and DRY_RUN_NO_WRITE_PHRASE in stdout
    return {
        "locale": locale,
        "language_name": SUPPORTED_LOCALES[locale],
        "success": success,
        "exit_code": exit_code,
        "skipped": False,
        "failure_type": None if success else _classify_failure(exit_code, timed_out, permission_denied),
        "failure_reason": "" if success else _failure_reason(exit_code, timed_out, permission_denied, stderr_tail),
        "permission_denied": permission_denied,
        "timed_out": timed_out,
        "duration_seconds": round(time.time() - started, 3),
        "review_file_path": str(host_review_path),
        "host_review_file_path": str(host_review_path),
        "container_review_file_path": container_review_path,
        "review_file_exists": host_review_path.exists(),
        "review_file_fresh": review_file_fresh,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "warnings_count": command_review.get("warnings_count", _count_warning_lines(combined_tail)),
        "title_length_warnings": command_review.get("title_length_warnings", 0),
        "meta_title_warnings": command_review.get("meta_title_warnings", 0),
        "meta_description_warnings": command_review.get("meta_description_warnings", 0),
        "removed_shipping_marketing_phrase_count": command_review.get(
            "removed_shipping_marketing_phrase_count", 0
        ),
        "removed_skipped_origin_field_count": command_review.get("removed_skipped_origin_field_count", 0),
        "no_shopify_writes_confirmed": no_write_confirmed,
        "no_shopify_writes_performed": no_write_confirmed,
    }


def _build_command(product_id: str, locale: str, review_file_path: str) -> list[str]:
    return [
        "docker",
        "compose",
        "exec",
        "-T",
        "web",
        "python",
        "manage.py",
        "translate_shopify_product",
        "--product-id",
        product_id,
        "--target-locale",
        locale,
        "--dry-run",
        "--review-file",
        review_file_path,
    ]


def _parse_command_review(path: Path, started_at: float) -> tuple[dict, bool]:
    if not path.exists():
        return {}, False
    try:
        if path.stat().st_mtime + 1 < started_at:
            return {}, False
    except OSError:
        return {}, False
    try:
        with path.open("r", encoding="utf-8") as review_file:
            data = json.load(review_file)
    except (json.JSONDecodeError, OSError):
        return {}, False
    warnings = data.get("warnings") or []
    summary = data.get("summary") or {}
    title_chars = summary.get("title_chars") or 0
    meta_title_chars = summary.get("meta_title_chars") or 0
    meta_description_chars = summary.get("meta_description_chars") or 0
    return {
        "dry_run": data.get("dry_run"),
        "warnings_count": len(warnings),
        "title_length_warnings": 1 if title_chars and title_chars > 65 else 0,
        "meta_title_warnings": 1 if meta_title_chars and meta_title_chars > 60 else 0,
        "meta_description_warnings": 1 if meta_description_chars and meta_description_chars > 160 else 0,
        "removed_shipping_marketing_phrase_count": summary.get("removed_shipping_marketing_phrase_count", 0),
        "removed_skipped_origin_field_count": summary.get("removed_skipped_origin_field_count", 0),
    }, True


def _write_review(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REVIEW_PATH.open("w", encoding="utf-8") as review_file:
        json.dump(payload, review_file, ensure_ascii=False, indent=2)
        review_file.write("\n")
    return REVIEW_PATH


def _build_approval_message(payload: dict, review_path: Path) -> str:
    return (
        "Shopify multi-locale translation dry-run completed.\n"
        f"Product ID: {payload.get('product_id')}\n"
        f"Locales: {', '.join(payload.get('locales') or [])}\n"
        f"Success count: {payload.get('success_count')}\n"
        f"Failed count: {payload.get('failed_count')}\n"
        f"Skipped count: {payload.get('skipped_count')}\n"
        f"Failed locales: {', '.join(payload.get('failed_locales') or []) or 'none'}\n"
        f"Warnings: {payload.get('warnings_count')}\n"
        f"Review file: {review_path}\n"
        "No Shopify writes confirmed for successful locales: "
        f"{payload.get('all_no_write_confirmed')}\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep review files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Write, publish, apply, update, commit, and push are not allowed for this dry-run task."
    )


def _tail_lines(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-max_lines:])


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _count_warning_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if "warning" in line.lower())


def _review_paths(locale: str) -> dict:
    review_file_name = f"shopify_translation_command_review_{locale}.json"
    host_review_path = PROJECT_ROOT / "backend" / "logs" / review_file_name
    return {
        "review_file_path": str(host_review_path),
        "host_review_file_path": str(host_review_path),
        "container_review_file_path": f"/app/logs/{review_file_name}",
    }


def _validate_glossary(locale: str) -> str:
    path = GLOSSARY_PATHS[locale]
    if not path.exists():
        return f"Glossary file is missing: {path}"
    try:
        with path.open("r", encoding="utf-8") as glossary_file:
            json.load(glossary_file)
    except (json.JSONDecodeError, OSError) as exc:
        return f"Glossary file is invalid JSON: {path}. Error: {exc}"
    return ""


def _failed_locale_result(
    locale: str,
    language_name: str,
    failure_type: str,
    failure_reason: str,
    review_paths: dict | None = None,
) -> dict:
    paths = review_paths or {"review_file_path": "", "host_review_file_path": "", "container_review_file_path": ""}
    return {
        "locale": locale,
        "language_name": language_name,
        "success": False,
        "exit_code": None,
        "skipped": False,
        "failure_type": failure_type,
        "failure_reason": failure_reason,
        "permission_denied": failure_type == "docker_permission_denied",
        "timed_out": failure_type == "timeout",
        "duration_seconds": 0,
        "review_file_path": paths["review_file_path"],
        "host_review_file_path": paths["host_review_file_path"],
        "container_review_file_path": paths["container_review_file_path"],
        "review_file_exists": False,
        "review_file_fresh": False,
        "stdout_tail": "",
        "stderr_tail": failure_reason,
        "warnings_count": 0,
        "title_length_warnings": 0,
        "meta_title_warnings": 0,
        "meta_description_warnings": 0,
        "removed_shipping_marketing_phrase_count": 0,
        "removed_skipped_origin_field_count": 0,
        "no_shopify_writes_confirmed": False,
        "no_shopify_writes_performed": False,
    }


def _classify_failure(exit_code: int, timed_out: bool, permission_denied: bool) -> str:
    if timed_out:
        return "timeout"
    if permission_denied:
        return "docker_permission_denied"
    if exit_code in (126, 127):
        return "command_error"
    return "command_error" if exit_code else "unknown"


def _failure_reason(exit_code: int, timed_out: bool, permission_denied: bool, stderr_tail: str) -> str:
    if timed_out:
        return f"Command timed out after {TIMEOUT_SECONDS} seconds."
    if permission_denied:
        return "Docker permission denied. Use administrator PowerShell if Docker access is required."
    if stderr_tail:
        return stderr_tail
    return f"Command failed with exit code {exit_code}."


def _build_issue_summary(locale_results: list[dict], all_success: bool, all_no_write_confirmed: bool) -> str:
    if not locale_results:
        return "No locales were configured for Shopify multi-locale translation dry-run."
    if all_success and all_no_write_confirmed:
        return "All locale dry-runs completed, and all successful locales confirmed no Shopify writes."
    if all_success:
        return "All locale dry-runs completed, but no-write confirmation was missing for at least one locale."
    failure_types = sorted({item["failure_type"] for item in locale_results if item.get("failure_type")})
    return "One or more locale dry-runs failed. Failure types: " + ", ".join(failure_types)
