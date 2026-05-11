import json
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, load_env, utc_now_iso


TASK_NAME = "shopify_translation_dry_run"
TARGET_LOCALE = "de"
COMMAND_LABEL = "docker_compose_web_translate_shopify_product_dry_run"
REVIEW_PATH = LOG_DIR / "shopify_translation_dry_run_review.json"
COMMAND_REVIEW_CONTAINER_PATH = "/app/logs/shopify_translation_command_review.json"
COMMAND_REVIEW_HOST_PATH = PROJECT_ROOT / "backend" / "logs" / "shopify_translation_command_review.json"
TIMEOUT_SECONDS = 300
TAIL_LINES = 300
PRODUCT_ID_RE = re.compile(r"^(?:\d+|gid://shopify/Product/\d+)$")


def run_shopify_translation_dry_run_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError("shopify_translation_dry_run only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    stdout = ""
    stderr = ""
    exit_code = 1
    timed_out = False
    product_id = _configured_product_id()
    command_review_path: Optional[Path] = None

    if not product_id:
        stderr = (
            "A safe test product_id is required. Configure SHOPIFY_TRANSLATION_TEST_PRODUCT_ID in .env. "
            "Current phase did not execute Shopify dry-run."
        )
        detected_issue_summary = "Missing safe test product_id. Shopify dry-run was not executed."
    elif not PRODUCT_ID_RE.match(product_id):
        stderr = "SHOPIFY_TRANSLATION_TEST_PRODUCT_ID must be a numeric product ID or gid://shopify/Product/<id>."
        detected_issue_summary = "Invalid safe test product_id format. Shopify dry-run was not executed."
    else:
        command = _build_command(product_id)
        try:
            completed = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                shell=False,
            )
            exit_code = completed.returncode
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            if COMMAND_REVIEW_HOST_PATH.exists():
                command_review_path = COMMAND_REVIEW_HOST_PATH
        except FileNotFoundError:
            stderr = "Docker command was not found. Please install Docker Desktop and make sure it is available in PATH."
            exit_code = 127
        except PermissionError:
            stderr = "Docker permission denied. Stop here, reopen Codex as administrator, and confirm Docker Desktop is running."
            exit_code = 126
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = 124
            stdout = _to_text(exc.stdout)
            stderr = _to_text(exc.stderr)
            stderr = (stderr + "\n" if stderr else "") + f"Shopify translation dry-run timed out after {TIMEOUT_SECONDS} seconds."
        detected_issue_summary = _summarize_issue(exit_code, stderr, timed_out)

    end_time = utc_now_iso()
    duration_seconds = round(time.time() - started, 3)
    success = exit_code == 0
    parsed_metrics = _parse_command_review(command_review_path)
    stdout_tail = _tail_lines(stdout, TAIL_LINES)
    stderr_tail = _tail_lines(stderr, TAIL_LINES)
    review_payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "mode": mode,
        "target_locale": TARGET_LOCALE,
        "limit": None,
        "product_id": product_id or None,
        "command_label": COMMAND_LABEL,
        "exit_code": exit_code,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": duration_seconds,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "success": success,
        "detected_issue_summary": detected_issue_summary,
        "review_file_path": str(command_review_path) if command_review_path else "",
        "warnings_count": parsed_metrics.get("warnings_count"),
        "removed_shipping_marketing_phrase_count": parsed_metrics.get("removed_shipping_marketing_phrase_count"),
        "glossary_matches": parsed_metrics.get("glossary_matches"),
        "title_length_warnings": parsed_metrics.get("title_length_warnings"),
    }
    review_path = _write_review(review_payload)

    return {
        "task_type": TASK_NAME,
        "success": success,
        "exit_code": exit_code,
        "target_locale": TARGET_LOCALE,
        "products_checked": 1 if product_id and success else 0,
        "warnings_count": parsed_metrics.get("warnings_count", _count_warning_lines(stdout_tail + "\n" + stderr_tail)),
        "command_label": COMMAND_LABEL,
        "review_path": str(review_path),
        "detected_issue_summary": detected_issue_summary,
        "approval_message": _build_approval_message(success, review_path, detected_issue_summary, parsed_metrics),
    }


def _configured_product_id() -> str:
    env = load_env(["SHOPIFY_TRANSLATION_TEST_PRODUCT_ID"])
    return (env.get("SHOPIFY_TRANSLATION_TEST_PRODUCT_ID") or "").strip()


def _build_command(product_id: str) -> list[str]:
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
        TARGET_LOCALE,
        "--dry-run",
        "--review-file",
        COMMAND_REVIEW_CONTAINER_PATH,
    ]


def _write_review(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REVIEW_PATH.open("w", encoding="utf-8") as review_file:
        json.dump(payload, review_file, ensure_ascii=False, indent=2)
        review_file.write("\n")
    return REVIEW_PATH


def _build_approval_message(success: bool, review_path: Path, issue_summary: str, metrics: dict) -> str:
    warnings_count = metrics.get("warnings_count", 0)
    if success:
        return (
            "Shopify translation dry-run completed.\n"
            f"Target locale: {TARGET_LOCALE}\n"
            "Products checked: 1\n"
            f"Warnings: {warnings_count}\n"
            f"Review file: {review_path}\n\n"
            "Choose next step:\n"
            "1 = keep review file\n"
            "SHOW_LOG = show recent log summary\n"
            "0 = stop"
        )
    return (
        "Shopify translation dry-run failed.\n"
        f"Reason: {issue_summary}\n"
        f"Review file: {review_path}\n\n"
        "Choose next step:\n"
        "1 = keep review file\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _parse_command_review(path: Optional[Path]) -> dict:
    if not path or not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as review_file:
            data = json.load(review_file)
    except (json.JSONDecodeError, OSError):
        return {}

    warnings = data.get("warnings") or []
    summary = data.get("summary") or {}
    glossary_matches = summary.get("glossary_matches") or []
    title_chars = summary.get("title_chars") or 0
    title_length_warnings = 1 if title_chars and title_chars > 65 else 0
    return {
        "warnings_count": len(warnings),
        "removed_shipping_marketing_phrase_count": summary.get("removed_shipping_marketing_phrase_count", 0),
        "glossary_matches": len(glossary_matches),
        "title_length_warnings": title_length_warnings,
    }


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


def _summarize_issue(exit_code: int, stderr: str, timed_out: bool) -> str:
    stderr_lower = stderr.lower()
    if exit_code == 0:
        return "No issues detected by Shopify translation dry-run."
    if timed_out:
        return f"Command timed out after {TIMEOUT_SECONDS} seconds."
    if "access is denied" in stderr_lower or "permission denied" in stderr_lower:
        return "Docker permission denied. Do not retry with automated elevation; reopen Codex as administrator if needed."
    if "not found" in stderr_lower or "is not recognized" in stderr_lower:
        return "Docker command was not found or is not available in PATH."
    if "openai_api_key is not configured" in stderr_lower:
        return "Missing OpenAI API key configuration. Secret value was not printed."
    if "shopify installation not found" in stderr_lower:
        return "Missing Shopify installation/configuration for the selected shop."
    if "unrecognized arguments" in stderr_lower:
        return "Management command arguments are not supported by the current code."
    return "Shopify translation dry-run failed. See stderr_tail in the review file."
