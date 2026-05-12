import json
import re
import subprocess
import time
from html import escape
from html.parser import HTMLParser
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, load_env, utc_now_iso


class ReviewJsonInvalidError(RuntimeError):
    pass


TASK_NAME = "shopify_translation_batch_multi_locale_dry_run"
COMMAND_LABEL = "docker_compose_web_translate_shopify_product_batch_multi_locale_dry_run"
REVIEW_PATH = LOG_DIR / "shopify_translation_batch_multi_locale_dry_run_review.json"
HTML_REVIEW_PATH = LOG_DIR / "shopify_translation_batch_multi_locale_dry_run_review.html"
PRODUCT_IDS_FILE_PATH = PROJECT_ROOT / "backend" / "reviews" / "translation_product_ids.txt"
DEFAULT_LOCALES = ["de", "fr", "es", "it", "ja"]
SUPPORTED_LOCALES = {
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "ja": "Japanese",
}
MAX_PRODUCTS = 3
MAX_LOCALES = 5
TIMEOUT_SECONDS = 420
TAIL_LINES = 120
PRODUCT_ID_RE = re.compile(r"^(?:\d+|gid://shopify/Product/\d+)$")
PRODUCT_KEY_RE = re.compile(r"(\d+)$")
PERMISSION_DENIED_RE = re.compile(r"(access is denied|permission denied|docker_engine)", re.IGNORECASE)
DRY_RUN_NO_WRITE_PHRASE = "Dry run complete. No Shopify writes performed."
TRANSLATION_KEYS = ("title", "body_html", "meta_title", "meta_description")
MAX_PRODUCT_TITLE_CHARS = 65
MAX_META_TITLE_CHARS = 60
MAX_META_DESCRIPTION_CHARS = 160
URL_TEXT_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"</?([A-Za-z][A-Za-z0-9:-]*)\b")
JSON_UNSAFE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MOJIBAKE_RE = re.compile(
    r"("
    r"�|Ã.|Â.|â[€\u0080-\u00BF]?|"
    r"鈥|檃|茅|贸|铆|谩|聽|莽|锚|卯|"
    r"盲|眉|脽|枚|脿|脰|脺|"
    r"銉|儵|偍|笺|伄|伀|鍐|绶|姗|鐢|瑁|鍙|淇|瀵|儹|儶|兂|偗|偪|偣|"
    r"縺|蜊|譁|譛|荳|蟆"
    r")"
)
FORBIDDEN_SHIPPING_ORIGIN_RE = re.compile(
    r"("
    r"made\s+in\s+china|mainland\s+china|shipping\s+origin|"
    r"\borigin\s*:|\bsource\s*:|herkunft\s*:|origine\s*:|origen\s*:|"
    r"worldwide\s+shipping|ships\s+worldwide|shipping\s+worldwide|"
    r"weltweiter\s+versand|versand\s+weltweit|lieferung\s+weltweit|"
    r"livraison\s+mondiale|exp[eé]dition\s+mondiale|"
    r"env[ií]o\s+mundial|env[ií]os\s+a\s+todo\s+el\s+mundo|"
    r"spedizione\s+mondiale|spedizione\s+in\s+tutto\s+il\s+mondo|"
    r"世界中に発送|送料無料|中国製|中国大陆"
    r")",
    re.IGNORECASE,
)
FORBIDDEN_CTA_RE = re.compile(
    r"("
    r"buy\s+now|shop\s+now|order\s+now|"
    r"jetzt\s+kaufen|kaufen\s+sie\s+jetzt|"
    r"achetez\s+maintenant|acheter\s+maintenant|"
    r"comprar\s+ahora|compra\s+ahora|"
    r"acquista\s+ora|compra\s+ora|"
    r"今すぐ購入|今すぐ買う"
    r")",
    re.IGNORECASE,
)
FORBIDDEN_MILITARY_RE = re.compile(
    r"("
    r"battle\s+force|combat\s+power|dominate\s+the\s+sky|military\s+mission|"
    r"kampfkraft|dominieren|milit[äa]rische\s+eins[aä]tze|kampfeins[aä]tze|"
    r"force\s+de\s+combat|dominer\s+le\s+ciel|"
    r"fuerza\s+de\s+combate|dominar\s+el\s+cielo|"
    r"forza\s+di\s+combattimento|dominare\s+il\s+cielo|"
    r"戦闘力|空を支配"
    r")",
    re.IGNORECASE,
)
GLOSSARY_PATHS = {
    "de": PROJECT_ROOT / "backend" / "shopify_sync" / "translation_glossary_de.json",
    "fr": PROJECT_ROOT / "backend" / "shopify_sync" / "translation_glossary_fr.json",
    "es": PROJECT_ROOT / "backend" / "shopify_sync" / "translation_glossary_es.json",
    "it": PROJECT_ROOT / "backend" / "shopify_sync" / "translation_glossary_it.json",
    "ja": PROJECT_ROOT / "backend" / "shopify_sync" / "translation_glossary_ja.json",
}


