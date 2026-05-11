import json
import os
import re
import subprocess
import time
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "git_safety_check"
COMMAND_LABEL = "fixed_git_read_only_safety_check"
REVIEW_PATH = LOG_DIR / "git_safety_check_review.json"
TAIL_LINES = 300
MAX_SCAN_BYTES = 512 * 1024

FIXED_COMMANDS = {
    "status": ["git", "status", "--short", "--branch"],
    "branch": ["git", "branch", "--show-current"],
    "ahead_commits": ["git", "log", "--oneline", "origin/main..HEAD"],
    "diff_stat": ["git", "diff", "--stat"],
    "cached_diff_stat": ["git", "diff", "--cached", "--stat"],
    "diff_name_only": ["git", "diff", "--name-only"],
    "cached_diff_name_only": ["git", "diff", "--cached", "--name-only"],
}

SECRET_PATTERNS = [
    ("OPENAI_API_KEY", re.compile(r"OPENAI_API_KEY\s*="), "high"),
    ("SHOPIFY_ACCESS_TOKEN", re.compile(r"SHOPIFY_ACCESS_TOKEN\s*="), "high"),
    ("TELEGRAM_BOT_TOKEN", re.compile(r"TELEGRAM_BOT_TOKEN\s*="), "high"),
    ("TELEGRAM_CHAT_ID", re.compile(r"TELEGRAM_CHAT_ID\s*="), "medium"),
    ("API_KEY", re.compile(r"API_KEY\s*="), "high"),
    ("SECRET", re.compile(r"SECRET\s*="), "high"),
    ("PASSWORD", re.compile(r"PASSWORD\s*="), "high"),
    ("BEARER_TOKEN", re.compile(r"Bearer\s+", re.IGNORECASE), "high"),
    ("X_SHPAT_TOKEN", re.compile(r"x-shpat_", re.IGNORECASE), "high"),
    ("SHPAT_TOKEN", re.compile(r"shpat_", re.IGNORECASE), "high"),
    ("GITHUB_TOKEN", re.compile(r"ghp_", re.IGNORECASE), "high"),
    ("OPENAI_KEY_LITERAL", re.compile(r"sk-"), "high"),
]

HIGH_RISK_PATHS = [
    ".env",
    "backend/logs/",
    "logs/",
    "backend/reviews/",
    "_review.json",
    "approval_history.jsonl",
    "approval_state.json",
    "scheduler.log",
    "scripts/",
    "backend/shopify_sync/management/commands/translate_shopify_product.py",
    "backend/shopify_sync/views.py",
]


def run_git_safety_check_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError("git_safety_check only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    command_results = {label: _run_fixed_command(command) for label, command in FIXED_COMMANDS.items()}
    end_time = utc_now_iso()
    duration_seconds = round(time.time() - started, 3)

    status_text = command_results["status"]["stdout"]
    branch = command_results["branch"]["stdout"].strip()
    ahead_commits = _non_empty_lines(command_results["ahead_commits"]["stdout"])
    changed_files = _non_empty_lines(command_results["diff_name_only"]["stdout"])
    staged_files = _non_empty_lines(command_results["cached_diff_name_only"]["stdout"])
    untracked_files = _parse_untracked_files(status_text)
    scan_targets = _unique_paths(changed_files + staged_files + untracked_files)
    suspicious_files = _detect_suspicious_files(scan_targets + staged_files)
    secret_scan_findings = _scan_secret_risks(scan_targets)
    risk_summary = _build_risk_summary(branch, ahead_commits, changed_files, staged_files, suspicious_files, secret_scan_findings)
    recommended_next_action = _recommended_next_action(risk_summary)
    success = not any(item["risk_level"] == "high" for item in risk_summary)

    review_payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "mode": mode,
        "command_label": COMMAND_LABEL,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": duration_seconds,
        "branch": branch,
        "ahead_commits": ahead_commits,
        "changed_files": changed_files,
        "staged_files": staged_files,
        "untracked_files": untracked_files,
        "suspicious_files": suspicious_files,
        "secret_scan_findings": secret_scan_findings,
        "risk_summary": risk_summary,
        "recommended_next_action": recommended_next_action,
        "success": success,
        "detected_issue_summary": _detected_issue_summary(risk_summary),
        "command_outputs": {
            label: {
                "exit_code": result["exit_code"],
                "stdout_tail": _tail_lines(result["stdout"], TAIL_LINES),
                "stderr_tail": _tail_lines(result["stderr"], TAIL_LINES),
            }
            for label, result in command_results.items()
        },
    }
    review_path = _write_review(review_payload)

    return {
        "task_type": TASK_NAME,
        "success": success,
        "command_label": COMMAND_LABEL,
        "review_path": str(review_path),
        "branch": branch,
        "ahead_commits": len(ahead_commits),
        "changed_files": len(changed_files),
        "staged_files": len(staged_files),
        "untracked_files": len(untracked_files),
        "secret_findings": len(secret_scan_findings),
        "detected_issue_summary": review_payload["detected_issue_summary"],
        "approval_message": _build_approval_message(success, review_path, review_payload),
    }


