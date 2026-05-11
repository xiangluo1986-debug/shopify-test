import json
import subprocess
import time
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


COMMAND_LABEL = "docker_compose_web_manage_check"
DJANGO_CHECK_COMMAND = ["docker", "compose", "exec", "-T", "web", "python", "manage.py", "check"]
REVIEW_PATH = LOG_DIR / "django_check_review.json"
TIMEOUT_SECONDS = 180
TAIL_LINES = 200


def run_django_check_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError("django_check only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    stdout = ""
    stderr = ""
    exit_code = 1
    timed_out = False

    try:
        completed = subprocess.run(
            DJANGO_CHECK_COMMAND,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            shell=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
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
        stderr = (stderr + "\n" if stderr else "") + f"Django check timed out after {TIMEOUT_SECONDS} seconds."

    end_time = utc_now_iso()
    duration_seconds = round(time.time() - started, 3)
    success = exit_code == 0
    detected_issue_summary = _summarize_issue(exit_code, stderr, timed_out)
    review_path = _write_review(
        {
            "timestamp": end_time,
            "task": "django_check",
            "mode": mode,
            "command_label": COMMAND_LABEL,
            "exit_code": exit_code,
            "start_time": start_time,
            "end_time": end_time,
            "duration_seconds": duration_seconds,
            "stdout_tail": _tail_lines(stdout, TAIL_LINES),
            "stderr_tail": _tail_lines(stderr, TAIL_LINES),
            "success": success,
            "detected_issue_summary": detected_issue_summary,
        }
    )

    return {
        "task_type": "django_check",
        "success": success,
        "exit_code": exit_code,
        "command_label": COMMAND_LABEL,
        "review_path": str(review_path),
        "detected_issue_summary": detected_issue_summary,
        "approval_message": _build_approval_message(success, review_path),
    }


def _write_review(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REVIEW_PATH.open("w", encoding="utf-8") as review_file:
        json.dump(payload, review_file, ensure_ascii=False, indent=2)
        review_file.write("\n")
    return REVIEW_PATH


def _build_approval_message(success: bool, review_path: Path) -> str:
    if success:
        return (
            "Django check completed.\n"
            "Result: success\n"
            f"Review file: {review_path}\n\n"
            "Choose next step:\n"
            "1 = keep review file\n"
            "0 = stop"
        )
    return (
        "Django check failed.\n"
        "Please review the generated review file.\n"
        f"Review file: {review_path}\n\n"
        "Choose next step:\n"
        "1 = keep review file\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
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


def _summarize_issue(exit_code: int, stderr: str, timed_out: bool) -> str:
    stderr_lower = stderr.lower()
    if exit_code == 0:
        return "No issues detected by Django system check."
    if timed_out:
        return f"Command timed out after {TIMEOUT_SECONDS} seconds."
    if "access is denied" in stderr_lower or "permission denied" in stderr_lower:
        return "Docker permission denied. Do not retry with automated elevation; reopen Codex as administrator if needed."
    if "not found" in stderr_lower or "is not recognized" in stderr_lower:
        return "Docker command was not found or is not available in PATH."
    return "Django check failed. See stderr_tail in the review file."