def run_shopify_translation_batch_multi_locale_dry_run_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    env = load_env(
        [
            "SHOPIFY_TRANSLATION_TEST_PRODUCT_IDS",
            "SHOPIFY_TRANSLATION_TEST_PRODUCT_ID",
            "SHOPIFY_TRANSLATION_TEST_LOCALES",
        ]
    )
    product_input = _configured_product_input(env)
    product_ids = product_input["product_ids"]
    invalid_product_ids = product_input["invalid_product_ids"]
    locales = _configured_locales(env.get("SHOPIFY_TRANSLATION_TEST_LOCALES", ""))
    results = []

    preflight_failure = _limit_failure(product_ids, locales)
    for invalid_product_id in invalid_product_ids:
        results.append(
            _failed_result(
                product_id=invalid_product_id,
                locale="",
                failure_type="invalid_product_id",
                failure_reason="Invalid product ID format. Use a numeric product ID or gid://shopify/Product/<id>.",
                skipped=True,
            )
        )

    if preflight_failure:
        results.append(preflight_failure)
    elif not product_ids:
        if not invalid_product_ids:
            results.append(
                _failed_result(
                    product_id="",
                    locale="",
                    failure_type="missing_product_id",
                    failure_reason=(
                        "Set SHOPIFY_TRANSLATION_TEST_PRODUCT_IDS, add IDs to "
                        "backend/reviews/translation_product_ids.txt, or set SHOPIFY_TRANSLATION_TEST_PRODUCT_ID. "
                        "No Shopify translation dry-run command was executed."
                    ),
                    skipped=True,
                )
            )
    else:
        for product_id in product_ids:
            for locale in locales:
                results.append(_run_or_preflight_result(product_id, locale))

    success_count = sum(1 for item in results if item["success"])
    failed_count = len(results) - success_count
    skipped_count = sum(1 for item in results if item.get("skipped"))
    all_success = bool(results) and failed_count == 0
    successful_results = [item for item in results if item["success"]]
    all_no_write_confirmed = bool(successful_results) and all(
        item["no_shopify_writes_confirmed"] for item in successful_results
    )
    qa_status_counts = _qa_status_counts(results)
    qa_gate_passed = bool(results) and qa_status_counts["fail"] == 0
    all_qa_pass = bool(results) and qa_status_counts["fail"] == 0 and qa_status_counts["warning"] == 0
    failed_items = [
        {
            "product_id": item["product_id"],
            "locale": item["locale"],
            "failure_type": item["failure_type"],
        }
        for item in results
        if not item["success"]
    ]
    warning_items = [
        {
            "product_id": item["product_id"],
            "locale": item["locale"],
            "warnings_count": item["warnings_count"],
            "qa_status": item.get("qa_status", ""),
            "qa_warnings_count": len(item.get("qa_warnings", [])),
            "qa_failures_count": len(item.get("qa_failures", [])),
        }
        for item in results
        if item["warnings_count"] or item.get("qa_status") in {"warning", "fail"}
    ]
    qa_failed_items = [
        {
            "product_id": item["product_id"],
            "locale": item["locale"],
            "qa_status": item.get("qa_status", ""),
            "qa_failures": item.get("qa_failures", []),
        }
        for item in results
        if item.get("qa_status") == "fail"
    ]
    qa_warning_items = [
        {
            "product_id": item["product_id"],
            "locale": item["locale"],
            "qa_status": item.get("qa_status", ""),
            "qa_warnings": item.get("qa_warnings", []),
        }
        for item in results
        if item.get("qa_status") == "warning"
    ]

    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "mode": mode,
        "command_label": COMMAND_LABEL,
        "json_review_path": str(REVIEW_PATH),
        "html_review_path": str(HTML_REVIEW_PATH),
        "product_input_source": product_input["source"],
        "product_input_file_path": str(PRODUCT_IDS_FILE_PATH),
        "product_ids": product_ids,
        "invalid_product_ids": invalid_product_ids,
        "locales": locales,
        "product_count": len(product_ids),
        "locale_count": len(locales),
        "total_runs": len(results),
        "success_count": success_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "failed_items": failed_items,
        "warning_items": warning_items,
        "qa_failed_items": qa_failed_items,
        "qa_warning_items": qa_warning_items,
        "all_success": all_success,
        "all_no_write_confirmed": all_no_write_confirmed,
        "no_shopify_writes_performed": all_no_write_confirmed,
        "warnings_count": sum(item["warnings_count"] for item in results),
        "qa_status_counts": qa_status_counts,
        "qa_pass_count": qa_status_counts["pass"],
        "qa_warning_count": qa_status_counts["warning"],
        "qa_fail_count": qa_status_counts["fail"],
        "qa_gate_passed": qa_gate_passed,
        "all_qa_pass": all_qa_pass,
        "per_product_summary": _per_product_summary(product_ids, results),
        "per_locale_summary": _per_locale_summary(locales, results),
        "results": results,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
        "review_json_valid": True,
        "review_json_error": "",
        "review_json_validation": "json.loads after write",
        "detected_issue_summary": _build_issue_summary(
            results, all_success, all_no_write_confirmed, qa_status_counts
        ),
        "safety": {
            "dry_run_only": True,
            "max_products": MAX_PRODUCTS,
            "max_locales": MAX_LOCALES,
            "shopify_writes_allowed": False,
            "register_translations_allowed": False,
            "publish_allowed": False,
            "database_writes_allowed": False,
            "git_push_allowed": False,
            "auto_scan_all_products_allowed": False,
        },
    }
    try:
        review_path = _write_review(payload)
    except ReviewJsonInvalidError as exc:
        payload["review_json_valid"] = False
        payload["review_json_error"] = str(exc)
        payload["detected_issue_summary"] = f"review_json_invalid: {exc}"
        html_review_path = write_batch_review_html(payload, HTML_REVIEW_PATH)
        return {
            "task_type": TASK_NAME,
            "success": False,
            "exit_code": 1,
            "products_checked": len(product_ids),
            "failed_count": failed_count,
            "failure_type": "review_json_invalid",
            "all_no_write_confirmed": all_no_write_confirmed,
            "warnings_count": payload["warnings_count"],
            "qa_gate_passed": False,
            "qa_pass_count": payload["qa_pass_count"],
            "qa_warning_count": payload["qa_warning_count"],
            "qa_fail_count": payload["qa_fail_count"],
            "command_label": COMMAND_LABEL,
            "review_path": str(REVIEW_PATH),
            "json_review_path": str(REVIEW_PATH),
            "html_review_path": str(html_review_path),
            "detected_issue_summary": payload["detected_issue_summary"],
            "approval_message": _build_approval_message(payload, REVIEW_PATH, html_review_path),
        }
    html_review_path = write_batch_review_html(payload, HTML_REVIEW_PATH)
    return {
        "task_type": TASK_NAME,
        "success": all_success and all_no_write_confirmed and qa_gate_passed,
        "exit_code": 0 if (all_success and all_no_write_confirmed and qa_gate_passed) else 1,
        "products_checked": len(product_ids) if all_success else success_count,
        "failed_count": failed_count,
        "all_no_write_confirmed": all_no_write_confirmed,
        "warnings_count": payload["warnings_count"],
        "qa_gate_passed": qa_gate_passed,
        "qa_pass_count": payload["qa_pass_count"],
        "qa_warning_count": payload["qa_warning_count"],
        "qa_fail_count": payload["qa_fail_count"],
        "command_label": COMMAND_LABEL,
        "review_path": str(review_path),
        "json_review_path": str(review_path),
        "html_review_path": str(html_review_path),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, review_path, html_review_path),
}


