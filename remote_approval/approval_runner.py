import argparse
import json
import os
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
    parser.add_argument("task_or_command", nargs="?", help="Registered task name, or 'list'")
    parser.add_argument("--task", help="Registered task name, for example: demo")
    parser.add_argument(
        "--mode",
        default="dry-run",
        choices=["dry-run", "real-run", "execute-real-write"],
        help="Execution mode",
    )
    parser.add_argument("--approval", default="local", choices=["local", "telegram"], help="Approval mode")
    parser.add_argument("--list-tasks", action="store_true", help="List registered fixed tasks and exit")
    parser.add_argument("--summary-only", action="store_true", help="Run the fixed task and print summary without approval action")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.task_or_command:
        if args.task_or_command == "list":
            args.list_tasks = True
        elif not args.task:
            args.task = args.task_or_command
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

        os.environ["REMOTE_APPROVAL_MODE"] = args.approval
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
        "shopify_review_request_ali_reviews_capability_discovery",
        "shopify_review_request_candidate_scan",
        "shopify_review_request_gmail_oauth_setup_helper",
        "shopify_review_request_gmail_readiness_package",
        "shopify_review_request_kudosi_api_403_diagnostics",
        "shopify_review_request_kudosi_api_capability_probe",
        "shopify_review_request_manual_action_csv_export",
        "shopify_review_request_manual_action_package",
        "shopify_review_request_next_repeat_customer_candidate_scan",
        "shopify_review_request_trustpilot_one_candidate_gmail_draft_package",
        "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute",
        "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight",
        "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute",
        "shopify_review_request_returned_package_guard",
        "shopify_review_request_shopify_tag_permission_readiness",
        "shopify_review_request_tag_discovery",
        "shopify_review_request_trustpilot_gmail_draft_create_locked_test",
        "shopify_review_request_trustpilot_gmail_draft_content_update_pre_send",
        "shopify_review_request_trustpilot_gmail_draft_package",
        "shopify_review_request_trustpilot_gmail_first_draft_audit",
        "shopify_review_request_trustpilot_gmail_oauth_readiness_preflight",
        "shopify_review_request_trustpilot_gmail_one_draft_locked_runner",
        "shopify_review_request_trustpilot_gmail_one_draft_send_execute",
        "shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight",
        "shopify_review_request_trustpilot_gmail_one_draft_send_locked_runner",
        "shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness",
        "shopify_review_request_trustpilot_gmail_repeat_customer_guard",
        "shopify_review_request_trustpilot_gmail_send_audit",
        "shopify_review_request_trustpilot_gmail_send_tag_design_dry_run",
        "shopify_review_request_trustpilot_completion_next_batch_design",
        "shopify_review_request_trustpilot_suppress_ali_reviews_design",
        "shopify_review_request_trustpilot_tag_write_audit",
        "shopify_review_request_trustpilot_tag_write_design_dry_run",
        "shopify_review_request_trustpilot_tag_write_execute",
        "shopify_review_request_trustpilot_tag_write_final_preflight",
        "shopify_review_request_trustpilot_tag_write_locked_runner",
        "shopify_review_request_unified_decision_engine_dry_run",
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
        "shopify_translation_single_field_final_human_approval_package",
        "shopify_translation_single_field_real_write_runner_final_safe_shell",
        "shopify_translation_single_field_real_write_execution_plan",
        "shopify_translation_single_field_real_write_one_shot_locked_shell",
        "shopify_translation_single_field_real_write_one_shot_execute",
        "shopify_translation_single_field_post_write_audit_package",
        "shopify_translation_single_field_rollback_approval_package",
        "shopify_translation_second_single_field_test_prepare",
        "shopify_translation_second_single_field_verified_backup_fetch",
        "shopify_translation_second_single_field_real_write_readiness",
        "shopify_translation_second_single_field_real_write_execute",
        "shopify_translation_second_single_field_post_write_audit_package",
        "shopify_translation_small_batch_apply_plan_package",
        "shopify_translation_small_batch_apply_execute",
        "shopify_translation_small_batch_post_write_audit_package",
        "shopify_translation_small_batch_rollback_approval_package",
        "shopify_translation_csv_json_small_batch_apply_plan_package",
        "shopify_translation_csv_json_small_batch_real_write_readiness_package",
        "shopify_translation_csv_json_small_batch_manual_real_run_test_package",
        "shopify_translation_csv_json_small_batch_post_write_audit_package",
        "shopify_translation_selected_product_missing_translation_draft_package",
        "shopify_translation_translatable_resource_mapping_audit",
        "shopify_translation_selected_product_real_write_execute",
        "shopify_translation_first_real_write_completion_audit",
        "shopify_translation_small_batch_locked_dry_run_package",
        "shopify_translation_small_batch_real_write_gate_preflight",
        "shopify_translation_small_batch_real_write_execute",
        "shopify_translation_small_batch_post_write_audit",
        "shopify_translation_next_batch_locked_dry_run_package",
        "shopify_translation_next_batch_real_write_execute",
        "shopify_translation_next_batch_post_write_audit",
        "shopify_translation_remaining_title_batch_locked_dry_run_package",
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
        "plan_source",
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
        "json_final_human_approval_package_path",
        "html_final_human_approval_package_path",
        "approval_package_status",
        "final_human_approval_package_only",
        "phase_12_entry_allowed",
        "json_final_safe_shell_path",
        "html_final_safe_shell_path",
        "final_safe_shell_status",
        "final_safe_shell_only",
        "phase_12_1_entry_allowed",
        "final_safe_shell_ack_present",
        "final_safe_shell_ack_effective",
        "json_execution_plan_path",
        "html_execution_plan_path",
        "execution_plan_status",
        "execution_plan_only",
        "payload_preview_only",
        "phase_12_1b_entry_allowed",
        "phase_12_1a_plan_ack_present",
        "phase_12_1a_plan_ack_effective",
        "json_one_shot_locked_shell_path",
        "html_one_shot_locked_shell_path",
        "one_shot_locked_shell_status",
        "one_shot_locked_shell_only",
        "phase_12_1b_real_execution_allowed",
        "phase_12_final_safe_shell_ack_present",
        "phase_12_final_safe_shell_ack_effective",
        "phase_12_1b_locked_shell_ack_present",
        "phase_12_1b_locked_shell_ack_effective",
        "json_one_shot_execute_path",
        "html_one_shot_execute_path",
        "execution_status",
        "one_shot_real_execution_task",
        "real_execution_ack_present",
        "real_execution_ack_valid",
        "real_write_scope_limited",
        "real_write_count",
        "readback_matches_proposed_value",
        "rollback_approval_required",
        "automatic_rollback_performed",
        "json_post_write_audit_package_path",
        "html_post_write_audit_package_path",
        "audit_status",
        "post_write_audit_only",
        "source_execution_status",
        "source_shopify_write_performed",
        "source_translations_register_called",
        "source_mutation_performed",
        "source_readback_performed",
        "audit_verification_passed",
        "rollback_needed",
        "no_new_shopify_writes_performed",
        "all_new_actions_no_write_confirmed",
        "json_rollback_approval_package_path",
        "html_rollback_approval_package_path",
        "rollback_approval_status",
        "rollback_approval_package_only",
        "rollback_optional_restore_possible",
        "rollback_optional_restore_requires_separate_approval",
        "current_value",
        "backup_value",
        "rollback_execution_allowed",
        "json_second_test_prepare_path",
        "html_second_test_prepare_path",
        "preparation_status",
        "second_test_prepare_only",
        "second_test_field",
        "second_test_proposed_value_chars",
        "second_test_real_write_allowed",
        "json_second_verified_backup_path",
        "html_second_verified_backup_path",
        "source_second_test_prepare_status",
        "second_backup_source_is_verified",
        "second_backup_value_present",
        "second_backup_value_chars",
        "second_backup_locale",
        "second_backup_field",
        "second_backup_product_id",
        "json_second_real_write_readiness_path",
        "html_second_real_write_readiness_path",
        "readiness_status",
        "readiness_package_only",
        "product_id",
        "locale",
        "field",
        "current_backup_value_chars",
        "backup_source_verified",
        "read_only_backup_query_performed",
        "human_approval_required_before_real_write",
        "json_second_real_write_execute_path",
        "html_second_real_write_execute_path",
        "second_real_write_execute_task",
        "second_real_execution_ack_present",
        "second_real_execution_ack_valid",
        "second_real_write_scope_limited",
        "bulk_write_performed",
        "json_second_post_write_audit_package_path",
        "html_second_post_write_audit_package_path",
        "audit_package_only",
        "source_real_write_count",
        "rollback_optional_restore_possible",
        "json_small_batch_apply_plan_package_path",
        "html_small_batch_apply_plan_package_path",
        "plan_package_only",
        "entry_count",
        "allowed_fields",
        "manual_review_required",
        "next_step_requires_separate_execute_task",
        "json_small_batch_apply_execute_path",
        "html_small_batch_apply_execute_path",
        "small_batch_execute_task",
        "small_batch_execute_dry_run_only",
        "small_batch_execution_ack_present",
        "small_batch_execution_ack_valid",
        "small_batch_write_performed",
        "readback_all_entries_match",
        "readback_matched_entry_count",
        "json_small_batch_post_write_audit_package_path",
        "html_small_batch_post_write_audit_package_path",
        "source_entry_count",
        "manual_review_completed",
        "json_small_batch_rollback_approval_package_path",
        "html_small_batch_rollback_approval_package_path",
        "restore_plan_status",
        "restore_value_source",
        "manual_backup_review_required",
        "restore_execution_task_required",
        "manual_human_approval_required_before_restore",
        "restore_performed",
        "json_csv_json_small_batch_apply_plan_package_path",
        "html_csv_json_small_batch_apply_plan_package_path",
        "input_source",
        "input_path",
        "json_csv_json_small_batch_real_write_readiness_package_path",
        "html_csv_json_small_batch_real_write_readiness_package_path",
        "json_csv_json_small_batch_manual_real_run_test_package_path",
        "html_csv_json_small_batch_manual_real_run_test_package_path",
        "manual_test_package_status",
        "manual_test_package_only",
        "manual_test_required",
        "real_run_not_executed_by_this_task",
        "json_csv_json_small_batch_post_write_audit_package_path",
        "html_csv_json_small_batch_post_write_audit_package_path",
        "json_next_batch_post_write_audit_path",
        "html_next_batch_post_write_audit_path",
        "next_batch_completion_status",
        "readback_audit_status",
        "duplicate_write_protection_status",
        "remaining_eligible_count",
        "next_recommended_batch_status",
        "next_recommended_batch_count",
        "json_remaining_title_batch_locked_dry_run_package_path",
        "html_remaining_title_batch_locked_dry_run_package_path",
        "remaining_title_batch_locked_status",
        "locked_remaining_title_batch_ready",
        "remaining_title_candidate_count",
        "locked_remaining_title_planned_values_persisted",
        "json_remaining_title_batch_real_write_execute_path",
        "html_remaining_title_batch_real_write_execute_path",
        "remaining_title_selected_count",
        "manual_remaining_title_batch_real_write_allowed_next_step",
        "json_remaining_title_batch_post_write_audit_path",
        "html_remaining_title_batch_post_write_audit_path",
        "remaining_title_completion_status",
        "selected_product_seo_fields_completion_status",
        "json_selected_product_missing_translation_draft_package_path",
        "html_selected_product_missing_translation_draft_package_path",
        "json_mapping_audit_path",
        "html_mapping_audit_path",
        "audit_status",
        "target_product_gid",
        "target_locale",
        "can_enable_options_draft_generation",
        "can_enable_variants_draft_generation",
        "can_enable_metafields_draft_generation",
        "json_ali_reviews_capability_discovery_path",
        "html_ali_reviews_capability_discovery_path",
        "json_kudosi_api_403_diagnostics_path",
        "html_kudosi_api_403_diagnostics_path",
        "diagnostics_status",
        "authorization_header_present",
        "api_key_present",
        "api_key_length",
        "api_key_has_leading_or_trailing_whitespace",
        "api_key_contains_spaces",
        "api_key_contains_quotes",
        "api_key_safe_fingerprint_prefix",
        "json_kudosi_api_capability_probe_path",
        "html_kudosi_api_capability_probe_path",
        "capability_probe_status",
        "endpoint_called",
        "http_status",
        "list_reviews_available",
        "review_request_send_available",
        "review_request_sent_status_available",
        "json_candidate_scan_path",
        "html_candidate_scan_path",
        "json_manual_action_package_path",
        "html_manual_action_package_path",
        "json_manual_action_csv_export_path",
        "html_manual_action_csv_export_path",
        "csv_manual_action_export_path",
        "json_next_repeat_customer_candidate_scan_path",
        "html_next_repeat_customer_candidate_scan_path",
        "json_trustpilot_one_candidate_gmail_draft_package_path",
        "html_trustpilot_one_candidate_gmail_draft_package_path",
        "json_trustpilot_one_candidate_gmail_draft_create_execute_path",
        "html_trustpilot_one_candidate_gmail_draft_create_execute_path",
        "json_trustpilot_one_candidate_gmail_draft_send_preflight_path",
        "html_trustpilot_one_candidate_gmail_draft_send_preflight_path",
        "json_trustpilot_one_candidate_gmail_draft_send_execute_path",
        "html_trustpilot_one_candidate_gmail_draft_send_execute_path",
        "json_gmail_oauth_setup_helper_path",
        "html_gmail_oauth_setup_helper_path",
        "json_trustpilot_gmail_draft_create_locked_test_path",
        "html_trustpilot_gmail_draft_create_locked_test_path",
        "json_trustpilot_gmail_draft_content_update_pre_send_path",
        "html_trustpilot_gmail_draft_content_update_pre_send_path",
        "json_trustpilot_gmail_draft_package_path",
        "html_trustpilot_gmail_draft_package_path",
        "json_trustpilot_gmail_oauth_readiness_preflight_path",
        "html_trustpilot_gmail_oauth_readiness_preflight_path",
        "json_trustpilot_gmail_first_draft_audit_path",
        "html_trustpilot_gmail_first_draft_audit_path",
        "json_trustpilot_gmail_one_draft_locked_runner_path",
        "html_trustpilot_gmail_one_draft_locked_runner_path",
        "json_trustpilot_gmail_one_draft_send_execute_path",
        "html_trustpilot_gmail_one_draft_send_execute_path",
        "json_trustpilot_gmail_one_draft_send_final_preflight_path",
        "html_trustpilot_gmail_one_draft_send_final_preflight_path",
        "json_trustpilot_gmail_one_draft_send_locked_runner_path",
        "html_trustpilot_gmail_one_draft_send_locked_runner_path",
        "json_trustpilot_gmail_one_draft_send_real_run_readiness_path",
        "html_trustpilot_gmail_one_draft_send_real_run_readiness_path",
        "json_trustpilot_gmail_repeat_customer_guard_path",
        "html_trustpilot_gmail_repeat_customer_guard_path",
        "json_returned_package_guard_path",
        "html_returned_package_guard_path",
        "json_trustpilot_gmail_send_audit_path",
        "html_trustpilot_gmail_send_audit_path",
        "json_trustpilot_gmail_send_tag_design_dry_run_path",
        "html_trustpilot_gmail_send_tag_design_dry_run_path",
        "json_trustpilot_completion_next_batch_design_path",
        "html_trustpilot_completion_next_batch_design_path",
        "json_trustpilot_suppress_ali_reviews_design_path",
        "html_trustpilot_suppress_ali_reviews_design_path",
        "json_trustpilot_tag_write_audit_path",
        "html_trustpilot_tag_write_audit_path",
        "json_trustpilot_tag_write_design_dry_run_path",
        "html_trustpilot_tag_write_design_dry_run_path",
        "json_trustpilot_tag_write_execute_path",
        "html_trustpilot_tag_write_execute_path",
        "json_trustpilot_tag_write_final_preflight_path",
        "html_trustpilot_tag_write_final_preflight_path",
        "json_trustpilot_tag_write_locked_runner_path",
        "html_trustpilot_tag_write_locked_runner_path",
        "json_unified_decision_engine_dry_run_path",
        "html_unified_decision_engine_dry_run_path",
        "one_draft_status",
        "first_draft_audit_status",
        "send_tag_design_status",
        "one_draft_send_status",
        "one_draft_send_execute_status",
        "tag_write_execute_status",
        "tag_write_audit_status",
        "tag_write_final_preflight_status",
        "tag_write_locked_status",
        "real_run_readiness_status",
        "final_preflight_status",
        "draft_create_status",
        "draft_content_pre_send_status",
        "repeat_customer_guard_status",
        "return_guard_status",
        "source_preflight_status",
        "source_send_preflight_status",
        "send_audit_status",
        "completion_next_batch_design_status",
        "trustpilot_suppress_ali_reviews_design_status",
        "tag_write_design_status",
        "setup_status",
        "preflight_status",
        "draft_package_status",
        "one_candidate_gmail_draft_package_status",
        "one_candidate_gmail_draft_create_execute_status",
        "one_candidate_gmail_draft_send_preflight_status",
        "one_candidate_gmail_draft_send_execute_status",
        "manual_action_package_status",
        "csv_export_status",
        "next_repeat_customer_candidate_scan_status",
        "decision_engine_status",
        "source_report_status",
        "source_manual_action_package_status",
        "source_scanner_version",
        "section_counts",
        "total_manual_action_items",
        "total_rows_exported",
        "total_orders_evaluated",
        "total_candidates_seen",
        "total_local_drafts_prepared",
        "total_gmail_drafts_created",
        "candidate_count_seen",
        "candidate_selected_count",
        "selected_candidate",
        "rows_by_bucket",
        "counts",
        "blocked_counts",
        "gmail_create_drafts_enabled",
        "approval_ack_valid",
        "gmail_oauth_present",
        "gmail_scope_configured",
        "gmail_client_id_present",
        "gmail_client_secret_present",
        "gmail_refresh_token_present",
        "gmail_scopes_present",
        "gmail_compose_scope_present",
        "gmail_sender_matches_expected",
        "gmail_oauth_token_refresh_attempted",
        "gmail_oauth_token_refresh_succeeded",
        "gmail_draft_creation_ack_valid",
        "ack_valid",
        "gmail_draft_create_attempted",
        "gmail_token_refresh_attempted",
        "gmail_token_refresh_succeeded",
        "gmail_drafts_created_count",
        "selected_order_name",
        "selected_masked_email",
        "next_candidate_selected",
        "next_candidate_count",
        "repeat_customer_confirmed",
        "duplicate_trustpilot_invitation_block_confirmed",
        "returned_package_guard_confirmed",
        "first_order_customer_block_confirmed",
        "would_create_gmail_draft",
        "would_create_count",
        "would_send_gmail_draft",
        "would_send_count",
        "real_run_requested",
        "real_gmail_draft_create_allowed",
        "real_gmail_draft_create_executed",
        "real_gmail_draft_create_blocked_reason",
        "real_gmail_send_allowed",
        "real_gmail_send_executed",
        "real_gmail_send_blocked_reason",
        "real_gmail_send_allowed_now",
        "future_real_gmail_send_needs_next_phase",
        "gmail_draft_id_partial",
        "gmail_draft_verified",
        "draft_created_confirmed",
        "source_draft_create_status",
        "protected_raw_email_lookup_attempted",
        "raw_email_available_to_runtime",
        "gmail_sender_planned",
        "trustpilot_link",
        "subject",
        "csv_contains_only_masked_emails",
        "scanner_version",
        "report_status",
        "classification_counts",
        "ready_for_manual_ali_reviews_check_count",
        "existing_manual_review_request_tag_present_count",
        "delivered_but_ali_status_unknown_count",
        "repeat_customer_candidate_count",
        "blocked_order_count",
        "needs_manual_review_count",
        "ticket_status_check",
        "email_field_sources_attempted",
        "email_parse_source_counts",
        "orders_with_email_count",
        "orders_without_email_count",
        "email_masking_applied",
        "ticket_model_detected",
        "ticket_query_performed",
        "ticket_matches_found_count",
        "orders_with_ticket_match_count",
        "orders_blocked_by_ticket_count",
        "ticket_blocking_statuses",
        "ticket_warning_statuses",
        "ticket_filter_error_sanitized",
        "query_failure_type",
        "query_failure_message_sanitized",
        "command_attempted_sanitized",
        "docker_command_reached",
        "django_shell_reached",
        "shopify_installation_found",
        "shopify_credentials_found",
        "shopify_api_response_error_count",
        "successful_query_label",
        "successful_fallback_query_label",
        "query_warning_summary",
        "ali_reviews_public_api_base_url",
        "known_public_api_capability_count",
        "missing_or_unconfirmed_capability_count",
        "support_question_count",
        "automation_decision_status",
        "json_gmail_readiness_package_path",
        "html_gmail_readiness_package_path",
        "gmail_send_from",
        "required_scope",
        "required_env_var_count",
        "missing_env_var_count",
        "trustpilot_review_link_configured",
        "gmail_send_allowed",
        "recommended_scope",
        "sender_email",
        "draft_only_mode",
        "gmail_draft_create_allowed_later_only_with_ack",
        "json_shopify_tag_permission_readiness_path",
        "html_shopify_tag_permission_readiness_path",
        "required_order_tag_scopes",
        "required_customer_tag_scopes",
        "required_mutations",
        "direct_tags_field_overwrite_allowed",
        "exact_existing_review_request_tag",
        "exact_existing_delivered_tag",
        "future_candidate_tag_count",
        "shopify_tag_write_allowed",
        "json_tag_discovery_path",
        "html_tag_discovery_path",
        "discovery_status",
        "product_field_count",
        "nested_resource_count",
        "variant_related_count",
        "option_related_count",
        "image_alt_related_count",
        "metafield_related_count",
        "read_only_discovery_only",
        "orders_queried",
        "candidate_tag_count",
        "exact_tag_strings",
        "tags_add_performed",
        "tags_remove_performed",
        "kudosi_api_call_performed",
        "kudosi_write_api_call_performed",
        "kudosi_review_request_send_performed",
        "ali_reviews_api_call_performed",
        "gmail_api_call_performed",
        "gmail_oauth_token_exchange_performed",
        "gmail_draft_created",
        "gmail_drafts_send_called",
        "gmail_messages_send_called",
        "gmail_send_performed",
        "email_sent",
        "draft_status",
        "generated_draft_count",
        "draft_ready_count",
        "draft_needs_manual_review_count",
        "eligible_apply_plan_count",
        "over_length_after_rewrite_count",
        "seo_ready_count",
        "seo_needs_manual_review_count",
        "seo_eligible_apply_plan_count",
        "forbidden_phrase_count",
        "missing_core_keyword_count",
        "too_short_for_seo_count",
        "skipped_existing_translation_count",
        "skipped_outdated_translation_count",
        "skipped_source_empty_count",
        "draft_package_only",
        "shopify_read_only",
        "openai_call_performed",
        "translation_generated",
        "existing_translation_overwrite_allowed",
        "manual_human_approval_required",
        "required_ack_env_name",
        "next_step_manual_real_run_required",
        "batch_mode_allowed",
        "full_store_scan_allowed",
        "automatic_rollback_allowed",
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
        "shopify_review_request_ali_reviews_capability_discovery",
        "shopify_review_request_candidate_scan",
        "shopify_review_request_gmail_oauth_setup_helper",
        "shopify_review_request_gmail_readiness_package",
        "shopify_review_request_kudosi_api_403_diagnostics",
        "shopify_review_request_kudosi_api_capability_probe",
        "shopify_review_request_manual_action_csv_export",
        "shopify_review_request_manual_action_package",
        "shopify_review_request_next_repeat_customer_candidate_scan",
        "shopify_review_request_trustpilot_one_candidate_gmail_draft_package",
        "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute",
        "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight",
        "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute",
        "shopify_review_request_returned_package_guard",
        "shopify_review_request_shopify_tag_permission_readiness",
        "shopify_review_request_tag_discovery",
        "shopify_review_request_trustpilot_gmail_draft_create_locked_test",
        "shopify_review_request_trustpilot_gmail_draft_content_update_pre_send",
        "shopify_review_request_trustpilot_gmail_draft_package",
        "shopify_review_request_trustpilot_gmail_first_draft_audit",
        "shopify_review_request_trustpilot_gmail_oauth_readiness_preflight",
        "shopify_review_request_trustpilot_gmail_one_draft_locked_runner",
        "shopify_review_request_trustpilot_gmail_one_draft_send_execute",
        "shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight",
        "shopify_review_request_trustpilot_gmail_one_draft_send_locked_runner",
        "shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness",
        "shopify_review_request_trustpilot_gmail_repeat_customer_guard",
        "shopify_review_request_trustpilot_gmail_send_audit",
        "shopify_review_request_trustpilot_gmail_send_tag_design_dry_run",
        "shopify_review_request_trustpilot_completion_next_batch_design",
        "shopify_review_request_trustpilot_suppress_ali_reviews_design",
        "shopify_review_request_trustpilot_tag_write_audit",
        "shopify_review_request_trustpilot_tag_write_design_dry_run",
        "shopify_review_request_trustpilot_tag_write_execute",
        "shopify_review_request_trustpilot_tag_write_final_preflight",
        "shopify_review_request_trustpilot_tag_write_locked_runner",
        "shopify_review_request_unified_decision_engine_dry_run",
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
        "shopify_translation_single_field_final_human_approval_package",
        "shopify_translation_single_field_real_write_runner_final_safe_shell",
        "shopify_translation_single_field_real_write_execution_plan",
        "shopify_translation_single_field_real_write_one_shot_locked_shell",
        "shopify_translation_single_field_real_write_one_shot_execute",
        "shopify_translation_single_field_post_write_audit_package",
        "shopify_translation_single_field_rollback_approval_package",
        "shopify_translation_second_single_field_test_prepare",
        "shopify_translation_second_single_field_verified_backup_fetch",
        "shopify_translation_second_single_field_real_write_readiness",
        "shopify_translation_second_single_field_real_write_execute",
        "shopify_translation_second_single_field_post_write_audit_package",
        "shopify_translation_small_batch_apply_plan_package",
        "shopify_translation_small_batch_apply_execute",
        "shopify_translation_small_batch_post_write_audit_package",
        "shopify_translation_small_batch_rollback_approval_package",
        "shopify_translation_csv_json_small_batch_apply_plan_package",
        "shopify_translation_csv_json_small_batch_real_write_readiness_package",
        "shopify_translation_csv_json_small_batch_manual_real_run_test_package",
        "shopify_translation_csv_json_small_batch_post_write_audit_package",
        "shopify_translation_selected_product_missing_translation_draft_package",
        "shopify_translation_translatable_resource_mapping_audit",
        "shopify_translation_small_batch_locked_dry_run_package",
        "shopify_translation_small_batch_real_write_gate_preflight",
        "shopify_translation_small_batch_real_write_execute",
        "shopify_translation_small_batch_post_write_audit",
        "shopify_translation_next_batch_locked_dry_run_package",
        "shopify_translation_next_batch_real_write_execute",
        "shopify_translation_next_batch_post_write_audit",
        "shopify_translation_remaining_title_batch_locked_dry_run_package",
        "shopify_translation_remaining_title_batch_real_write_execute",
        "shopify_translation_remaining_title_batch_post_write_audit",
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


if __name__ == "__main__":
    raise SystemExit(main())