def _run_fixed_command(command: list[str]) -> dict:
    env = os.environ.copy()
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "safe.directory"
    env["GIT_CONFIG_VALUE_0"] = str(PROJECT_ROOT)
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=False,
        timeout=30,
        shell=False,
        env=env,
    )
    return {
        "exit_code": completed.returncode,
        "stdout": _to_text(completed.stdout),
        "stderr": _to_text(completed.stderr),
    }


def _write_review(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REVIEW_PATH.open("w", encoding="utf-8") as review_file:
        json.dump(payload, review_file, ensure_ascii=False, indent=2)
        review_file.write("\n")
    return REVIEW_PATH


def _build_approval_message(success: bool, review_path: Path, payload: dict) -> str:
    status = "completed" if success else "completed with risks"
    return (
        f"Git safety check {status}.\n"
        f"Branch: {payload['branch']}\n"
        f"Ahead commits: {len(payload['ahead_commits'])}\n"
        f"Changed files: {len(payload['changed_files'])}\n"
        f"Staged files: {len(payload['staged_files'])}\n"
        f"Untracked files: {len(payload['untracked_files'])}\n"
        f"Secret risk findings: {len(payload['secret_scan_findings'])}\n"
        f"Review file: {review_path}\n\n"
        "Choose next step:\n"
        "1 = keep review file\n"
        "SHOW_LOG = show recent log summary\n"
        "SUMMARY = show current task summary\n"
        "0 = stop"
    )


def _parse_untracked_files(status_text: str) -> list[str]:
    files = []
    for line in status_text.splitlines():
        if line.startswith("?? "):
            files.append(line[3:].strip())
    return files


def _non_empty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _unique_paths(paths: list[str]) -> list[str]:
    seen = set()
    unique = []
    for path in paths:
        normalized = path.replace("\\", "/").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def _detect_suspicious_files(paths: list[str]) -> list[dict]:
    findings = []
    for path in _unique_paths(paths):
        normalized = path.replace("\\", "/")
        for pattern in HIGH_RISK_PATHS:
            if pattern in normalized or normalized == pattern:
                findings.append({"file": normalized, "risk_type": f"suspicious_path:{pattern}", "risk_level": _path_risk_level(normalized)})
                break
    return findings


def _path_risk_level(path: str) -> str:
    if path == ".env":
        return "high"
    if path.endswith("_review.json") or path.endswith("approval_history.jsonl") or path.endswith("approval_state.json"):
        return "high"
    if path.startswith("logs/") or path.startswith("backend/logs/") or path.startswith("backend/reviews/"):
        return "medium"
    if path.endswith("scheduler.log"):
        return "medium"
    if path.startswith("scripts/"):
        return "medium"
    if path in {
        "backend/shopify_sync/management/commands/translate_shopify_product.py",
        "backend/shopify_sync/views.py",
    }:
        return "high"
    return "medium"


def _scan_secret_risks(paths: list[str]) -> list[dict]:
    findings = []
    for path in _unique_paths(paths):
        if path == ".env" or path.endswith(".env"):
            findings.append({"file": path, "pattern_type": "ENV_FILE_CHANGED", "risk_level": "high"})
            continue
        file_path = PROJECT_ROOT / path
        if not _is_scannable_text_file(file_path):
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in content.splitlines():
            if _is_scanner_rule_definition(line):
                continue
            for pattern_type, pattern, risk_level in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append({"file": path, "pattern_type": pattern_type, "risk_level": risk_level})
                    break
    return findings


def _is_scanner_rule_definition(line: str) -> bool:
    return "re.compile" in line or "SECRET_PATTERNS" in line


def _is_scannable_text_file(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return False
    except OSError:
        return False
    return path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".sqlite3", ".pyc"}


def _build_risk_summary(
    branch: str,
    ahead_commits: list[str],
    changed_files: list[str],
    staged_files: list[str],
    suspicious_files: list[dict],
    secret_scan_findings: list[dict],
) -> list[dict]:
    risks = []
    staged = {path.replace("\\", "/") for path in staged_files}
    changed = {path.replace("\\", "/") for path in changed_files}

    if ".env" in staged:
        risks.append({"risk_level": "high", "risk_type": "env_staged", "message": ".env is staged. Do not commit secrets."})
    if any(_is_log_or_review(path) for path in staged):
        risks.append({"risk_level": "high", "risk_type": "logs_or_reviews_staged", "message": "Log/review/state files are staged."})
    if any(path.endswith("scheduler.log") for path in changed | staged):
        risks.append({"risk_level": "medium", "risk_type": "scheduler_log_changed", "message": "scheduler.log is modified or staged."})
    if any(_is_shopify_write_sensitive_path(path) for path in changed | staged):
        risks.append({"risk_level": "high", "risk_type": "shopify_code_changed", "message": "Shopify write-sensitive code changed; manual review required."})
    if branch == "main" and ahead_commits:
        risks.append({"risk_level": "medium", "risk_type": "main_ahead_origin", "message": "Current branch is main and ahead of origin/main. Confirm before any push."})
    for finding in suspicious_files:
        risks.append({"risk_level": finding["risk_level"], "risk_type": finding["risk_type"], "message": f"Suspicious file path: {finding['file']}"})
    for finding in secret_scan_findings:
        risks.append({"risk_level": finding["risk_level"], "risk_type": f"secret_pattern:{finding['pattern_type']}", "message": f"Possible secret risk in {finding['file']}"})

    if not risks and _only_local_approval_docs_changed(changed | staged):
        risks.append({"risk_level": "low", "risk_type": "local_approval_docs_only", "message": "Only Local Approval Runner docs/code appear changed."})
    if not risks:
        risks.append({"risk_level": "low", "risk_type": "no_obvious_risk", "message": "No obvious Git safety risk detected."})
    return risks


def _is_log_or_review(path: str) -> bool:
    return (
        path.startswith("logs/")
        or path.startswith("backend/logs/")
        or path.startswith("backend/reviews/")
        or path.endswith("_review.json")
        or path.endswith("approval_history.jsonl")
        or path.endswith("approval_state.json")
    )


def _is_shopify_write_sensitive_path(path: str) -> bool:
    return path in {
        "backend/shopify_sync/management/commands/translate_shopify_product.py",
        "backend/shopify_sync/views.py",
    }


def _only_local_approval_docs_changed(paths: set[str]) -> bool:
    if not paths:
        return False
    allowed_prefixes = (
        "remote_approval/",
        ".codex/skills/local-approval-runner/",
    )
    allowed_files = {".gitignore", "AGENTS.md"}
    return all(path.startswith(allowed_prefixes) or path in allowed_files for path in paths)


def _recommended_next_action(risk_summary: list[dict]) -> str:
    if any(item["risk_level"] == "high" for item in risk_summary):
        return "Stop before commit/push. Review high-risk files and remove secrets/logs/write-sensitive changes from staging."
    if any(item["risk_level"] == "medium" for item in risk_summary):
        return "Review medium-risk files manually before staging or committing."
    return "Low risk detected. If the staged file list is correct, a local commit may be reasonable."


def _detected_issue_summary(risk_summary: list[dict]) -> str:
    highest = "low"
    if any(item["risk_level"] == "high" for item in risk_summary):
        highest = "high"
    elif any(item["risk_level"] == "medium" for item in risk_summary):
        highest = "medium"
    return f"Git safety risk level: {highest}. Findings: {len(risk_summary)}."


def _tail_lines(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-max_lines:])


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