def _configured_product_input(env: dict[str, str]) -> dict:
    raw_multi = (env.get("SHOPIFY_TRANSLATION_TEST_PRODUCT_IDS") or "").strip()
    if raw_multi:
        product_ids, invalid_product_ids = _parse_product_id_items(raw_multi.split(","))
        return {
            "source": "env_multi",
            "product_ids": product_ids,
            "invalid_product_ids": invalid_product_ids,
        }
    if PRODUCT_IDS_FILE_PATH.exists():
        product_ids, invalid_product_ids = _parse_product_id_file(PRODUCT_IDS_FILE_PATH)
        return {
            "source": "file",
            "product_ids": product_ids,
            "invalid_product_ids": invalid_product_ids,
        }
    raw_single = (env.get("SHOPIFY_TRANSLATION_TEST_PRODUCT_ID") or "").strip()
    product_ids, invalid_product_ids = _parse_product_id_items([raw_single] if raw_single else [])
    return {
        "source": "env_single",
        "product_ids": product_ids,
        "invalid_product_ids": invalid_product_ids,
    }


def _parse_product_id_file(path: Path) -> tuple[list[str], list[str]]:
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return [], [str(path)]
    items = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(line)
    return _parse_product_id_items(items)


def _parse_product_id_items(items: list[str]) -> tuple[list[str], list[str]]:
    product_ids = []
    invalid_product_ids = []
    for raw_item in items:
        product_id = raw_item.strip()
        if not product_id:
            continue
        if PRODUCT_ID_RE.match(product_id):
            if product_id not in product_ids:
                product_ids.append(product_id)
        elif product_id not in invalid_product_ids:
            invalid_product_ids.append(product_id)
    return product_ids, invalid_product_ids


def _configured_locales(raw_value: str) -> list[str]:
    if not raw_value.strip():
        return DEFAULT_LOCALES[:]
    locales = []
    for item in raw_value.split(","):
        locale = item.strip().lower()
        if locale and locale not in locales:
            locales.append(locale)
    return locales or DEFAULT_LOCALES[:]


def _limit_failure(product_ids: list[str], locales: list[str]) -> dict | None:
    if len(product_ids) > MAX_PRODUCTS:
        return _failed_result(
            product_id="",
            locale="",
            failure_type="product_limit_exceeded",
            failure_reason=f"Configured {len(product_ids)} products. Reduce to {MAX_PRODUCTS} or fewer.",
            skipped=True,
        )
    if len(locales) > MAX_LOCALES:
        return _failed_result(
            product_id="",
            locale="",
            failure_type="locale_limit_exceeded",
            failure_reason=f"Configured {len(locales)} locales. Reduce to {MAX_LOCALES} or fewer.",
            skipped=True,
        )
    return None


def _run_or_preflight_result(product_id: str, locale: str) -> dict:
    if not PRODUCT_ID_RE.match(product_id):
        return _failed_result(
            product_id=product_id,
            locale=locale,
            failure_type="invalid_product_id",
            failure_reason="Invalid product ID format. Use a numeric product ID or gid://shopify/Product/<id>.",
            review_paths=_review_paths(product_id, locale),
            skipped=True,
        )
    if locale not in SUPPORTED_LOCALES:
        return _failed_result(
            product_id=product_id,
            locale=locale,
            failure_type="unsupported_locale",
            failure_reason=f"Unsupported locale '{locale}'. Supported locales: {', '.join(DEFAULT_LOCALES)}.",
            review_paths=_review_paths(product_id, locale),
            skipped=True,
        )
    glossary_error = _validate_glossary(locale)
    if glossary_error:
        return _failed_result(
            product_id=product_id,
            locale=locale,
            failure_type="glossary_invalid",
            failure_reason=glossary_error,
            review_paths=_review_paths(product_id, locale),
            skipped=True,
        )
    return _run_product_locale(product_id, locale)


