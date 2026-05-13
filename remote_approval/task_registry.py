from typing import Callable, Dict, List

from remote_approval.tasks.django_check_task import run_django_check_task
from remote_approval.tasks.demo_task import run_demo_task
from remote_approval.tasks.git_safety_check_task import run_git_safety_check_task
from remote_approval.tasks.shopify_review_request_ali_reviews_capability_discovery_task import (
    run_shopify_review_request_ali_reviews_capability_discovery_task,
)
from remote_approval.tasks.shopify_review_request_candidate_scan_task import (
    run_shopify_review_request_candidate_scan_task,
)
from remote_approval.tasks.shopify_review_request_gmail_readiness_package_task import (
    run_shopify_review_request_gmail_readiness_package_task,
)
from remote_approval.tasks.shopify_review_request_gmail_oauth_setup_helper_task import (
    run_shopify_review_request_gmail_oauth_setup_helper_task,
)
from remote_approval.tasks.shopify_review_request_kudosi_api_403_diagnostics_task import (
    run_shopify_review_request_kudosi_api_403_diagnostics_task,
)
from remote_approval.tasks.shopify_review_request_kudosi_api_capability_probe_task import (
    run_shopify_review_request_kudosi_api_capability_probe_task,
)
from remote_approval.tasks.shopify_review_request_manual_action_package_task import (
    run_shopify_review_request_manual_action_package_task,
)
from remote_approval.tasks.shopify_review_request_manual_action_csv_export_task import (
    run_shopify_review_request_manual_action_csv_export_task,
)
from remote_approval.tasks.shopify_review_request_shopify_tag_permission_readiness_task import (
    run_shopify_review_request_shopify_tag_permission_readiness_task,
)
from remote_approval.tasks.shopify_review_request_tag_discovery_task import (
    run_shopify_review_request_tag_discovery_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_draft_package_task import (
    run_shopify_review_request_trustpilot_gmail_draft_package_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_draft_create_locked_test_task import (
    run_shopify_review_request_trustpilot_gmail_draft_create_locked_test_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_draft_content_update_pre_send_task import (
    run_shopify_review_request_trustpilot_gmail_draft_content_update_pre_send_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_oauth_readiness_preflight_task import (
    run_shopify_review_request_trustpilot_gmail_oauth_readiness_preflight_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_first_draft_audit_task import (
    run_shopify_review_request_trustpilot_gmail_first_draft_audit_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_one_draft_locked_runner_task import (
    run_shopify_review_request_trustpilot_gmail_one_draft_locked_runner_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_one_draft_send_locked_runner_task import (
    run_shopify_review_request_trustpilot_gmail_one_draft_send_locked_runner_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight_task import (
    run_shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_one_draft_send_execute_task import (
    run_shopify_review_request_trustpilot_gmail_one_draft_send_execute_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness_task import (
    run_shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_send_tag_design_dry_run_task import (
    run_shopify_review_request_trustpilot_gmail_send_tag_design_dry_run_task,
)
from remote_approval.tasks.shopify_review_request_unified_decision_engine_dry_run_task import (
    run_shopify_review_request_unified_decision_engine_dry_run_task,
)
from remote_approval.tasks.shopify_translation_batch_apply_plan_task import (
    run_shopify_translation_batch_apply_plan_task,
)
from remote_approval.tasks.shopify_translation_batch_apply_plan_validate_task import (
    run_shopify_translation_batch_apply_plan_validate_task,
)
from remote_approval.tasks.shopify_translation_batch_apply_execution_preview_task import (
    run_shopify_translation_batch_apply_execution_preview_task,
)
from remote_approval.tasks.shopify_translation_batch_apply_execution_final_validate_task import (
    run_shopify_translation_batch_apply_execution_final_validate_task,
)
from remote_approval.tasks.shopify_translation_batch_apply_command_generate_task import (
    run_shopify_translation_batch_apply_command_generate_task,
)
from remote_approval.tasks.shopify_translation_batch_apply_command_validate_task import (
    run_shopify_translation_batch_apply_command_validate_task,
)
from remote_approval.tasks.shopify_translation_batch_apply_execution_dry_run_task import (
    run_shopify_translation_batch_apply_execution_dry_run_task,
)
from remote_approval.tasks.shopify_translation_batch_apply_execution_approval_validate_task import (
    run_shopify_translation_batch_apply_execution_approval_validate_task,
)
from remote_approval.tasks.shopify_translation_batch_apply_locked_runner_task import (
    run_shopify_translation_batch_apply_locked_runner_task,
)
from remote_approval.tasks.shopify_translation_single_field_apply_sandbox_design_task import (
    run_shopify_translation_single_field_apply_sandbox_design_task,
)
from remote_approval.tasks.shopify_translation_single_field_apply_sandbox_runner_task import (
    run_shopify_translation_single_field_apply_sandbox_runner_task,
)
from remote_approval.tasks.shopify_translation_single_field_apply_preflight_package_task import (
    run_shopify_translation_single_field_apply_preflight_package_task,
)
from remote_approval.tasks.shopify_translation_single_field_backup_fetch_task import (
    run_shopify_translation_single_field_backup_fetch_task,
)
from remote_approval.tasks.shopify_translation_single_field_readback_rollback_plan_task import (
    run_shopify_translation_single_field_readback_rollback_plan_task,
)
from remote_approval.tasks.shopify_translation_single_field_final_write_gate_task import (
    run_shopify_translation_single_field_final_write_gate_task,
)
from remote_approval.tasks.shopify_translation_single_field_real_write_runner_design_task import (
    run_shopify_translation_single_field_real_write_runner_design_task,
)
from remote_approval.tasks.shopify_translation_single_field_real_write_locked_runner_task import (
    run_shopify_translation_single_field_real_write_locked_runner_task,
)
from remote_approval.tasks.shopify_translation_single_field_real_write_pre_execution_validate_task import (
    run_shopify_translation_single_field_real_write_pre_execution_validate_task,
)
from remote_approval.tasks.shopify_translation_single_field_final_human_approval_package_task import (
    run_shopify_translation_single_field_final_human_approval_package_task,
)
from remote_approval.tasks.shopify_translation_single_field_real_write_runner_final_safe_shell_task import (
    run_shopify_translation_single_field_real_write_runner_final_safe_shell_task,
)
from remote_approval.tasks.shopify_translation_single_field_real_write_execution_plan_task import (
    run_shopify_translation_single_field_real_write_execution_plan_task,
)
from remote_approval.tasks.shopify_translation_single_field_real_write_one_shot_locked_shell_task import (
    run_shopify_translation_single_field_real_write_one_shot_locked_shell_task,
)
from remote_approval.tasks.shopify_translation_single_field_real_write_one_shot_execute_task import (
    run_shopify_translation_single_field_real_write_one_shot_execute_task,
)
from remote_approval.tasks.shopify_translation_single_field_post_write_audit_package_task import (
    run_shopify_translation_single_field_post_write_audit_package_task,
)
from remote_approval.tasks.shopify_translation_single_field_rollback_approval_package_task import (
    run_shopify_translation_single_field_rollback_approval_package_task,
)
from remote_approval.tasks.shopify_translation_second_single_field_test_prepare_task import (
    run_shopify_translation_second_single_field_test_prepare_task,
)
from remote_approval.tasks.shopify_translation_second_single_field_verified_backup_fetch_task import (
    run_shopify_translation_second_single_field_verified_backup_fetch_task,
)
from remote_approval.tasks.shopify_translation_second_single_field_real_write_readiness_task import (
    run_shopify_translation_second_single_field_real_write_readiness_task,
)
from remote_approval.tasks.shopify_translation_second_single_field_real_write_execute_task import (
    run_shopify_translation_second_single_field_real_write_execute_task,
)
from remote_approval.tasks.shopify_translation_second_single_field_post_write_audit_package_task import (
    run_shopify_translation_second_single_field_post_write_audit_package_task,
)
from remote_approval.tasks.shopify_translation_small_batch_apply_plan_package_task import (
    run_shopify_translation_small_batch_apply_plan_package_task,
)
from remote_approval.tasks.shopify_translation_small_batch_apply_execute_task import (
    run_shopify_translation_small_batch_apply_execute_task,
)
from remote_approval.tasks.shopify_translation_small_batch_post_write_audit_package_task import (
    run_shopify_translation_small_batch_post_write_audit_package_task,
)
from remote_approval.tasks.shopify_translation_small_batch_rollback_approval_package_task import (
    run_shopify_translation_small_batch_rollback_approval_package_task,
)
from remote_approval.tasks.shopify_translation_csv_json_small_batch_apply_plan_package_task import (
    run_shopify_translation_csv_json_small_batch_apply_plan_package_task,
)
from remote_approval.tasks.shopify_translation_csv_json_small_batch_real_write_readiness_package_task import (
    run_shopify_translation_csv_json_small_batch_real_write_readiness_package_task,
)
from remote_approval.tasks.shopify_translation_csv_json_small_batch_manual_real_run_test_package_task import (
    run_shopify_translation_csv_json_small_batch_manual_real_run_test_package_task,
)
from remote_approval.tasks.shopify_translation_csv_json_small_batch_post_write_audit_package_task import (
    run_shopify_translation_csv_json_small_batch_post_write_audit_package_task,
)
from remote_approval.tasks.shopify_translation_selected_product_missing_translation_draft_package_task import (
    run_shopify_translation_selected_product_missing_translation_draft_package_task,
)
from remote_approval.tasks.shopify_translation_selected_product_real_write_execute_task import (
    run_shopify_translation_selected_product_real_write_execute_task,
)
from remote_approval.tasks.shopify_translation_first_real_write_completion_audit_task import (
    run_shopify_translation_first_real_write_completion_audit_task,
)
from remote_approval.tasks.shopify_translation_small_batch_locked_dry_run_package_task import (
    run_shopify_translation_small_batch_locked_dry_run_package_task,
)
from remote_approval.tasks.shopify_translation_small_batch_real_write_gate_preflight_task import (
    run_shopify_translation_small_batch_real_write_gate_preflight_task,
)
from remote_approval.tasks.shopify_translation_small_batch_real_write_execute_task import (
    run_shopify_translation_small_batch_real_write_execute_task,
)
from remote_approval.tasks.shopify_translation_small_batch_post_write_audit_task import (
    run_shopify_translation_small_batch_post_write_audit_task,
)
from remote_approval.tasks.shopify_translation_next_batch_locked_dry_run_package_task import (
    run_shopify_translation_next_batch_locked_dry_run_package_task,
)
from remote_approval.tasks.shopify_translation_next_batch_real_write_execute_task import (
    run_shopify_translation_next_batch_real_write_execute_task,
)
from remote_approval.tasks.shopify_translation_next_batch_post_write_audit_task import (
    run_shopify_translation_next_batch_post_write_audit_task,
)
from remote_approval.tasks.shopify_translation_remaining_title_batch_locked_dry_run_package_task import (
    run_shopify_translation_remaining_title_batch_locked_dry_run_package_task,
)
from remote_approval.tasks.shopify_translation_batch_multi_locale_task import (
    run_shopify_translation_batch_multi_locale_dry_run_task,
)
from remote_approval.tasks.shopify_translation_multi_locale_task import (
    run_shopify_translation_multi_locale_dry_run_task,
)
from remote_approval.tasks.shopify_translation_task import run_shopify_translation_dry_run_task


TaskCallable = Callable[[str], dict]


TASK_REGISTRY: Dict[str, TaskCallable] = {
    "demo": run_demo_task,
    "django_check": run_django_check_task,
    "git_safety_check": run_git_safety_check_task,
    "shopify_review_request_ali_reviews_capability_discovery": (
        run_shopify_review_request_ali_reviews_capability_discovery_task
    ),
    "shopify_review_request_candidate_scan": run_shopify_review_request_candidate_scan_task,
    "shopify_review_request_gmail_readiness_package": run_shopify_review_request_gmail_readiness_package_task,
    "shopify_review_request_gmail_oauth_setup_helper": run_shopify_review_request_gmail_oauth_setup_helper_task,
    "shopify_review_request_kudosi_api_403_diagnostics": run_shopify_review_request_kudosi_api_403_diagnostics_task,
    "shopify_review_request_kudosi_api_capability_probe": run_shopify_review_request_kudosi_api_capability_probe_task,
    "shopify_review_request_manual_action_csv_export": run_shopify_review_request_manual_action_csv_export_task,
    "shopify_review_request_manual_action_package": run_shopify_review_request_manual_action_package_task,
    "shopify_review_request_shopify_tag_permission_readiness": (
        run_shopify_review_request_shopify_tag_permission_readiness_task
    ),
    "shopify_review_request_tag_discovery": run_shopify_review_request_tag_discovery_task,
    "shopify_review_request_trustpilot_gmail_draft_package": (
        run_shopify_review_request_trustpilot_gmail_draft_package_task
    ),
    "shopify_review_request_trustpilot_gmail_draft_create_locked_test": (
        run_shopify_review_request_trustpilot_gmail_draft_create_locked_test_task
    ),
    "shopify_review_request_trustpilot_gmail_draft_content_update_pre_send": (
        run_shopify_review_request_trustpilot_gmail_draft_content_update_pre_send_task
    ),
    "shopify_review_request_trustpilot_gmail_oauth_readiness_preflight": (
        run_shopify_review_request_trustpilot_gmail_oauth_readiness_preflight_task
    ),
    "shopify_review_request_trustpilot_gmail_first_draft_audit": (
        run_shopify_review_request_trustpilot_gmail_first_draft_audit_task
    ),
    "shopify_review_request_trustpilot_gmail_one_draft_locked_runner": (
        run_shopify_review_request_trustpilot_gmail_one_draft_locked_runner_task
    ),
    "shopify_review_request_trustpilot_gmail_one_draft_send_locked_runner": (
        run_shopify_review_request_trustpilot_gmail_one_draft_send_locked_runner_task
    ),
    "shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight": (
        run_shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight_task
    ),
    "shopify_review_request_trustpilot_gmail_one_draft_send_execute": (
        run_shopify_review_request_trustpilot_gmail_one_draft_send_execute_task
    ),
    "shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness": (
        run_shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness_task
    ),
    "shopify_review_request_trustpilot_gmail_send_tag_design_dry_run": (
        run_shopify_review_request_trustpilot_gmail_send_tag_design_dry_run_task
    ),
    "shopify_review_request_unified_decision_engine_dry_run": (
        run_shopify_review_request_unified_decision_engine_dry_run_task
    ),
    "shopify_translation_batch_apply_command_generate": run_shopify_translation_batch_apply_command_generate_task,
    "shopify_translation_batch_apply_command_validate": run_shopify_translation_batch_apply_command_validate_task,
    "shopify_translation_batch_apply_execution_approval_validate": (
        run_shopify_translation_batch_apply_execution_approval_validate_task
    ),
    "shopify_translation_batch_apply_execution_dry_run": run_shopify_translation_batch_apply_execution_dry_run_task,
    "shopify_translation_batch_apply_execution_final_validate": (
        run_shopify_translation_batch_apply_execution_final_validate_task
    ),
    "shopify_translation_batch_apply_execution_preview": run_shopify_translation_batch_apply_execution_preview_task,
    "shopify_translation_batch_apply_locked_runner": run_shopify_translation_batch_apply_locked_runner_task,
    "shopify_translation_batch_apply_plan": run_shopify_translation_batch_apply_plan_task,
    "shopify_translation_batch_apply_plan_validate": run_shopify_translation_batch_apply_plan_validate_task,
    "shopify_translation_batch_multi_locale_dry_run": run_shopify_translation_batch_multi_locale_dry_run_task,
    "shopify_translation_single_field_apply_sandbox_design": (
        run_shopify_translation_single_field_apply_sandbox_design_task
    ),
    "shopify_translation_single_field_apply_sandbox_runner": (
        run_shopify_translation_single_field_apply_sandbox_runner_task
    ),
    "shopify_translation_single_field_apply_preflight_package": (
        run_shopify_translation_single_field_apply_preflight_package_task
    ),
    "shopify_translation_single_field_backup_fetch": run_shopify_translation_single_field_backup_fetch_task,
    "shopify_translation_single_field_readback_rollback_plan": (
        run_shopify_translation_single_field_readback_rollback_plan_task
    ),
    "shopify_translation_single_field_final_write_gate": run_shopify_translation_single_field_final_write_gate_task,
    "shopify_translation_single_field_real_write_runner_design": (
        run_shopify_translation_single_field_real_write_runner_design_task
    ),
    "shopify_translation_single_field_real_write_locked_runner": (
        run_shopify_translation_single_field_real_write_locked_runner_task
    ),
    "shopify_translation_single_field_real_write_pre_execution_validate": (
        run_shopify_translation_single_field_real_write_pre_execution_validate_task
    ),
    "shopify_translation_single_field_final_human_approval_package": (
        run_shopify_translation_single_field_final_human_approval_package_task
    ),
    "shopify_translation_single_field_real_write_runner_final_safe_shell": (
        run_shopify_translation_single_field_real_write_runner_final_safe_shell_task
    ),
    "shopify_translation_single_field_real_write_execution_plan": (
        run_shopify_translation_single_field_real_write_execution_plan_task
    ),
    "shopify_translation_single_field_real_write_one_shot_locked_shell": (
        run_shopify_translation_single_field_real_write_one_shot_locked_shell_task
    ),
    "shopify_translation_single_field_real_write_one_shot_execute": (
        run_shopify_translation_single_field_real_write_one_shot_execute_task
    ),
    "shopify_translation_single_field_post_write_audit_package": (
        run_shopify_translation_single_field_post_write_audit_package_task
    ),
    "shopify_translation_single_field_rollback_approval_package": (
        run_shopify_translation_single_field_rollback_approval_package_task
    ),
    "shopify_translation_second_single_field_test_prepare": run_shopify_translation_second_single_field_test_prepare_task,
    "shopify_translation_second_single_field_verified_backup_fetch": (
        run_shopify_translation_second_single_field_verified_backup_fetch_task
    ),
    "shopify_translation_second_single_field_real_write_readiness": (
        run_shopify_translation_second_single_field_real_write_readiness_task
    ),
    "shopify_translation_second_single_field_real_write_execute": (
        run_shopify_translation_second_single_field_real_write_execute_task
    ),
    "shopify_translation_second_single_field_post_write_audit_package": (
        run_shopify_translation_second_single_field_post_write_audit_package_task
    ),
    "shopify_translation_small_batch_apply_plan_package": run_shopify_translation_small_batch_apply_plan_package_task,
    "shopify_translation_small_batch_apply_execute": run_shopify_translation_small_batch_apply_execute_task,
    "shopify_translation_small_batch_post_write_audit_package": (
        run_shopify_translation_small_batch_post_write_audit_package_task
    ),
    "shopify_translation_small_batch_rollback_approval_package": (
        run_shopify_translation_small_batch_rollback_approval_package_task
    ),
    "shopify_translation_csv_json_small_batch_apply_plan_package": (
        run_shopify_translation_csv_json_small_batch_apply_plan_package_task
    ),
    "shopify_translation_csv_json_small_batch_real_write_readiness_package": (
        run_shopify_translation_csv_json_small_batch_real_write_readiness_package_task
    ),
    "shopify_translation_csv_json_small_batch_manual_real_run_test_package": (
        run_shopify_translation_csv_json_small_batch_manual_real_run_test_package_task
    ),
    "shopify_translation_csv_json_small_batch_post_write_audit_package": (
        run_shopify_translation_csv_json_small_batch_post_write_audit_package_task
    ),
    "shopify_translation_selected_product_missing_translation_draft_package": (
        run_shopify_translation_selected_product_missing_translation_draft_package_task
    ),
    "shopify_translation_selected_product_real_write_execute": (
        run_shopify_translation_selected_product_real_write_execute_task
    ),
    "shopify_translation_first_real_write_completion_audit": (
        run_shopify_translation_first_real_write_completion_audit_task
    ),
    "shopify_translation_small_batch_locked_dry_run_package": (
        run_shopify_translation_small_batch_locked_dry_run_package_task
    ),
    "shopify_translation_small_batch_real_write_gate_preflight": (
        run_shopify_translation_small_batch_real_write_gate_preflight_task
    ),
    "shopify_translation_small_batch_real_write_execute": (
        run_shopify_translation_small_batch_real_write_execute_task
    ),
    "shopify_translation_small_batch_post_write_audit": (
        run_shopify_translation_small_batch_post_write_audit_task
    ),
    "shopify_translation_next_batch_locked_dry_run_package": (
        run_shopify_translation_next_batch_locked_dry_run_package_task
    ),
    "shopify_translation_next_batch_real_write_execute": (
        run_shopify_translation_next_batch_real_write_execute_task
    ),
    "shopify_translation_next_batch_post_write_audit": (
        run_shopify_translation_next_batch_post_write_audit_task
    ),
    "shopify_translation_remaining_title_batch_locked_dry_run_package": (
        run_shopify_translation_remaining_title_batch_locked_dry_run_package_task
    ),
    "shopify_translation_multi_locale_dry_run": run_shopify_translation_multi_locale_dry_run_task,
    "shopify_translation_dry_run": run_shopify_translation_dry_run_task,
}


TASK_METADATA: Dict[str, dict] = {
    "demo": {
        "description": "Demo dry-run approval flow.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/demo_review.json",
    },
    "django_check": {
        "description": "Run fixed Django system check inside the Docker web service.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/django_check_review.json",
    },
    "git_safety_check": {
        "description": "Read-only Git working tree and secret-risk safety check.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/git_safety_check_review.json",
    },
    "shopify_review_request_ali_reviews_capability_discovery": {
        "description": "Generate a docs-only Ali Reviews / Kudosi capability discovery report.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_ali_reviews_capability_discovery.json",
    },
    "shopify_review_request_candidate_scan": {
        "description": "Run a read-only Shopify review request candidate scan and local dry-run report.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify order query",
        "review_file_path": "logs/shopify_review_request_candidate_scan.json",
    },
    "shopify_review_request_gmail_readiness_package": {
        "description": "Generate a docs-only Gmail send permission readiness package for review requests.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_gmail_readiness_package.json",
    },
    "shopify_review_request_gmail_oauth_setup_helper": {
        "description": "Generate a no-secret Gmail OAuth setup helper package for draft-only Trustpilot invitations.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_gmail_oauth_setup_helper.json",
    },
    "shopify_review_request_kudosi_api_403_diagnostics": {
        "description": "Generate read-only Kudosi / Ali Reviews HTTP 403 diagnostics without exposing secrets.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only external API GET",
        "review_file_path": "logs/shopify_review_request_kudosi_api_403_diagnostics.json",
    },
    "shopify_review_request_kudosi_api_capability_probe": {
        "description": "Run a read-only Kudosi / Ali Reviews public API capability probe.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only external API GET",
        "review_file_path": "logs/shopify_review_request_kudosi_api_capability_probe.json",
    },
    "shopify_review_request_manual_action_csv_export": {
        "description": "Generate a no-write CSV export from the Phase 1.2 review request manual action package.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_manual_action_csv_export.json",
    },
    "shopify_review_request_manual_action_package": {
        "description": "Generate a no-write manual action package from the Phase 1.1 review request scan.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_manual_action_package.json",
    },
    "shopify_review_request_shopify_tag_permission_readiness": {
        "description": "Generate a docs-only Shopify tag write permission readiness package.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_shopify_tag_permission_readiness.json",
    },
    "shopify_review_request_tag_discovery": {
        "description": "Read-only Shopify order tag discovery for review request automation preparation.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify order tag query",
        "review_file_path": "logs/shopify_review_request_tag_discovery.json",
    },
    "shopify_review_request_trustpilot_gmail_draft_package": {
        "description": "Generate a no-send Trustpilot Gmail draft package from the Phase 3.0 decision report.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none by default; optional Gmail drafts.create only behind explicit env gate",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_draft_package.json",
    },
    "shopify_review_request_trustpilot_gmail_draft_create_locked_test": {
        "description": "Run a locked at-most-one Gmail drafts.create test from the Phase 3.1 Trustpilot package.",
        "allowed_modes": ["dry-run"],
        "write_risk": "optional Gmail drafts.create only behind explicit env and ack gates",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_draft_create_locked_test.json",
    },
    "shopify_review_request_trustpilot_gmail_draft_content_update_pre_send": {
        "description": "Verify and if needed update the existing Trustpilot Gmail draft content before any send.",
        "allowed_modes": ["dry-run"],
        "write_risk": "Gmail drafts.get/drafts.update only; no send",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_draft_content_update_pre_send.json",
    },
    "shopify_review_request_trustpilot_gmail_oauth_readiness_preflight": {
        "description": "Check Gmail OAuth readiness and prepare a locked one-draft Trustpilot preflight.",
        "allowed_modes": ["dry-run"],
        "write_risk": "optional Gmail drafts.create only behind explicit env and ack gates",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_oauth_readiness_preflight.json",
    },
    "shopify_review_request_trustpilot_gmail_first_draft_audit": {
        "description": "Audit the first Trustpilot Gmail draft creation report without calling Gmail or Shopify.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_first_draft_audit.json",
    },
    "shopify_review_request_trustpilot_gmail_one_draft_locked_runner": {
        "description": "Run a locked at-most-one Trustpilot Gmail draft creation runner.",
        "allowed_modes": ["dry-run"],
        "write_risk": "optional Gmail drafts.create only behind explicit env and ack gates",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_one_draft_locked_runner.json",
    },
    "shopify_review_request_trustpilot_gmail_one_draft_send_locked_runner": {
        "description": "Validate locked gates for a future at-most-one Trustpilot Gmail draft send without sending.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; dry-run only",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_one_draft_send_locked_runner.json",
    },
    "shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight": {
        "description": "Generate the final manual approval preflight for a future one-draft Trustpilot Gmail send.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight.json",
    },
    "shopify_review_request_trustpilot_gmail_one_draft_send_execute": {
        "description": "Execute or dry-run a locked at-most-one Trustpilot Gmail draft send.",
        "allowed_modes": ["dry-run"],
        "write_risk": "Gmail drafts.send only when all explicit real-send gates are enabled",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_one_draft_send_execute.json",
    },
    "shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness": {
        "description": "Generate the no-send operator readiness package for a future one-draft Trustpilot Gmail real send.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness.json",
    },
    "shopify_review_request_trustpilot_gmail_send_tag_design_dry_run": {
        "description": "Generate a no-send/no-write Trustpilot Gmail draft send and Shopify tag design package.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_send_tag_design_dry_run.json",
    },
    "shopify_review_request_unified_decision_engine_dry_run": {
        "description": "Generate a unified no-write review request decision report from local Phase 1 reports.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_unified_decision_engine_dry_run.json",
    },
    "shopify_translation_dry_run": {
        "description": "Run fixed Shopify product translation preview for one configured test product.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_dry_run_review.json",
    },
    "shopify_translation_batch_apply_command_generate": {
        "description": "Generate a command-only Shopify translation apply plan from final validation.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_batch_apply_command_plan.json",
    },
    "shopify_translation_batch_apply_command_validate": {
        "description": "Validate command approval in the Shopify translation apply command plan without writing.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_batch_apply_command_validation.json",
    },
    "shopify_translation_batch_apply_execution_dry_run": {
        "description": "Simulate Shopify translation apply execution from command validation without writing.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_batch_apply_execution_dry_run.json",
    },
    "shopify_translation_batch_apply_execution_approval_validate": {
        "description": "Validate execution approval from the Shopify translation execution dry-run without writing.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_batch_apply_execution_approval_validation.json",
    },
    "shopify_translation_batch_apply_execution_preview": {
        "description": "Generate a preview-only Shopify translation apply execution list from validation results.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_batch_apply_execution_preview.json",
    },
    "shopify_translation_batch_apply_execution_final_validate": {
        "description": "Validate final approval in the Shopify translation apply execution preview without writing.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_batch_apply_execution_final_validation.json",
    },
    "shopify_translation_batch_apply_locked_runner": {
        "description": "Locked shell for Shopify translation apply execution; checks approvals without writing.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_batch_apply_locked_runner.json",
    },
    "shopify_translation_batch_apply_plan": {
        "description": "Generate a review-only apply plan from the latest Shopify batch translation dry-run review.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_batch_apply_plan.json",
    },
    "shopify_translation_batch_apply_plan_validate": {
        "description": "Validate manual decisions in the Shopify batch translation apply plan without writing to Shopify.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_batch_apply_plan_validation.json",
    },
    "shopify_translation_batch_multi_locale_dry_run": {
        "description": "Batch Shopify product multi-locale translation dry-run.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_batch_multi_locale_dry_run_review.json",
    },
    "shopify_translation_single_field_apply_sandbox_design": {
        "description": "Design a locked single-product single-locale single-field Shopify translation apply sandbox.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_apply_sandbox_design.json",
    },
    "shopify_translation_single_field_apply_sandbox_runner": {
        "description": "Run a forced dry-run single-product single-locale meta_title Shopify apply sandbox preview.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_apply_sandbox_runner.json",
    },
    "shopify_translation_single_field_apply_preflight_package": {
        "description": "Build a single-field Shopify translation apply preflight package without writing.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_apply_preflight_package.json",
    },
    "shopify_translation_single_field_backup_fetch": {
        "description": "Fetch a read-only single-field Shopify translation backup for a manual sandbox scope.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_backup_fetch.json",
    },
    "shopify_translation_single_field_readback_rollback_plan": {
        "description": "Generate a local readback and rollback plan from single-field preflight and backup reports.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_readback_rollback_plan.json",
    },
    "shopify_translation_single_field_final_write_gate": {
        "description": "Generate a local final write gate package for single-field Shopify translation apply.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_final_write_gate.json",
    },
    "shopify_translation_single_field_real_write_runner_design": {
        "description": "Generate a design-only package for a future single-field Shopify translation write runner.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_real_write_runner_design.json",
    },
    "shopify_translation_single_field_real_write_locked_runner": {
        "description": "Locked shell for a future single-field Shopify translation write runner; never writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_real_write_locked_runner.json",
    },
    "shopify_translation_single_field_real_write_pre_execution_validate": {
        "description": "Validate single-field Shopify translation write preconditions without executing writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_real_write_pre_execution_validate.json",
    },
    "shopify_translation_single_field_final_human_approval_package": {
        "description": "Generate the final human approval package before any future single-field Shopify write phase.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_final_human_approval_package.json",
    },
    "shopify_translation_single_field_real_write_runner_final_safe_shell": {
        "description": "Generate a final-safe locked shell report for a future single-field Shopify write runner.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_real_write_runner_final_safe_shell.json",
    },
    "shopify_translation_single_field_real_write_execution_plan": {
        "description": "Generate a local execution plan for a future single-field Shopify write test without writing.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_real_write_execution_plan.json",
    },
    "shopify_translation_single_field_real_write_one_shot_locked_shell": {
        "description": "Generate a one-shot locked shell report for a future single-field Shopify write test.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_real_write_one_shot_locked_shell.json",
    },
    "shopify_translation_single_field_real_write_one_shot_execute": {
        "description": "Execute or dry-run the locked one-shot single-field Shopify translation write with immediate readback.",
        "allowed_modes": ["dry-run", "real-run", "execute-real-write"],
        "write_risk": "high outside dry-run",
        "review_file_path": "logs/shopify_translation_single_field_real_write_one_shot_execute.json",
    },
    "shopify_translation_single_field_post_write_audit_package": {
        "description": "Generate a local post-write audit package from the one-shot execution report without new Shopify actions.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_post_write_audit_package.json",
    },
    "shopify_translation_single_field_rollback_approval_package": {
        "description": "Generate a local rollback approval package and restore plan without executing rollback.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_single_field_rollback_approval_package.json",
    },
    "shopify_translation_second_single_field_test_prepare": {
        "description": "Prepare a second one-shot single-field Shopify translation test without Shopify actions.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_second_single_field_test_prepare.json",
    },
    "shopify_translation_second_single_field_verified_backup_fetch": {
        "description": "Fetch a read-only verified backup for the second one-shot single-field Shopify test.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify query",
        "review_file_path": "logs/shopify_translation_second_single_field_verified_backup_fetch.json",
    },
    "shopify_translation_second_single_field_real_write_readiness": {
        "description": "Generate the final readiness package for a second one-shot single-field Shopify write.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_second_single_field_real_write_readiness.json",
    },
    "shopify_translation_second_single_field_real_write_execute": {
        "description": "Execute or dry-run the second one-shot single-field Shopify translation write with immediate readback.",
        "allowed_modes": ["dry-run", "real-run", "execute-real-write"],
        "write_risk": "high outside dry-run",
        "review_file_path": "logs/shopify_translation_second_single_field_real_write_execute.json",
    },
    "shopify_translation_second_single_field_post_write_audit_package": {
        "description": "Generate a local audit package from the second one-shot execution report without new Shopify actions.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_second_single_field_post_write_audit_package.json",
    },
    "shopify_translation_small_batch_apply_plan_package": {
        "description": "Generate a local small batch Shopify translation apply plan package without Shopify actions.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_small_batch_apply_plan_package.json",
    },
    "shopify_translation_small_batch_apply_execute": {
        "description": "Execute or dry-run a tightly scoped small batch Shopify translation apply with immediate readback.",
        "allowed_modes": ["dry-run", "real-run", "execute-real-write"],
        "write_risk": "high outside dry-run",
        "review_file_path": "logs/shopify_translation_small_batch_apply_execute.json",
    },
    "shopify_translation_small_batch_post_write_audit_package": {
        "description": "Generate a local post-write audit package from the small batch execution report without Shopify actions.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_small_batch_post_write_audit_package.json",
    },
    "shopify_translation_small_batch_rollback_approval_package": {
        "description": "Generate a local rollback approval / restore plan package from small batch reports without Shopify actions.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_small_batch_rollback_approval_package.json",
    },
    "shopify_translation_csv_json_small_batch_apply_plan_package": {
        "description": "Generate a local small batch Shopify apply plan from CSV or JSON input without Shopify actions.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_csv_json_small_batch_apply_plan_package.json",
    },
    "shopify_translation_csv_json_small_batch_real_write_readiness_package": {
        "description": "Generate a local CSV/JSON small batch real-write readiness package without Shopify actions.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_csv_json_small_batch_real_write_readiness_package.json",
    },
    "shopify_translation_csv_json_small_batch_manual_real_run_test_package": {
        "description": "Generate a local manual real-run test package for CSV/JSON small batch Shopify translation apply.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_csv_json_small_batch_manual_real_run_test_package.json",
    },
    "shopify_translation_csv_json_small_batch_post_write_audit_package": {
        "description": "Generate a local CSV/JSON small batch post-write audit package without new Shopify actions.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_csv_json_small_batch_post_write_audit_package.json",
    },
    "shopify_translation_selected_product_missing_translation_draft_package": {
        "description": "Generate local draft translations for missing selected product fields without Shopify writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify query plus OpenAI draft generation",
        "review_file_path": "logs/shopify_translation_selected_product_missing_translation_draft_package.json",
    },
    "shopify_translation_selected_product_real_write_execute": {
        "description": "Dry-run or execute the selected product translation real write with strict ACK, scope, digest, and readback verification gates.",
        "allowed_modes": ["dry-run", "real-run", "execute-real-write"],
        "write_risk": "high outside dry-run",
        "review_file_path": "logs/shopify_translation_selected_product_real_write_execute.json",
    },
    "shopify_translation_first_real_write_completion_audit": {
        "description": "Audit the first selected-product real translation write and prepare no-write small batch readiness.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify query plus OpenAI dry-run package generation",
        "review_file_path": "logs/shopify_translation_first_real_write_completion_audit.json",
    },
    "shopify_translation_small_batch_locked_dry_run_package": {
        "description": "Generate a no-write locked small-batch dry-run package for selected product meta_title translations.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify query plus OpenAI dry-run package generation",
        "review_file_path": "logs/shopify_translation_small_batch_locked_dry_run_package.json",
    },
    "shopify_translation_small_batch_real_write_gate_preflight": {
        "description": "Generate a dry-run/read-only real-write gate preflight for the locked selected-product small batch.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify query plus OpenAI dry-run package generation",
        "review_file_path": "logs/shopify_translation_small_batch_real_write_gate_preflight.json",
    },
    "shopify_translation_small_batch_real_write_execute": {
        "description": "Dry-run or execute the locked selected-product small batch translation write with strict ACK, scope, digest, and readback gates.",
        "allowed_modes": ["dry-run", "real-run", "execute-real-write"],
        "write_risk": "high outside dry-run",
        "review_file_path": "logs/shopify_translation_small_batch_real_write_execute.json",
    },
    "shopify_translation_small_batch_post_write_audit": {
        "description": "Audit the selected-product small batch real write and prepare no-write next-batch readiness.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify query plus OpenAI dry-run package generation",
        "review_file_path": "logs/shopify_translation_small_batch_post_write_audit.json",
    },
    "shopify_translation_next_batch_locked_dry_run_package": {
        "description": "Generate a no-write locked dry-run package for the next selected-product translation batch.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify query plus OpenAI dry-run package generation",
        "review_file_path": "logs/shopify_translation_next_batch_locked_dry_run_package.json",
    },
    "shopify_translation_next_batch_real_write_execute": {
        "description": "Dry-run or execute the locked selected-product next-batch translation write with strict ACK, scope, digest, SEO, and readback gates.",
        "allowed_modes": ["dry-run", "real-run", "execute-real-write"],
        "write_risk": "high outside dry-run",
        "review_file_path": "logs/shopify_translation_next_batch_real_write_execute.json",
    },
    "shopify_translation_next_batch_post_write_audit": {
        "description": "Audit the selected-product next-batch real write, confirm duplicate protection, and recommend remaining entries without new writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify query plus OpenAI dry-run package generation",
        "review_file_path": "logs/shopify_translation_next_batch_post_write_audit.json",
    },
    "shopify_translation_remaining_title_batch_locked_dry_run_package": {
        "description": "Generate a no-write locked dry-run package for the remaining selected-product title translations.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify query plus OpenAI dry-run package generation",
        "review_file_path": "logs/shopify_translation_remaining_title_batch_locked_dry_run_package.json",
    },
    "shopify_translation_multi_locale_dry_run": {
        "description": "Run fixed Shopify product translation previews for one product across de, fr, es, it, and ja.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_translation_multi_locale_dry_run_review.json",
    },
}


def get_task(task_name: str) -> TaskCallable:
    try:
        return TASK_REGISTRY[task_name]
    except KeyError as exc:
        allowed = ", ".join(sorted(TASK_REGISTRY))
        raise ValueError(f"Unknown task '{task_name}'. Allowed tasks: {allowed}") from exc


def get_task_metadata(task_name: str) -> dict:
    get_task(task_name)
    return TASK_METADATA[task_name]


def list_task_metadata() -> List[dict]:
    return [
        {"name": name, **TASK_METADATA[name]}
        for name in sorted(TASK_REGISTRY)
    ]
