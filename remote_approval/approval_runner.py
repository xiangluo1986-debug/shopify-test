import argparse
import json
import uuid
from pathlib import Path

from remote_approval.approval_client import (
    ApprovalConfig,
    ApprovalReply,
    LocalApprovalClient,
    TelegramApprovalClient,
)
from remote_approval.task_registry import get_task, get_task_metadata, list_task_metadata
from remote_approval.utils import (
    LOG_DIR,
    append_history,
    format_error_trace,
    load_env,
    mark_approval_processed,
    send_voice_prompt,
    setup_logging,
    utc_now_iso,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run fixed tasks with remote approval gates.")
    parser.add_argument("--task", help="Registered task name, for example: demo")
    parser.add_argument("--mode", default="dry-run", choices=["dry-run"], help="Execution mode")
    parser.add_argument("--approval", default="local", choices=["local", "telegram"], help="Approval mode")
    parser.add_argument("--list-tasks", action="store_true", help="List registered fixed tasks and exit")
    parser.add_argument("--summary-only", action="store_true", help="Run the fixed task and print summary without approval action")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.list_tasks:
        _print_task_list()
        return 0
    if not args.task:
        parser.error("--task is required unless --list-tasks is used")

    logger = setup_logging()
    approval_id = str(uuid.uuid4())

    logger.info("task started")
    logger.info("command arguments: task=%s mode=%s approval=%s", args.task, args.mode, args.approval)
    local_client = LocalApprovalClient(logger) if args.approval == "local" else None

    try:
        interrupt_reply = _check_local_interrupt(local_client, args.task, args.mode, approval_id, "", logger)
        if interrupt_reply:
            return _finish_stopped_by_interrupt(args, approval_id, interrupt_reply, logger)

        task_func = get_task(args.task)
        result = task_func(args.mode)
        task_summary = _build_task_summary(args.task, args.mode, args.approval, result)
        logger.info("task result summary: %s", task_summary)

        if args.summary_only:
            print(task_summary)
            if args.approval == "local":
                send_voice_prompt("Task completed. Please review the summary.")
            return 0

        message = _build_approval_message(args.task, args.mode, result, approval_id)
        interrupt_reply = _check_local_interrupt(local_client, args.task, args.mode, approval_id, task_summary, logger)
        if interrupt_reply:
            return _finish_stopped_by_interrupt(args, approval_id, interrupt_reply, logger)

        approval_reply = _request_reply(message, logger, args.approval, task_summary)
        logger.info("user reply: %s", approval_reply.reply)

        interrupt_reply = _check_local_interrupt(local_client, args.task, args.mode, approval_id, task_summary, logger)
        if interrupt_reply:
            return _finish_stopped_by_interrupt(args, approval_id, interrupt_reply, logger)

        action, action_result, history_result = _execute_selected_action(
            approval_reply, approval_id, args.task, args.mode, result, logger
        )
        logger.info("selected action: %s", action)
        logger.info("action result: %s", action_result)
        append_history(
            {
                "timestamp": utc_now_iso(),
                "task": args.task,
                "mode": args.mode,
                "approval_id": approval_id,
                "approval_mode": args.approval,
                "message": message,
                "reply": approval_reply.reply,
                "action": action,
                "result": history_result,
                "voice_prompt_sent": approval_reply.voice_prompt_sent,
                "interrupt_detected": approval_reply.interrupt_detected,
                "paused": approval_reply.paused,
            }
        )
        print(action_result)
        if args.approval == "local":
            send_voice_prompt("Task completed. Please review the summary.")
        return 0
    except Exception as exc:
        trace = format_error_trace(exc)
        logger.error("error trace:\n%s", trace)
        append_history(
            {
                "timestamp": utc_now_iso(),
                "task": args.task,
                "mode": args.mode,
                "approval_id": approval_id,
                "approval_mode": args.approval,
                "message": "task failed before approval completed",
                "reply": "",
                "action": "stop",
                "result": "failed",
                "voice_prompt_sent": False,
                "interrupt_detected": False,
                "paused": False,
            }
        )
        print(f"Task failed and stopped: {exc}")
        if args.approval == "local":
            send_voice_prompt("Task failed. Please check the log.")
        return 1


def _build_approval_message(task: str, mode: str, result: dict, approval_id: str) -> str:
    if result.get("approval_message"):
        return (
            f"Task: {task}\n"
            f"Approval ID: {approval_id}\n"
            f"Mode: {mode}\n\n"
            f"{result['approval_message']}"
        )

    return (
        f"Task: {task}\n"
        f"Approval ID: {approval_id}\n"
        f"Status: {mode} completed\n"
        "Result:\n"
        f"- checked_items: {result['checked_items']}\n"
        f"- warnings: {result['warnings']}\n\n"
        "Choose next step:\n"
        "1 = generate review file\n"
        "2 = run simulated test write only\n"
        "0 = stop task\n"
        "SHOW_LOG = show recent log summary"
    )


def _request_reply(message: str, logger, approval_mode: str, summary: str) -> ApprovalReply:
    if approval_mode == "local":
        logger.info("local approval selected")
        return LocalApprovalClient(logger).request_approval(message, summary=summary)

    env = load_env(["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "APPROVAL_TIMEOUT_SECONDS"])
    timeout_seconds = _parse_timeout(env.get("APPROVAL_TIMEOUT_SECONDS", "3600"))
    config = ApprovalConfig(
        telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=env.get("TELEGRAM_CHAT_ID", ""),
        timeout_seconds=timeout_seconds,
    )

    if config.has_telegram:
        try:
            logger.info("approval message sending via telegram")
            reply = TelegramApprovalClient(config, logger).request_approval(message)
            logger.info("approval message sent")
            return reply
        except Exception:
            logger.error("telegram approval failed; falling back to console without logging token details")
    else:
        missing = []
        if not config.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not config.telegram_chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        logger.info("console fallback selected; missing config keys: %s", ", ".join(missing))

    logger.info("approval message sent via console fallback")
    return LocalApprovalClient(logger).request_approval(message, summary=summary)


def _parse_timeout(value: str) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return 3600
    return max(timeout, 1)


def _execute_selected_action(
    approval_reply: ApprovalReply, approval_id: str, task: str, mode: str, result: dict, logger
) -> tuple[str, str, str]:
    if approval_reply.result == "timed_out":
        logger.info("approval timed out, task stopped")
        return "stop", "Approval timed out, task stopped.", "timed_out"

    if not mark_approval_processed(approval_id):
        logger.info("duplicate approval ignored: approval_id=%s", approval_id)
        return "duplicate_ignored", "Duplicate approval ignored; no action executed.", "duplicated/ignored"

    if approval_reply.reply == "0":
        return "stop", "Task stopped. No follow-up action executed.", "stopped"
    if result.get("task_type") in {
        "django_check",
        "shopify_translation_dry_run",
        "shopify_translation_batch_apply_command_generate",
        "shopify_translation_batch_apply_command_validate",
        "shopify_translation_batch_apply_execution_approval_validate",
        "shopify_translation_batch_apply_execution_dry_run",
        "shopify_translation_batch_apply_execution_final_validate",
        "shopify_translation_batch_apply_execution_preview",
        "shopify_translation_batch_apply_locked_runner",
        "shopify_translation_batch_apply_plan",
        "shopify_translation_batch_apply_plan_validate",
        "shopify_translation_batch_multi_locale_dry_run",
        "shopify_translation_single_field_apply_preflight_package",
        "shopify_translation_single_field_backup_fetch",
        "shopify_translation_single_field_readback_rollback_plan",
        "shopify_translation_single_field_final_write_gate",
        "shopify_translation_single_field_real_write_runner_design",
        "shopify_translation_single_field_real_write_locked_runner",
        "shopify_translation_single_field_real_write_pre_execution_validate",
        "shopify_translation_single_field_apply_sandbox_design",
        "shopify_translation_single_field_apply_sandbox_runner",
        "shopify_translation_multi_locale_dry_run",
        "git_safety_check",
    }:
        if approval_reply.reply == "1":
            return "keep_review_file", f"Review file kept: {result.get('review_path')}", "approved"
        return "invalid", f"Invalid reply for {result.get('task_type')}. Task stopped.", "invalid"
    if approval_reply.reply == "1":
        review_path = _write_demo_review(task, mode, result)
        return "generate_review_file", f"Review file generated: {review_path}", "approved"
    if approval_reply.reply == "2":
        return (
            "simulate_test_write",
            "Simulated test write completed. No Shopify, database, settlement, or Shopify business write was performed.",
            "approved",
        )
    return "invalid", "Invalid reply. Task stopped.", "invalid"


def _write_demo_review(task: str, mode: str, result: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    review_path = LOG_DIR / "demo_review.json"
    payload = {
        "timestamp": utc_now_iso(),
        "task": task,
        "mode": mode,
        "result": result,
        "note": "Demo review file only. No Shopify, database, or settlement write was performed.",
    }
    with review_path.open("w", encoding="utf-8") as review_file:
        json.dump(payload, review_file, ensure_ascii=False, indent=2)
        review_file.write("\n")
    return review_path


def _summarize_task_result(result: dict) -> str:
    summary_keys = [
        "task_type",
        "success",
        "exit_code",
        "command_label",
        "review_path",
        "json_review_path",
        "html_review_path",
        "detected_issue_summary",
        "failed_count",
        "no_shopify_writes_performed",
        "all_no_write_confirmed",
        "checked_items",
        "warnings",
        "next_step",
        "products_checked",
        "warnings_count",
        "plan_item_count",
        "ready_for_apply_count",
        "needs_review_count",
        "blocked_count",
        "manual_review_required_count",
        "manual_approval_ready_count",
        "manual_pending_count",
        "validation_errors_count",
        "shopify_write_performed",
        "apply_performed",
        "publish_performed",
        "translations_register_performed",
        "json_plan_path",
        "html_plan_path",
        "json_validation_path",
        "html_validation_path",
        "json_preview_path",
        "html_preview_path",
        "preview_only",
        "preview_apply_count",
        "not_apply_count",
        "final_approval_required",
        "final_approval_status",
        "final_approval_ready_count",
        "final_apply_allowed",
        "json_final_validation_path",
        "html_final_validation_path",
        "final_validation_status",
        "eligible_for_real_apply_count",
        "total_preview_items",
        "json_command_plan_path",
        "html_command_plan_path",
        "command_generation_only",
        "command_generation_status",
        "generated_command_count",
        "generated_payload_count",
        "command_approval_required",
        "command_approval_status",
        "command_approval_ready_count",
        "command_execution_allowed",
        "json_command_validation_path",
        "html_command_validation_path",
        "command_validation_only",
        "command_validation_status",
        "eligible_command_execution_count",
        "json_execution_dry_run_path",
        "html_execution_dry_run_path",
        "execution_dry_run_only",
        "execution_dry_run_status",
        "json_execution_approval_validation_path",
        "html_execution_approval_validation_path",
        "execution_approval_validation_only",
        "execution_validation_status",
        "execution_approval_required",
        "execution_approval_status",
        "execution_approval_ready_count",
        "real_execution_allowed",
        "simulated_execution_count",
        "simulated_payload_count",
        "eligible_real_execution_count",
        "command_executed",
        "json_locked_runner_path",
        "html_locked_runner_path",
        "locked_apply_shell_only",
        "locked_runner_status",
        "source_real_execution_allowed",
        "real_apply_allowed",
        "real_apply_performed",
        "json_sandbox_design_path",
        "html_sandbox_design_path",
        "sandbox_design_only",
        "sandbox_design_status",
        "json_sandbox_runner_path",
        "html_sandbox_runner_path",
        "sandbox_runner_dry_run_only",
        "sandbox_runner_status",
        "json_preflight_package_path",
        "html_preflight_package_path",
        "preflight_package_only",
        "preflight_status",
        "json_backup_fetch_path",
        "html_backup_fetch_path",
        "backup_fetch_status",
        "read_only_shopify_query_performed",
        "shopify_query_type",
        "backup_value_present",
        "backup_value_chars",
        "backup_value_source",
        "backup_locale",
        "backup_field",
        "backup_product_id",
        "json_readback_rollback_plan_path",
        "html_readback_rollback_plan_path",
        "plan_status",
        "backup_source_is_verified",
        "source_preflight_status",
        "source_backup_fetch_status",
        "shopify_api_call_performed",
        "readback_performed",
        "rollback_performed",
        "json_final_write_gate_path",
        "html_final_write_gate_path",
        "final_gate_status",
        "final_real_write_allowed",
        "json_real_write_runner_design_path",
        "html_real_write_runner_design_path",
        "design_status",
        "design_only",
        "future_required_dangerous_flag",
        "json_real_write_locked_runner_path",
        "html_real_write_locked_runner_path",
        "locked_shell",
        "dangerous_flag_present",
        "dangerous_flag_effective",
        "json_pre_execution_validate_path",
        "html_pre_execution_validate_path",
        "pre_execution_validation_only",
        "validation_status",
        "write_execution_allowed",
        "would_apply_field",
        "would_call_shopify_mutation",
        "proposed_value_chars",
        "proposed_value_length_allowed",
        "real_write_allowed",
        "real_write_attempted",
        "translations_register_allowed",
        "translations_register_called",
        "shopify_api_called",
        "mutation_performed",
        "max_products",
        "max_locales",
        "max_fields",
        "default_field",
        "total_final_validation_items",
        "blocked_items_count",
        "validation_failures_count",
        "validation_warnings_count",
        "validation_only",
        "total_plan_items",
        "validated_for_future_apply_count",
        "needs_revision_count",
        "pending_count",
        "validation_warning_count",
        "validation_failure_count",
        "branch",
        "ahead_commits",
        "changed_files",
        "staged_files",
        "untracked_files",
        "secret_findings",
    ]
    summary = {key: result[key] for key in summary_keys if key in result}
    return json.dumps(summary, ensure_ascii=False)


def _build_task_summary(task: str, mode: str, approval_mode: str, result: dict) -> str:
    metadata = get_task_metadata(task)
    success = result.get("success")
    if success is None and task == "demo":
        success = True
    summary = {
        "task": task,
        "mode": mode,
        "approval_mode": approval_mode,
        "review_file_path": result.get("review_path") or metadata.get("review_file_path"),
        "success": success,
        "detected_issue_summary": result.get("detected_issue_summary") or "No issue summary for this task.",
        "next_allowed_actions": _next_allowed_actions(task),
        "result": json.loads(_summarize_task_result(result)),
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


def _next_allowed_actions(task: str) -> list[str]:
    if task == "demo":
        return ["Y/1 generate review file", "2 run simulated test write", "N/0 stop", "P pause", "SHOW_LOG", "SUMMARY"]
    if task in {
        "shopify_translation_multi_locale_dry_run",
        "shopify_translation_batch_multi_locale_dry_run",
        "shopify_translation_batch_apply_command_generate",
        "shopify_translation_batch_apply_command_validate",
        "shopify_translation_batch_apply_execution_approval_validate",
        "shopify_translation_batch_apply_execution_dry_run",
        "shopify_translation_batch_apply_execution_final_validate",
        "shopify_translation_batch_apply_execution_preview",
        "shopify_translation_batch_apply_locked_runner",
        "shopify_translation_batch_apply_plan",
        "shopify_translation_batch_apply_plan_validate",
        "shopify_translation_single_field_apply_preflight_package",
        "shopify_translation_single_field_backup_fetch",
        "shopify_translation_single_field_readback_rollback_plan",
        "shopify_translation_single_field_final_write_gate",
        "shopify_translation_single_field_real_write_runner_design",
        "shopify_translation_single_field_real_write_locked_runner",
        "shopify_translation_single_field_real_write_pre_execution_validate",
        "shopify_translation_single_field_apply_sandbox_design",
        "shopify_translation_single_field_apply_sandbox_runner",
    }:
        return ["Y/1 keep review files", "N/0 stop", "SHOW_LOG", "SUMMARY"]
    return ["Y/1 keep review file", "N/0 stop", "P pause", "SHOW_LOG", "SUMMARY"]


def _print_task_list() -> None:
    print("Registered Local Approval Runner tasks:")
    for metadata in list_task_metadata():
        print(f"- {metadata['name']}")
        print(f"  description: {metadata['description']}")
        print(f"  allowed modes: {', '.join(metadata['allowed_modes'])}")
        print(f"  write risk: {metadata['write_risk']}")
        print(f"  review file path: {metadata['review_file_path']}")


def _check_local_interrupt(
    local_client: LocalApprovalClient | None, task: str, mode: str, approval_id: str, summary: str, logger
) -> ApprovalReply | None:
    if local_client is None:
        return None
    reply = local_client.handle_interrupt_if_requested(summary=summary)
    if not reply:
        return None
    logger.info("task stopped by local interrupt")
    return reply


def _finish_stopped_by_interrupt(args, approval_id: str, reply: ApprovalReply, logger) -> int:
    append_history(
        {
            "timestamp": utc_now_iso(),
            "task": args.task,
            "mode": args.mode,
            "approval_id": approval_id,
            "approval_mode": args.approval,
            "message": "local interrupt requested before continuing task stage",
            "reply": reply.reply,
            "action": "stop",
            "result": "stopped",
            "voice_prompt_sent": reply.voice_prompt_sent,
            "interrupt_detected": reply.interrupt_detected,
            "paused": reply.paused,
        }
    )
    logger.info("selected action: stop")
    logger.info("action result: stopped by local interrupt")
    print("Task stopped by local interrupt.")
    send_voice_prompt("Task failed. Please check the log.")
    return 0