def _run_product_locale(product_id: str, locale: str) -> dict:
    started = time.time()
    review_paths = _review_paths(product_id, locale)
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
        stderr = (stderr + "\n" if stderr else "") + (
            f"Product {product_id} locale {locale} timed out after {TIMEOUT_SECONDS} seconds."
        )

    stdout_tail = _tail_lines(stdout, TAIL_LINES)
    stderr_tail = _tail_lines(stderr, TAIL_LINES)
    combined_tail = stdout_tail + "\n" + stderr_tail
    permission_denied = bool(PERMISSION_DENIED_RE.search(combined_tail))
    command_review, review_file_fresh = _parse_command_review(host_review_path, started)
    success = exit_code == 0
    no_write_confirmed = success and DRY_RUN_NO_WRITE_PHRASE in stdout
    result = {
        "product_id": product_id,
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
        "payload_keys": command_review.get("payload_keys", []),
        "title_chars": command_review.get("title_chars", 0),
        "meta_title_chars": command_review.get("meta_title_chars", 0),
        "meta_description_chars": command_review.get("meta_description_chars", 0),
        "source_meta_description_chars": command_review.get("source_meta_description_chars", 0),
        "translated_text_node_count": command_review.get("translated_text_node_count", 0),
        "translated_img_alt_count": command_review.get("translated_img_alt_count", 0),
        "img_alt_chars_list": command_review.get("img_alt_chars_list", []),
        "removed_shipping_marketing_phrase_count": command_review.get(
            "removed_shipping_marketing_phrase_count", 0
        ),
        "removed_skipped_origin_field_count": command_review.get("removed_skipped_origin_field_count", 0),
        "no_shopify_writes_confirmed": no_write_confirmed,
        "no_shopify_writes_performed": no_write_confirmed,
    }
    return _with_qa(result, command_review)


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
    translation_values = _translation_values(data)
    source_values = {
        key: str(value)
        for key, value in (data.get("source") or {}).items()
        if key in TRANSLATION_KEYS and value is not None
    }
    payload_keys = summary.get("payload_keys") or _payload_keys(data.get("payload_preview") or [])
    title_chars = summary.get("title_chars") or 0
    meta_title_chars = summary.get("meta_title_chars") or 0
    meta_description_chars = summary.get("meta_description_chars") or 0
    return {
        "dry_run": data.get("dry_run"),
        "warnings_count": len(warnings),
        "warnings": warnings,
        "payload_keys": list(payload_keys),
        "title_chars": title_chars,
        "meta_title_chars": meta_title_chars,
        "meta_description_chars": meta_description_chars,
        "source_meta_description_chars": summary.get("source_meta_description_chars", 0),
        "source_meta_description_over_limit": bool(summary.get("source_meta_description_over_limit")),
        "translated_text_node_count": summary.get("translated_text_node_count", 0),
        "translated_img_alt_count": summary.get("translated_img_alt_count", 0),
        "img_alt_chars_list": summary.get("img_alt_chars_list", []),
        "translation_values": translation_values,
        "source_values": source_values,
        "title_length_warnings": 1 if title_chars and title_chars > 65 else 0,
        "meta_title_warnings": 1 if meta_title_chars and meta_title_chars > 60 else 0,
        "meta_description_warnings": 1 if meta_description_chars and meta_description_chars > 160 else 0,
        "removed_shipping_marketing_phrase_count": summary.get("removed_shipping_marketing_phrase_count", 0),
        "removed_skipped_origin_field_count": summary.get("removed_skipped_origin_field_count", 0),
    }, True


def _translation_values(review_data: dict) -> dict[str, str]:
    translation = review_data.get("translation") or {}
    payload_values = {}
    for item in review_data.get("payload_preview") or []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        if key in TRANSLATION_KEYS and value is not None:
            payload_values[key] = str(value)

    values = {}
    for key in TRANSLATION_KEYS:
        value = translation.get(key) if isinstance(translation, dict) else None
        if value is None:
            value = payload_values.get(key)
        if value is not None:
            values[key] = str(value)
    return values


def _payload_keys(payload_preview: list) -> list[str]:
    keys = []
    for item in payload_preview:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if key and key not in keys:
            keys.append(str(key))
    return keys


def _with_qa(result: dict, command_review: dict | None = None) -> dict:
    result.update(_evaluate_qa_gates(result, command_review or {}))
    return result


def _evaluate_qa_gates(result: dict, command_review: dict) -> dict:
    checks = {}
    qa_warnings = []
    qa_failures = []

    def record(name: str, status: str, message: str = "") -> None:
        checks[name] = status
        if message and status == "warning":
            qa_warnings.append(message)
        elif message and status == "fail":
            qa_failures.append(message)

    if not result.get("success"):
        record("command_success", "fail", f"Dry-run command failed: {result.get('failure_type') or 'unknown'}.")
        record("no_write_confirmed", "fail", "No-write confirmation is unavailable because the command did not finish.")
        return _qa_result(
            checks,
            qa_warnings,
            qa_failures,
            {"mojibake_issue_count": 0, "mojibake_samples": []},
        )

    record("command_success", "pass")
    record(
        "review_file_fresh",
        "pass" if result.get("review_file_fresh") else "fail",
        "" if result.get("review_file_fresh") else "Per-product/locale review file was missing or stale.",
    )
    record(
        "no_write_confirmed",
        "pass" if result.get("no_shopify_writes_confirmed") else "fail",
        "" if result.get("no_shopify_writes_confirmed") else "Dry-run output did not confirm no Shopify writes.",
    )

    payload_keys = command_review.get("payload_keys") or result.get("payload_keys") or []
    translation_values = command_review.get("translation_values") or {}
    source_values = command_review.get("source_values") or {}
    output_text = _qa_output_text(translation_values)

    title_chars = _int_value(result.get("title_chars"))
    meta_title_chars = _int_value(result.get("meta_title_chars"))
    meta_description_chars = _int_value(result.get("meta_description_chars"))

    record(
        "title_length",
        "warning" if title_chars > MAX_PRODUCT_TITLE_CHARS else "pass",
        (
            f"Product title is {title_chars} chars; recommended limit is {MAX_PRODUCT_TITLE_CHARS}."
            if title_chars > MAX_PRODUCT_TITLE_CHARS
            else ""
        ),
    )
    record(
        "meta_title_length",
        "fail" if meta_title_chars > MAX_META_TITLE_CHARS else "pass",
        (
            f"Meta title is {meta_title_chars} chars; hard limit is {MAX_META_TITLE_CHARS}."
            if meta_title_chars > MAX_META_TITLE_CHARS
            else ""
        ),
    )
    record(
        "meta_description_length",
        "fail" if meta_description_chars > MAX_META_DESCRIPTION_CHARS else "pass",
        (
            f"Meta description is {meta_description_chars} chars; hard limit is {MAX_META_DESCRIPTION_CHARS}."
            if meta_description_chars > MAX_META_DESCRIPTION_CHARS
            else ""
        ),
    )

    body_html = translation_values.get("body_html", "")
    if "body_html" in payload_keys:
        record(
            "body_html_present",
            "pass" if body_html.strip() else "fail",
            "" if body_html.strip() else "body_html is selected but translated output is empty.",
        )
    else:
        record("body_html_present", "warning", "body_html was not included in the dry-run payload.")

    has_forbidden_shipping_origin = bool(FORBIDDEN_SHIPPING_ORIGIN_RE.search(output_text))
    record(
        "forbidden_shipping_origin_phrases",
        "fail" if has_forbidden_shipping_origin else "pass",
        "Translated output contains forbidden shipping/origin/source wording."
        if has_forbidden_shipping_origin
        else "",
    )
    has_forbidden_cta = bool(FORBIDDEN_CTA_RE.search(output_text))
    record(
        "forbidden_cta_phrases",
        "fail" if has_forbidden_cta else "pass",
        "Translated output contains forbidden CTA wording such as Buy now / Shop now."
        if has_forbidden_cta
        else "",
    )
    has_forbidden_military = bool(FORBIDDEN_MILITARY_RE.search(output_text))
    record(
        "forbidden_military_exaggeration",
        "fail" if has_forbidden_military else "pass",
        "Translated output contains exaggerated military/combat wording." if has_forbidden_military else "",
    )
    mojibake_result = _mojibake_result(output_text)
    record("mojibake_detected", mojibake_result["status"], mojibake_result["message"])

    image_alt_result = _image_alt_result(body_html)
    if image_alt_result["image_count"] and image_alt_result["missing_alt_count"]:
        record(
            "alt_text_present",
            "warning",
            (
                f"{image_alt_result['missing_alt_count']} of {image_alt_result['image_count']} image tag(s) "
                "have missing or empty alt text."
            ),
        )
    else:
        record("alt_text_present", "pass")

    if "body_html" in payload_keys:
        html_status, html_message = _html_structure_check(source_values.get("body_html", ""), body_html)
        record("html_structure_preserved", html_status, html_message)
    else:
        record("html_structure_preserved", "warning", "body_html was not available for HTML structure QA.")

    if command_review.get("source_meta_description_over_limit"):
        qa_warnings.append("Source meta_description is over the recommended limit; translated output still passed gates.")
    command_warning_count = _int_value(result.get("warnings_count"))
    if command_warning_count:
        qa_warnings.append(f"Translation command emitted {command_warning_count} warning(s).")

    return _qa_result(
        checks,
        qa_warnings,
        qa_failures,
        {
            "mojibake_issue_count": mojibake_result["issue_count"],
            "mojibake_samples": mojibake_result["samples"],
        },
    )


def _qa_result(
    checks: dict,
    qa_warnings: list[str],
    qa_failures: list[str],
    extra: dict | None = None,
) -> dict:
    if qa_failures:
        status = "fail"
    elif qa_warnings:
        status = "warning"
    else:
        status = "pass"
    result = {
        "qa_status": status,
        "qa_warnings": qa_warnings,
        "qa_failures": qa_failures,
        "qa_checks": checks,
    }
    if extra:
        result.update(extra)
    return result


def _qa_status_counts(results: list[dict]) -> dict:
    return {
        "pass": sum(1 for item in results if item.get("qa_status") == "pass"),
        "warning": sum(1 for item in results if item.get("qa_status") == "warning"),
        "fail": sum(1 for item in results if item.get("qa_status") == "fail"),
    }


def _qa_output_text(translation_values: dict[str, str]) -> str:
    parts = []
    for key in ("title", "meta_title", "meta_description"):
        value = translation_values.get(key, "")
        if value:
            parts.append(value)
    body_html = translation_values.get("body_html", "")
    if body_html:
        parts.append(_html_visible_text(body_html))
    return URL_TEXT_RE.sub(" ", "\n".join(parts))


def _mojibake_result(text: str) -> dict:
    if not text:
        return {"status": "pass", "issue_count": 0, "samples": [], "message": ""}
    matches = [match.group(0) for match in MOJIBAKE_RE.finditer(text)]
    if not matches:
        return {"status": "pass", "issue_count": 0, "samples": [], "message": ""}

    samples = []
    for marker in matches:
        if marker not in samples:
            samples.append(marker)
        if len(samples) >= 8:
            break
    issue_count = len(matches)
    status = "fail" if issue_count >= 2 or any(marker in {"�", "銉", "盲", "眉", "鈥"} for marker in samples) else "warning"
    message = (
        f"Possible mojibake/encoding corruption detected: {issue_count} marker(s), "
        f"samples: {', '.join(samples)}."
    )
    return {
        "status": status,
        "issue_count": issue_count,
        "samples": samples,
        "message": message,
    }


def _html_visible_text(html: str) -> str:
    parser = _VisibleTextParser()
    try:
        parser.feed(html or "")
    except Exception:
        return re.sub(r"<[^>]+>", " ", html or "")
    return " ".join(part.strip() for part in parser.parts if part.strip())


def _image_alt_result(html: str) -> dict:
    parser = _ImageAltParser()
    try:
        parser.feed(html or "")
    except Exception:
        return {"image_count": 0, "missing_alt_count": 0, "alt_chars": []}
    return {
        "image_count": parser.image_count,
        "missing_alt_count": parser.missing_alt_count,
        "alt_chars": parser.alt_chars,
    }


def _html_structure_check(source_body: str, translated_body: str) -> tuple[str, str]:
    if not translated_body.strip():
        return "fail", "Translated body_html is empty."
    source_tags = _html_tag_names(source_body)
    translated_tags = _html_tag_names(translated_body)
    if source_tags and not translated_tags:
        return "fail", "Translated body_html no longer contains HTML tags."
    if source_tags and translated_tags and source_tags[0] != translated_tags[0]:
        return "warning", f"First HTML tag changed from {source_tags[0]} to {translated_tags[0]}."
    if source_tags and translated_tags:
        lower_bound = max(1, int(len(source_tags) * 0.7))
        upper_bound = max(lower_bound, int(len(source_tags) * 1.3) + 1)
        if len(translated_tags) < lower_bound or len(translated_tags) > upper_bound:
            return (
                "warning",
                f"HTML tag count changed from {len(source_tags)} to {len(translated_tags)}; review structure.",
            )
    return "pass", ""


def _html_tag_names(html: str) -> list[str]:
    return [match.group(1).lower() for match in HTML_TAG_RE.finditer(html or "")]


def _int_value(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class _VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        if data:
            self.parts.append(data)


class _ImageAltParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.image_count = 0
        self.missing_alt_count = 0
        self.alt_chars = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "img":
            return
        self.image_count += 1
        attrs_by_name = {name.lower(): value for name, value in attrs}
        alt = (attrs_by_name.get("alt") or "").strip()
        if not alt:
            self.missing_alt_count += 1
        else:
            self.alt_chars.append(len(alt))


def _write_review(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe_payload = _sanitize_for_json(payload)
    review_text = json.dumps(safe_payload, ensure_ascii=True, indent=2) + "\n"
    _validate_review_json_text(review_text)
    REVIEW_PATH.write_text(review_text, encoding="utf-8")
    _validate_review_json_text(REVIEW_PATH.read_text(encoding="utf-8"))
    return REVIEW_PATH


def _validate_review_json_text(review_text: str) -> None:
    try:
        json.loads(review_text)
    except json.JSONDecodeError as exc:
        raise ReviewJsonInvalidError(
            f"review_json_invalid at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def _sanitize_for_json(value):
    if isinstance(value, str):
        return _sanitize_json_string(value)
    if isinstance(value, list):
        return [_sanitize_for_json(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_for_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_for_json(item) for key, item in value.items()}
    return value


def _sanitize_json_string(value: str) -> str:
    return JSON_UNSAFE_CONTROL_RE.sub(lambda match: f"\\u{ord(match.group(0)):04x}", value)


def write_batch_review_html(review_data: dict, html_path: Path) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    html_path.write_text(_render_batch_review_html(review_data), encoding="utf-8")
    return html_path


def _render_batch_review_html(review_data: dict) -> str:
    status_label, status_class, status_text = _dashboard_status(review_data)
    rows = "\n".join(_render_result_row(item) for item in review_data.get("results", []))
    failed_rows = "\n".join(
        _render_failed_row(item) for item in review_data.get("results", []) if not item.get("success")
    )
    warning_rows = "\n".join(
        _render_warning_row(item)
        for item in review_data.get("results", [])
        if item.get("warnings_count") or item.get("qa_status") in {"warning", "fail"}
    )
    qa_rows = "\n".join(
        _render_qa_row(item) for item in review_data.get("results", []) if item.get("qa_status") != "pass"
    )
    review_links = "\n".join(_render_review_link(item) for item in review_data.get("results", []))
    summary_rows = "\n".join(
        _summary_row(label, review_data.get(key))
        for label, key in [
            ("Task", "task"),
            ("Timestamp", "timestamp"),
            ("Product Input Source", "product_input_source"),
            ("Product IDs", "product_ids"),
            ("Invalid Product IDs", "invalid_product_ids"),
            ("Product Count", "product_count"),
            ("Locale Count", "locale_count"),
            ("Total Runs", "total_runs"),
            ("Success Count", "success_count"),
            ("Failed Count", "failed_count"),
            ("Skipped Count", "skipped_count"),
            ("All Success", "all_success"),
            ("All No-Write Confirmed", "all_no_write_confirmed"),
            ("Warnings Count", "warnings_count"),
            ("QA Gate Passed", "qa_gate_passed"),
            ("All QA Pass", "all_qa_pass"),
            ("QA Pass Count", "qa_pass_count"),
            ("QA Warning Count", "qa_warning_count"),
            ("QA Fail Count", "qa_fail_count"),
        ]
    )
    json_link = _link_for_path(review_data.get("json_review_path", ""))
    html_link = _link_for_path(review_data.get("html_review_path", ""))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Batch Translation Dry-Run Review</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; background: #fff; }}
    h1, h2 {{ margin-top: 1.4em; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f6f8fa; }}
    .status {{ padding: 12px 14px; border-radius: 6px; font-weight: 700; margin: 12px 0; }}
    .status.pass {{ background: #dafbe1; color: #116329; }}
    .status.review {{ background: #fff8c5; color: #7d4e00; }}
    .status.fail {{ background: #ffebe9; color: #82071e; }}
    .qa-pass {{ color: #116329; font-weight: 700; }}
    .qa-warning {{ color: #7d4e00; font-weight: 700; }}
    .qa-fail {{ color: #82071e; font-weight: 700; }}
    .tail {{ max-width: 520px; white-space: pre-wrap; overflow-wrap: anywhere; font-family: Consolas, monospace; font-size: 12px; }}
    .path {{ font-family: Consolas, monospace; overflow-wrap: anywhere; }}
    .empty {{ color: #57606a; }}
  </style>
</head>
<body>
  <h1>Shopify Batch Multi-Locale Translation Dry-Run Review</h1>
  <div class="status {status_class}">{escape(status_label)}: {escape(status_text)}</div>
  <h2>Summary</h2>
  <table>
    <tbody>
      {summary_rows}
      <tr><th>JSON Review</th><td>{json_link}</td></tr>
      <tr><th>HTML Review</th><td>{html_link}</td></tr>
    </tbody>
  </table>
  <h2>Product x Locale Results</h2>
  <table>
    <thead>
      <tr>
        <th>Product ID</th><th>Locale</th><th>Success</th><th>QA Status</th><th>Failure Type</th>
        <th>Warnings</th><th>QA Warnings</th><th>QA Failures</th>
        <th>No Shopify Writes Confirmed</th><th>Review File</th>
        <th>stdout Tail Summary</th><th>stderr Tail Summary</th>
      </tr>
    </thead>
    <tbody>{rows or _empty_row(12, "No product/locale results.")}</tbody>
  </table>
  <h2>Failed Items</h2>
  <table>
    <thead><tr><th>Product ID</th><th>Locale</th><th>Failure Type</th><th>stderr Tail</th></tr></thead>
    <tbody>{failed_rows or _empty_row(4, "No failed items.")}</tbody>
  </table>
  <h2>Warning Items</h2>
  <table>
    <thead><tr><th>Product ID</th><th>Locale</th><th>Warning Summary</th></tr></thead>
    <tbody>{warning_rows or _empty_row(3, "No warnings.")}</tbody>
  </table>
  <h2>QA Gate Items</h2>
  <table>
    <thead><tr><th>Product ID</th><th>Locale</th><th>QA Status</th><th>Warnings</th><th>Failures</th><th>Checks</th></tr></thead>
    <tbody>{qa_rows or _empty_row(6, "All QA gates passed without warnings.")}</tbody>
  </table>
  <h2>Review Links</h2>
  <ul>{review_links or '<li class="empty">No per-item review links.</li>'}</ul>
  <h2>Safety</h2>
  <ul>
    <li>This was a dry-run only.</li>
    <li>No Shopify writes were performed.</li>
    <li>Write/publish/apply/update actions are not available in this task.</li>
  </ul>
</body>
</html>
"""


def _build_approval_message(payload: dict, review_path: Path, html_review_path: Path) -> str:
    return (
        "Shopify batch multi-locale translation dry-run completed.\n"
        f"Products: {payload.get('product_count')}\n"
        f"Product input source: {payload.get('product_input_source')}\n"
        f"Locales: {', '.join(payload.get('locales') or [])}\n"
        f"Total runs: {payload.get('total_runs')}\n"
        f"Success count: {payload.get('success_count')}\n"
        f"Failed count: {payload.get('failed_count')}\n"
        f"Skipped count: {payload.get('skipped_count')}\n"
        f"Warnings: {payload.get('warnings_count')}\n"
        f"QA gate passed: {payload.get('qa_gate_passed')}\n"
        f"QA status counts: {payload.get('qa_status_counts')}\n"
        "Review JSON:\n"
        f"{review_path}\n\n"
        "Review HTML:\n"
        f"{html_review_path}\n"
        "No Shopify writes confirmed for successful runs: "
        f"{payload.get('all_no_write_confirmed')}\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep review files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Write, publish, apply, update, commit, and push are not allowed for this dry-run task."
    )


def _dashboard_status(review_data: dict) -> tuple[str, str, str]:
    if (
        review_data.get("failed_count", 0) > 0
        or not review_data.get("all_no_write_confirmed")
        or review_data.get("qa_fail_count", 0) > 0
    ):
        return "FAIL", "fail", "failed_count > 0, no-write confirmation is missing, or a QA gate failed."
    if review_data.get("warnings_count", 0) > 0 or review_data.get("qa_warning_count", 0) > 0:
        return "REVIEW", "review", "warnings or QA warnings exist; review translated output before any future write task."
    return "PASS", "pass", "all successful and all no-write confirmed."


def _render_result_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{_bool_text(item.get('success'))}</td>"
        f"<td>{_qa_status_label(item.get('qa_status'))}</td>"
        f"<td>{escape(str(item.get('failure_type') or ''))}</td>"
        f"<td>{escape(str(item.get('warnings_count', 0)))}</td>"
        f"<td>{escape(_compact_list(item.get('qa_warnings', [])))}</td>"
        f"<td>{escape(_compact_list(item.get('qa_failures', [])))}</td>"
        f"<td>{_bool_text(item.get('no_shopify_writes_confirmed'))}</td>"
        f"<td>{_link_for_path(item.get('review_file_path', ''))}</td>"
        f"<td><div class=\"tail\">{escape(_compact_tail(item.get('stdout_tail', '')))}</div></td>"
        f"<td><div class=\"tail\">{escape(_compact_tail(item.get('stderr_tail', '')))}</div></td>"
        "</tr>"
    )


def _render_failed_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{escape(str(item.get('failure_type') or ''))}</td>"
        f"<td><div class=\"tail\">{escape(_compact_tail(item.get('stderr_tail', '')))}</div></td>"
        "</tr>"
    )


def _render_warning_row(item: dict) -> str:
    summary = f"{item.get('warnings_count', 0)} warning(s)"
    if item.get("qa_status") in {"warning", "fail"}:
        summary += f"; qa_status={item.get('qa_status')}"
    if item.get("qa_warnings"):
        summary += f"; qa_warnings={len(item.get('qa_warnings', []))}"
    if item.get("qa_failures"):
        summary += f"; qa_failures={len(item.get('qa_failures', []))}"
    if item.get("failure_type"):
        summary += f"; failure_type={item.get('failure_type')}"
    return (
        "<tr>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{escape(summary)}</td>"
        "</tr>"
    )


def _render_qa_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{_qa_status_label(item.get('qa_status'))}</td>"
        f"<td>{escape(_compact_list(item.get('qa_warnings', []), max_chars=500))}</td>"
        f"<td>{escape(_compact_list(item.get('qa_failures', []), max_chars=500))}</td>"
        f"<td><div class=\"tail\">{escape(_format_checks(item.get('qa_checks', {})))}</div></td>"
        "</tr>"
    )


def _render_review_link(item: dict) -> str:
    path = item.get("review_file_path", "")
    if not path:
        return ""
    label = _project_relative_path(path)
    return f"<li>{_link_for_path(path, label)}</li>"


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _empty_row(colspan: int, message: str) -> str:
    return f"<tr><td colspan=\"{colspan}\" class=\"empty\">{escape(message)}</td></tr>"


def _bool_text(value) -> str:
    return "true" if bool(value) else "false"


def _qa_status_label(status: str | None) -> str:
    clean = status or "unknown"
    css = {
        "pass": "qa-pass",
        "warning": "qa-warning",
        "fail": "qa-fail",
    }.get(clean, "")
    return f"<span class=\"{css}\">{escape(clean)}</span>"


def _compact_list(values: list[str], max_chars: int = 240) -> str:
    text = "; ".join(str(value) for value in values if value)
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 4] + " ..."


def _format_checks(checks: dict) -> str:
    if not checks:
        return ""
    return "\n".join(f"{key}: {value}" for key, value in checks.items())


def _compact_tail(text: str, max_chars: int = 800) -> str:
    clean = (text or "").strip()
    if len(clean) <= max_chars:
        return clean
    return "... " + clean[-max_chars:]


def _link_for_path(path: str, label: str | None = None) -> str:
    if not path:
        return '<span class="empty">not generated</span>'
    display = label or _project_relative_path(path)
    href = _html_relative_href(path)
    return f"<a class=\"path\" href=\"{escape(href)}\">{escape(display)}</a>"


def _project_relative_path(path: str) -> str:
    try:
        absolute = Path(path)
        if not absolute.is_absolute():
            absolute = PROJECT_ROOT / absolute
        return absolute.resolve().relative_to(PROJECT_ROOT).as_posix()
    except (OSError, ValueError):
        return str(path).replace("\\", "/")


def _html_relative_href(path: str) -> str:
    try:
        absolute = Path(path)
        if not absolute.is_absolute():
            absolute = PROJECT_ROOT / absolute
        return absolute.resolve().relative_to(HTML_REVIEW_PATH.parent.resolve()).as_posix()
    except (OSError, ValueError):
        return _project_relative_path(path)


def _failed_result(
    product_id: str,
    locale: str,
    failure_type: str,
    failure_reason: str,
    review_paths: dict | None = None,
    skipped: bool = False,
) -> dict:
    paths = review_paths or {"review_file_path": "", "host_review_file_path": "", "container_review_file_path": ""}
    result = {
        "product_id": product_id,
        "locale": locale,
        "language_name": SUPPORTED_LOCALES.get(locale, ""),
        "success": False,
        "exit_code": None,
        "skipped": skipped,
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
        "payload_keys": [],
        "title_chars": 0,
        "meta_title_chars": 0,
        "meta_description_chars": 0,
        "source_meta_description_chars": 0,
        "translated_text_node_count": 0,
        "translated_img_alt_count": 0,
        "img_alt_chars_list": [],
        "removed_shipping_marketing_phrase_count": 0,
        "removed_skipped_origin_field_count": 0,
        "no_shopify_writes_confirmed": False,
        "no_shopify_writes_performed": False,
    }
    return _with_qa(result)


def _per_product_summary(product_ids: list[str], results: list[dict]) -> list[dict]:
    return [
        {
            "product_id": product_id,
            "success_count": sum(1 for item in results if item["product_id"] == product_id and item["success"]),
            "failed_count": sum(1 for item in results if item["product_id"] == product_id and not item["success"]),
            "warning_count": sum(item["warnings_count"] for item in results if item["product_id"] == product_id),
            "qa_pass_count": sum(
                1 for item in results if item["product_id"] == product_id and item.get("qa_status") == "pass"
            ),
            "qa_warning_count": sum(
                1 for item in results if item["product_id"] == product_id and item.get("qa_status") == "warning"
            ),
            "qa_fail_count": sum(
                1 for item in results if item["product_id"] == product_id and item.get("qa_status") == "fail"
            ),
        }
        for product_id in product_ids
    ]


def _per_locale_summary(locales: list[str], results: list[dict]) -> list[dict]:
    return [
        {
            "locale": locale,
            "success_count": sum(1 for item in results if item["locale"] == locale and item["success"]),
            "failed_count": sum(1 for item in results if item["locale"] == locale and not item["success"]),
            "warning_count": sum(item["warnings_count"] for item in results if item["locale"] == locale),
            "qa_pass_count": sum(
                1 for item in results if item["locale"] == locale and item.get("qa_status") == "pass"
            ),
            "qa_warning_count": sum(
                1 for item in results if item["locale"] == locale and item.get("qa_status") == "warning"
            ),
            "qa_fail_count": sum(
                1 for item in results if item["locale"] == locale and item.get("qa_status") == "fail"
            ),
        }
        for locale in locales
    ]


def _review_paths(product_id: str, locale: str) -> dict:
    product_key = _product_key(product_id)
    review_file_name = f"shopify_translation_command_review_{product_key}_{locale}.json"
    host_review_path = PROJECT_ROOT / "backend" / "logs" / review_file_name
    return {
        "review_file_path": str(host_review_path),
        "host_review_file_path": str(host_review_path),
        "container_review_file_path": f"/app/logs/{review_file_name}",
    }


def _product_key(product_id: str) -> str:
    match = PRODUCT_KEY_RE.search(product_id)
    if match:
        return match.group(1)
    return re.sub(r"[^A-Za-z0-9_-]+", "_", product_id)[-24:] or "unknown_product"


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


def _build_issue_summary(
    results: list[dict],
    all_success: bool,
    all_no_write_confirmed: bool,
    qa_status_counts: dict,
) -> str:
    if not results:
        return "No product/locale dry-run combinations were configured."
    if qa_status_counts.get("fail", 0):
        return "Dry-runs completed, but one or more QA gates failed. Review the batch QA gate details."
    if all_success and all_no_write_confirmed and not qa_status_counts.get("warning", 0):
        return "All batch product/locale dry-runs completed, all no-write checks passed, and QA gates passed."
    if all_success and all_no_write_confirmed:
        return "All batch product/locale dry-runs completed with no Shopify writes; QA warnings require review."
    if all_success:
        return "All batch product/locale dry-runs completed, but no-write confirmation was missing for at least one run."
    failure_types = sorted({item["failure_type"] for item in results if item.get("failure_type")})
    return "One or more batch product/locale dry-runs failed. Failure types: " + ", ".join(failure_types)


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
