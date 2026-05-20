from typing import Callable, Dict, List

from remote_approval.tasks.django_check_task import run_django_check_task
from remote_approval.tasks.demo_task import run_demo_task
from remote_approval.tasks.git_safety_check_task import run_git_safety_check_task
from remote_approval.tasks.shopify_review_request_ali_reviews_capability_discovery_task import (
    run_shopify_review_request_ali_reviews_capability_discovery_task,
)
from remote_approval.tasks.shopify_review_request_ali_reviews_api_capability_discovery_task import (
    run_shopify_review_request_ali_reviews_api_capability_discovery_task,
)
from remote_approval.tasks.shopify_review_request_candidate_scan_task import (
    run_shopify_review_request_candidate_scan_task,
)
from remote_approval.tasks.shopify_review_request_customer_level_trustpilot_duplicate_audit_task import (
    run_shopify_review_request_customer_level_trustpilot_duplicate_audit_task,
)
from remote_approval.tasks.shopify_review_request_customer_history_trustpilot_guard_audit_task import (
    run_shopify_review_request_customer_history_trustpilot_guard_audit_task,
)
from remote_approval.tasks.shopify_review_request_customer_history_precision_audit_task import (
    run_shopify_review_request_customer_history_precision_audit_task,
)
from remote_approval.tasks.shopify_review_request_customer_lifetime_trustpilot_note_audit_task import (
    run_shopify_review_request_customer_lifetime_trustpilot_note_audit_task,
)
from remote_approval.tasks.shopify_review_request_customer_identity_drilldown_audit_task import (
    run_shopify_review_request_customer_identity_drilldown_audit_task,
)
from remote_approval.tasks.shopify_review_request_on_demand_customer_history_lookup_task import (
    run_shopify_review_request_on_demand_customer_history_lookup_task,
)
from remote_approval.tasks.shopify_review_request_batch_customer_history_lookup_task import (
    run_shopify_review_request_batch_customer_history_lookup_task,
)
from remote_approval.tasks.shopify_review_request_shopify_scope_verification_task import (
    run_shopify_review_request_shopify_scope_verification_task,
)
from remote_approval.tasks.shopify_review_request_shopify_oauth_reauthorization_helper_task import (
    run_shopify_review_request_shopify_oauth_reauthorization_helper_task,
)
from remote_approval.tasks.shopify_review_request_review_send_failure_audit_task import (
    run_shopify_review_request_review_send_failure_audit_task,
)
from remote_approval.tasks.shopify_review_request_dynamic_review_send_audit_task import (
    run_shopify_review_request_dynamic_review_send_audit_task,
)
from remote_approval.tasks.shopify_review_request_review_send_post_send_audit_task import (
    run_shopify_review_request_review_send_post_send_audit_task,
)
from remote_approval.tasks.shopify_review_request_review_send_reuse_gmail_helper_audit_task import (
    run_shopify_review_request_review_send_reuse_gmail_helper_audit_task,
)
from remote_approval.tasks.shopify_review_request_gmail_readiness_package_task import (
    run_shopify_review_request_gmail_readiness_package_task,
)
from remote_approval.tasks.shopify_review_request_gmail_oauth_setup_helper_task import (
    run_shopify_review_request_gmail_oauth_setup_helper_task,
)
from remote_approval.tasks.shopify_review_request_history_ledger_audit_task import (
    run_shopify_review_request_history_ledger_audit_task,
)
from remote_approval.tasks.shopify_review_request_dashboard_counts_audit_task import (
    run_shopify_review_request_dashboard_counts_audit_task,
)
from remote_approval.tasks.shopify_review_request_dashboard_snapshot_refresh_task import (
    run_shopify_review_request_dashboard_snapshot_refresh_task,
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
from remote_approval.tasks.shopify_review_request_next_repeat_customer_candidate_scan_task import (
    run_shopify_review_request_next_repeat_customer_candidate_scan_task,
)
from remote_approval.tasks.shopify_review_request_last_60_days_candidate_scan_task import (
    run_shopify_review_request_last_60_days_candidate_scan_task,
)
from remote_approval.tasks.shopify_review_request_live_history_gate_audit_task import (
    run_shopify_review_request_live_history_gate_audit_task,
)
from remote_approval.tasks.shopify_review_request_shopify_order_sync_coverage_task import (
    run_shopify_review_request_shopify_order_sync_coverage_task,
)
from remote_approval.tasks.shopify_review_request_order_tags_persistence_audit_task import (
    run_shopify_review_request_order_tags_persistence_audit_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_tag_exclusion_audit_task import (
    run_shopify_review_request_trustpilot_tag_exclusion_audit_task,
)
from remote_approval.tasks.shopify_review_request_tag_alias_and_candidate_correction_audit_task import (
    run_shopify_review_request_tag_alias_and_candidate_correction_audit_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_one_candidate_gmail_draft_package_task import (
    run_shopify_review_request_trustpilot_one_candidate_gmail_draft_package_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner_task import (
    run_shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute_task import (
    run_shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight_task import (
    run_shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute_task import (
    run_shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute_task,
)
from remote_approval.tasks.shopify_review_request_returned_package_guard_task import (
    run_shopify_review_request_returned_package_guard_task,
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
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_repeat_customer_guard_task import (
    run_shopify_review_request_trustpilot_gmail_repeat_customer_guard_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_send_audit_task import (
    run_shopify_review_request_trustpilot_gmail_send_audit_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_send_tag_design_dry_run_task import (
    run_shopify_review_request_trustpilot_gmail_send_tag_design_dry_run_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_completion_next_batch_design_task import (
    run_shopify_review_request_trustpilot_completion_next_batch_design_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_suppress_ali_reviews_design_task import (
    run_shopify_review_request_trustpilot_suppress_ali_reviews_design_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_automation_dry_run_task import (
    run_shopify_review_request_trustpilot_automation_dry_run_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_locked_send_readiness_package_task import (
    run_shopify_review_request_trustpilot_locked_send_readiness_package_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_auto_queue_refresh_task import (
    run_shopify_review_request_trustpilot_auto_queue_refresh_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_candidate_simulator_task import (
    run_shopify_review_request_trustpilot_candidate_simulator_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_locked_gmail_send_gate_task import (
    run_shopify_review_request_trustpilot_locked_gmail_send_gate_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_send_executor_shell_task import (
    run_shopify_review_request_trustpilot_gmail_send_executor_shell_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_real_send_final_preflight_task import (
    run_shopify_review_request_trustpilot_real_send_final_preflight_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_real_send_execute_task import (
    run_shopify_review_request_trustpilot_real_send_execute_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_real_send_readiness_audit_task import (
    run_shopify_review_request_trustpilot_gmail_real_send_readiness_audit_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_oauth_config_helper_task import (
    run_shopify_review_request_trustpilot_gmail_oauth_config_helper_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_config_compatibility_audit_task import (
    run_shopify_review_request_trustpilot_gmail_config_compatibility_audit_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_env_loading_audit_task import (
    run_shopify_review_request_trustpilot_gmail_env_loading_audit_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_scope_compatibility_resolver_task import (
    run_shopify_review_request_trustpilot_gmail_scope_compatibility_resolver_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_draft_only_preflight_task import (
    run_shopify_review_request_trustpilot_gmail_draft_only_preflight_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner_task import (
    run_shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner_task,
)
from remote_approval.tasks.shopify_review_request_order_sync_auto_refresh_hook_audit_task import (
    run_shopify_review_request_order_sync_auto_refresh_hook_audit_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_tag_write_design_dry_run_task import (
    run_shopify_review_request_trustpilot_tag_write_design_dry_run_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_tag_write_audit_task import (
    run_shopify_review_request_trustpilot_tag_write_audit_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_tag_write_execute_task import (
    run_shopify_review_request_trustpilot_tag_write_execute_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_tag_write_final_preflight_task import (
    run_shopify_review_request_trustpilot_tag_write_final_preflight_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_tag_write_locked_runner_task import (
    run_shopify_review_request_trustpilot_tag_write_locked_runner_task,
)
from remote_approval.tasks.shopify_review_request_trustpilot_post_send_tag_write_task import (
    run_shopify_review_request_trustpilot_post_send_tag_write_task,
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
from remote_approval.tasks.shopify_translation_translatable_resource_mapping_audit_task import (
    run_shopify_translation_translatable_resource_mapping_audit_task,
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
from remote_approval.tasks.shopify_translation_remaining_title_batch_real_write_execute_task import (
    run_shopify_translation_remaining_title_batch_real_write_execute_task,
)
from remote_approval.tasks.shopify_translation_remaining_title_batch_post_write_audit_task import (
    run_shopify_translation_remaining_title_batch_post_write_audit_task,
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
    "shopify_review_request_ali_reviews_api_capability_discovery": (
        run_shopify_review_request_ali_reviews_api_capability_discovery_task
    ),
    "shopify_review_request_candidate_scan": run_shopify_review_request_candidate_scan_task,
    "shopify_review_request_customer_level_trustpilot_duplicate_audit": (
        run_shopify_review_request_customer_level_trustpilot_duplicate_audit_task
    ),
    "shopify_review_request_customer_history_trustpilot_guard_audit": (
        run_shopify_review_request_customer_history_trustpilot_guard_audit_task
    ),
    "shopify_review_request_customer_history_precision_audit": (
        run_shopify_review_request_customer_history_precision_audit_task
    ),
    "shopify_review_request_customer_lifetime_trustpilot_note_audit": (
        run_shopify_review_request_customer_lifetime_trustpilot_note_audit_task
    ),
    "shopify_review_request_customer_identity_drilldown_audit": (
        run_shopify_review_request_customer_identity_drilldown_audit_task
    ),
    "shopify_review_request_on_demand_customer_history_lookup": (
        run_shopify_review_request_on_demand_customer_history_lookup_task
    ),
    "shopify_review_request_batch_customer_history_lookup": (
        run_shopify_review_request_batch_customer_history_lookup_task
    ),
    "shopify_review_request_shopify_scope_verification": (
        run_shopify_review_request_shopify_scope_verification_task
    ),
    "shopify_review_request_shopify_oauth_reauthorization_helper": (
        run_shopify_review_request_shopify_oauth_reauthorization_helper_task
    ),
    "shopify_review_request_review_send_failure_audit": (
        run_shopify_review_request_review_send_failure_audit_task
    ),
    "shopify_review_request_dynamic_review_send_audit": (
        run_shopify_review_request_dynamic_review_send_audit_task
    ),
    "shopify_review_request_review_send_post_send_audit": (
        run_shopify_review_request_review_send_post_send_audit_task
    ),
    "shopify_review_request_review_send_reuse_gmail_helper_audit": (
        run_shopify_review_request_review_send_reuse_gmail_helper_audit_task
    ),
    "shopify_review_request_gmail_readiness_package": run_shopify_review_request_gmail_readiness_package_task,
    "shopify_review_request_gmail_oauth_setup_helper": run_shopify_review_request_gmail_oauth_setup_helper_task,
    "shopify_review_request_history_ledger_audit": run_shopify_review_request_history_ledger_audit_task,
    "shopify_review_request_dashboard_counts_audit": run_shopify_review_request_dashboard_counts_audit_task,
    "shopify_review_request_dashboard_snapshot_refresh": (
        run_shopify_review_request_dashboard_snapshot_refresh_task
    ),
    "shopify_review_request_kudosi_api_403_diagnostics": run_shopify_review_request_kudosi_api_403_diagnostics_task,
    "shopify_review_request_kudosi_api_capability_probe": run_shopify_review_request_kudosi_api_capability_probe_task,
    "shopify_review_request_manual_action_csv_export": run_shopify_review_request_manual_action_csv_export_task,
    "shopify_review_request_manual_action_package": run_shopify_review_request_manual_action_package_task,
    "shopify_review_request_next_repeat_customer_candidate_scan": (
        run_shopify_review_request_next_repeat_customer_candidate_scan_task
    ),
    "shopify_review_request_last_60_days_candidate_scan": (
        run_shopify_review_request_last_60_days_candidate_scan_task
    ),
    "shopify_review_request_live_history_gate_audit": (
        run_shopify_review_request_live_history_gate_audit_task
    ),
    "shopify_review_request_shopify_order_sync_coverage": (
        run_shopify_review_request_shopify_order_sync_coverage_task
    ),
    "shopify_review_request_order_tags_persistence_audit": (
        run_shopify_review_request_order_tags_persistence_audit_task
    ),
    "shopify_review_request_trustpilot_tag_exclusion_audit": (
        run_shopify_review_request_trustpilot_tag_exclusion_audit_task
    ),
    "shopify_review_request_tag_alias_and_candidate_correction_audit": (
        run_shopify_review_request_tag_alias_and_candidate_correction_audit_task
    ),
    "shopify_review_request_trustpilot_one_candidate_gmail_draft_package": (
        run_shopify_review_request_trustpilot_one_candidate_gmail_draft_package_task
    ),
    "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner": (
        run_shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner_task
    ),
    "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute": (
        run_shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute_task
    ),
    "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight": (
        run_shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight_task
    ),
    "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute": (
        run_shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute_task
    ),
    "shopify_review_request_returned_package_guard": run_shopify_review_request_returned_package_guard_task,
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
    "shopify_review_request_trustpilot_gmail_repeat_customer_guard": (
        run_shopify_review_request_trustpilot_gmail_repeat_customer_guard_task
    ),
    "shopify_review_request_trustpilot_gmail_send_audit": (
        run_shopify_review_request_trustpilot_gmail_send_audit_task
    ),
    "shopify_review_request_trustpilot_gmail_send_tag_design_dry_run": (
        run_shopify_review_request_trustpilot_gmail_send_tag_design_dry_run_task
    ),
    "shopify_review_request_trustpilot_completion_next_batch_design": (
        run_shopify_review_request_trustpilot_completion_next_batch_design_task
    ),
    "shopify_review_request_trustpilot_suppress_ali_reviews_design": (
        run_shopify_review_request_trustpilot_suppress_ali_reviews_design_task
    ),
    "shopify_review_request_trustpilot_automation_dry_run": (
        run_shopify_review_request_trustpilot_automation_dry_run_task
    ),
    "shopify_review_request_trustpilot_locked_send_readiness_package": (
        run_shopify_review_request_trustpilot_locked_send_readiness_package_task
    ),
    "shopify_review_request_trustpilot_auto_queue_refresh": (
        run_shopify_review_request_trustpilot_auto_queue_refresh_task
    ),
    "shopify_review_request_trustpilot_candidate_simulator": (
        run_shopify_review_request_trustpilot_candidate_simulator_task
    ),
    "shopify_review_request_trustpilot_locked_gmail_send_gate": (
        run_shopify_review_request_trustpilot_locked_gmail_send_gate_task
    ),
    "shopify_review_request_trustpilot_gmail_send_executor_shell": (
        run_shopify_review_request_trustpilot_gmail_send_executor_shell_task
    ),
    "shopify_review_request_trustpilot_real_send_final_preflight": (
        run_shopify_review_request_trustpilot_real_send_final_preflight_task
    ),
    "shopify_review_request_trustpilot_real_send_execute": (
        run_shopify_review_request_trustpilot_real_send_execute_task
    ),
    "shopify_review_request_trustpilot_gmail_real_send_readiness_audit": (
        run_shopify_review_request_trustpilot_gmail_real_send_readiness_audit_task
    ),
    "shopify_review_request_trustpilot_gmail_oauth_config_helper": (
        run_shopify_review_request_trustpilot_gmail_oauth_config_helper_task
    ),
    "shopify_review_request_trustpilot_gmail_config_compatibility_audit": (
        run_shopify_review_request_trustpilot_gmail_config_compatibility_audit_task
    ),
    "shopify_review_request_trustpilot_gmail_env_loading_audit": (
        run_shopify_review_request_trustpilot_gmail_env_loading_audit_task
    ),
    "shopify_review_request_trustpilot_gmail_scope_compatibility_resolver": (
        run_shopify_review_request_trustpilot_gmail_scope_compatibility_resolver_task
    ),
    "shopify_review_request_trustpilot_gmail_draft_only_preflight": (
        run_shopify_review_request_trustpilot_gmail_draft_only_preflight_task
    ),
    "shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner": (
        run_shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner_task
    ),
    "shopify_review_request_order_sync_auto_refresh_hook_audit": (
        run_shopify_review_request_order_sync_auto_refresh_hook_audit_task
    ),
    "shopify_review_request_trustpilot_tag_write_design_dry_run": (
        run_shopify_review_request_trustpilot_tag_write_design_dry_run_task
    ),
    "shopify_review_request_trustpilot_tag_write_audit": (
        run_shopify_review_request_trustpilot_tag_write_audit_task
    ),
    "shopify_review_request_trustpilot_tag_write_execute": (
        run_shopify_review_request_trustpilot_tag_write_execute_task
    ),
    "shopify_review_request_trustpilot_tag_write_final_preflight": (
        run_shopify_review_request_trustpilot_tag_write_final_preflight_task
    ),
    "shopify_review_request_trustpilot_tag_write_locked_runner": (
        run_shopify_review_request_trustpilot_tag_write_locked_runner_task
    ),
    "shopify_review_request_trustpilot_post_send_tag_write": (
        run_shopify_review_request_trustpilot_post_send_tag_write_task
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
    "shopify_translation_translatable_resource_mapping_audit": (
        run_shopify_translation_translatable_resource_mapping_audit_task
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
    "shopify_translation_remaining_title_batch_real_write_execute": (
        run_shopify_translation_remaining_title_batch_real_write_execute_task
    ),
    "shopify_translation_remaining_title_batch_post_write_audit": (
        run_shopify_translation_remaining_title_batch_post_write_audit_task
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
    "shopify_review_request_ali_reviews_api_capability_discovery": {
        "description": "Generate a read-only Phase 5.0 Ali Reviews / Kudosi API capability matrix from local code/docs and env-name presence.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_ali_reviews_api_capability_discovery.json",
    },
    "shopify_review_request_candidate_scan": {
        "description": "Run a read-only Shopify review request candidate scan and local dry-run report.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify order query",
        "review_file_path": "logs/shopify_review_request_candidate_scan.json",
    },
    "shopify_review_request_customer_level_trustpilot_duplicate_audit": {
        "description": "Audit customer-level Trustpilot duplicate invitation suppression for #22620 against prior local reports and DB identity.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local DB/read-only report audit only",
        "review_file_path": "logs/shopify_review_request_customer_level_trustpilot_duplicate_audit.json",
    },
    "shopify_review_request_customer_history_trustpilot_guard_audit": {
        "description": "Audit local customer history, first-order blocking, and prior Trustpilot tag suppression without APIs or writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local ShopifyOrder/report audit only",
        "review_file_path": "logs/shopify_review_request_customer_history_trustpilot_guard_audit.json",
    },
    "shopify_review_request_customer_history_precision_audit": {
        "description": "Audit exact customer-history matching and note-based aftersales/ticket blockers for Review & Send without APIs or writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local ShopifyOrder/report audit only",
        "review_file_path": "logs/shopify_review_request_customer_history_precision_audit.json",
    },
    "shopify_review_request_customer_lifetime_trustpilot_note_audit": {
        "description": "Audit lifetime customer order count and historical Trustpilot note evidence for #21687 without APIs or writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local ShopifyOrder/report audit only, no full note output",
        "review_file_path": "logs/shopify_review_request_customer_lifetime_trustpilot_note_audit.json",
    },
    "shopify_review_request_customer_identity_drilldown_audit": {
        "description": "Drill down #21687 local identity matching strategies and historical Trustpilot note evidence without APIs or writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local ShopifyOrder/report audit only, no raw contact or full note output",
        "review_file_path": "logs/shopify_review_request_customer_identity_drilldown_audit.json",
    },
    "shopify_review_request_on_demand_customer_history_lookup": {
        "description": "Run a selected-order read-only Shopify customer history lookup and block Review & Send when live history is missing or shows Trustpilot evidence.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify order/customer history query only; no writes, no Gmail, no raw contact or full note output",
        "review_file_path": "logs/codex_runs/shopify_review_request_on_demand_customer_history_lookup.json",
    },
    "shopify_review_request_batch_customer_history_lookup": {
        "description": "Run read-only batch Shopify customer history lookups for base-eligible review request candidates and cache sanitized results.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify order/customer history query only; no writes, no Gmail, no raw contact or full note output",
        "review_file_path": "logs/codex_runs/shopify_review_request_batch_customer_history_lookup.json",
    },
    "shopify_review_request_shopify_scope_verification": {
        "description": "Verify the active Shopify token has read_orders and read_all_orders for Review Request full-history checks.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify access scope endpoint only; no writes, no Gmail, no token output",
        "review_file_path": "logs/codex_runs/shopify_review_request_shopify_scope_verification.json",
    },
    "shopify_review_request_shopify_oauth_reauthorization_helper": {
        "description": "Prepare the manual Shopify OAuth reauthorization helper flow for scope updates such as read_all_orders.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; docs/report only, no Shopify API call, no token exchange, no .env write",
        "review_file_path": "logs/codex_runs/shopify_review_request_shopify_oauth_reauthorization_helper.json",
    },
    "shopify_review_request_review_send_failure_audit": {
        "description": "Diagnose the latest Review & Send failure for #21075 without Gmail, Shopify, or external review writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local report audit only",
        "review_file_path": "logs/shopify_review_request_review_send_failure_audit.json",
    },
    "shopify_review_request_dynamic_review_send_audit": {
        "description": "Audit latest-customer filtering and dynamic Review & Send Gmail readiness without Gmail or Shopify calls.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local report audit only, no Gmail/Shopify/API calls",
        "review_file_path": "logs/shopify_review_request_dynamic_review_send_audit.json",
    },
    "shopify_review_request_review_send_post_send_audit": {
        "description": "Verify the latest local Review & Send success report and mark the order/customer as locally sent with Shopify tag pending.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local report audit only, no Gmail/Shopify/API calls",
        "review_file_path": "logs/codex_runs/shopify_review_request_review_send_post_send_audit.json",
    },
    "shopify_review_request_review_send_reuse_gmail_helper_audit": {
        "description": "Audit whether the proven #22621 Gmail drafts.send helper can be reused by admin Review & Send without Gmail or Shopify calls.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; source inspection only, no Gmail/Shopify/API calls",
        "review_file_path": "logs/codex_runs/shopify_review_request_review_send_reuse_gmail_helper_audit.json",
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
    "shopify_review_request_history_ledger_audit": {
        "description": "Generate a read-only Trustpilot review request history/debug ledger audit from local JSON reports.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local report history audit only",
        "review_file_path": "logs/shopify_review_request_history_ledger_audit.json",
    },
    "shopify_review_request_dashboard_counts_audit": {
        "description": "Audit Review Request dashboard counters and Already sent pagination without Gmail, Shopify, or external review API calls.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local dashboard count audit only",
        "review_file_path": "logs/codex_runs/shopify_review_request_dashboard_counts_audit.json",
    },
    "shopify_review_request_dashboard_snapshot_refresh": {
        "description": "Refresh the cached Review Requests dashboard snapshot from local synced order data and local reports without external APIs or writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; writes local dashboard snapshot JSON/HTML only",
        "review_file_path": "logs/shopify_review_request_dashboard_snapshot.json",
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
    "shopify_review_request_next_repeat_customer_candidate_scan": {
        "description": "Scan local reports for the next safe repeat-customer Trustpilot candidate without APIs or writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_next_repeat_customer_candidate_scan.json",
    },
    "shopify_review_request_last_60_days_candidate_scan": {
        "description": "Scan synced local Shopify orders from the last 60 days for actually reviewable Trustpilot candidates without APIs or writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local synced order/report scan only",
        "review_file_path": "logs/shopify_review_request_last_60_days_candidate_scan.json",
    },
    "shopify_review_request_live_history_gate_audit": {
        "description": "Audit the mandatory live Shopify customer history gate for #21687 and visible Review & Send rows using local reports only.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local report audit only, no Shopify/Gmail/API calls",
        "review_file_path": "logs/codex_runs/shopify_review_request_live_history_gate_audit.json",
    },
    "shopify_review_request_shopify_order_sync_coverage": {
        "description": "Check local Shopify order coverage for Review Requests and prepare safe 60-day / 3-day sync commands without calling Shopify.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local coverage check and report-only candidate scan",
        "review_file_path": "logs/shopify_review_request_shopify_order_sync_coverage.json",
    },
    "shopify_review_request_order_tags_persistence_audit": {
        "description": "Audit persisted local Shopify order tags for Review Request scans without Shopify, Gmail, or external review API calls.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local ShopifyOrder tag storage and report-only candidate scan",
        "review_file_path": "logs/shopify_review_request_order_tags_persistence_audit.json",
    },
    "shopify_review_request_trustpilot_tag_exclusion_audit": {
        "description": "Audit that Trustpilot sent tag aliases exclude #21225 and any tagged order from Needs review without APIs or writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local candidate scan/report audit only",
        "review_file_path": "logs/codex_runs/shopify_review_request_trustpilot_tag_exclusion_audit.json",
    },
    "shopify_review_request_tag_alias_and_candidate_correction_audit": {
        "description": "Audit review-request tag alias detection and #22562 eligibility correction without APIs or writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local workbench/report audit only",
        "review_file_path": "logs/shopify_review_request_tag_alias_and_candidate_correction_audit.json",
    },
    "shopify_review_request_trustpilot_one_candidate_gmail_draft_package": {
        "description": "Generate a local one-candidate Trustpilot Gmail draft preview from the Phase 4.0 candidate scan without APIs or writes.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_trustpilot_one_candidate_gmail_draft_package.json",
    },
    "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner": {
        "description": "Validate the locked no-write one-candidate Trustpilot Gmail draft creation preflight.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; preflight only",
        "review_file_path": "logs/shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner.json",
    },
    "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute": {
        "description": "Dry-run or execute a locked exactly-one Trustpilot Gmail draft create for selected order #22620.",
        "allowed_modes": ["dry-run", "real-run"],
        "write_risk": "Gmail drafts.create only in real-run when DRY_RUN=0 and every exact Phase 4.6A ACK gate is valid",
        "review_file_path": "logs/shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute.json",
    },
    "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight": {
        "description": "Prepare a locked no-send preflight for the verified Trustpilot Gmail draft for selected order #22620.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; preflight only",
        "review_file_path": "logs/shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight.json",
    },
    "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute": {
        "description": "Dry-run or execute a locked exactly-one Trustpilot Gmail draft send for selected order #22620 with runtime draft ID resolution.",
        "allowed_modes": ["dry-run", "real-run"],
        "write_risk": "Gmail drafts.list/get/send only in real-run when DRY_RUN=0 and every exact Phase 4.8B ACK gate is valid",
        "review_file_path": "logs/shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute.json",
    },
    "shopify_review_request_returned_package_guard": {
        "description": "Run a read-only return/returned package tag guard before any review request send path.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify lookup only",
        "review_file_path": "logs/shopify_review_request_returned_package_guard.json",
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
    "shopify_review_request_trustpilot_gmail_repeat_customer_guard": {
        "description": "Run a read-only repeat-customer guard before any Trustpilot Gmail real send.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify lookup only",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_repeat_customer_guard.json",
    },
    "shopify_review_request_trustpilot_gmail_send_audit": {
        "description": "Audit the one-draft Trustpilot Gmail send report without new Gmail, Shopify, or Kudosi actions.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_send_audit.json",
    },
    "shopify_review_request_trustpilot_gmail_send_tag_design_dry_run": {
        "description": "Generate a no-send/no-write Trustpilot Gmail draft send and Shopify tag design package.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_send_tag_design_dry_run.json",
    },
    "shopify_review_request_trustpilot_completion_next_batch_design": {
        "description": "Summarize the completed one-order Trustpilot workflow and generate the next-batch safety design.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_trustpilot_completion_next_batch_design.json",
    },
    "shopify_review_request_trustpilot_suppress_ali_reviews_design": {
        "description": "Design no-write Ali Reviews/Kudosi suppression and exact review-request tag cleanup for Trustpilot-completed orders.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify tag readback only; no mutations or tagsRemove",
        "review_file_path": "logs/shopify_review_request_trustpilot_suppress_ali_reviews_design.json",
    },
    "shopify_review_request_trustpilot_automation_dry_run": {
        "description": "Orchestrate Trustpilot email automation readiness from local reports without Gmail, Shopify, or external API calls.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local report orchestration only",
        "review_file_path": "logs/shopify_review_request_trustpilot_automation_dry_run.json",
    },
    "shopify_review_request_trustpilot_locked_send_readiness_package": {
        "description": "Build a dry-run Trustpilot queue and locked send readiness package from local reports without Gmail, Shopify, or external API calls.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local report readiness package only",
        "review_file_path": "logs/shopify_review_request_trustpilot_locked_send_readiness_package.json",
    },
    "shopify_review_request_trustpilot_auto_queue_refresh": {
        "description": "Refresh the Trustpilot queue status for the dashboard from local reports without Gmail, Shopify, or external API calls.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local dashboard status refresh only",
        "review_file_path": "logs/shopify_review_request_trustpilot_auto_queue_refresh.json",
    },
    "shopify_review_request_trustpilot_candidate_simulator": {
        "description": "Generate fake local-only Trustpilot candidate fixtures for testing the locked Gmail send gate and executor shell.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; synthetic simulator fixture only",
        "review_file_path": "logs/shopify_review_request_trustpilot_candidate_simulator.json",
    },
    "shopify_review_request_trustpilot_locked_gmail_send_gate": {
        "description": "Validate the locked Trustpilot Gmail send gate from local reports without calling Gmail, Shopify, or external review APIs.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local send gate report only",
        "review_file_path": "logs/shopify_review_request_trustpilot_locked_gmail_send_gate.json",
    },
    "shopify_review_request_trustpilot_gmail_send_executor_shell": {
        "description": "Validate the no-send Trustpilot Gmail send executor shell from the locked gate report without calling Gmail, Shopify, or external review APIs.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; no-send executor shell report only",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_send_executor_shell.json",
    },
    "shopify_review_request_trustpilot_real_send_final_preflight": {
        "description": "Run the final no-send Trustpilot Gmail send preflight from production reports, ignoring simulator fixtures unless explicitly enabled.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; final preflight report only",
        "review_file_path": "logs/shopify_review_request_trustpilot_real_send_final_preflight.json",
    },
    "shopify_review_request_trustpilot_real_send_execute": {
        "description": "Run the locked Trustpilot real-send execute skeleton from final preflight without calling Gmail, Shopify, or external review APIs.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; execute skeleton report only",
        "review_file_path": "logs/shopify_review_request_trustpilot_real_send_execute.json",
    },
    "shopify_review_request_trustpilot_gmail_real_send_readiness_audit": {
        "description": "Audit local readiness for a future Trustpilot Gmail real-send implementation without calling Gmail, Shopify, or external review APIs.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local readiness audit report only",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_real_send_readiness_audit.json",
    },
    "shopify_review_request_trustpilot_gmail_oauth_config_helper": {
        "description": "Diagnose missing Gmail OAuth/config path requirements for future Trustpilot real-send readiness without calling Gmail or reading token files.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local config-name and path-existence helper report only",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_oauth_config_helper.json",
    },
    "shopify_review_request_trustpilot_gmail_config_compatibility_audit": {
        "description": "Audit legacy and new Gmail config-name compatibility for Trustpilot review requests without calling Gmail or reading token files.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local config-name compatibility report only",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_config_compatibility_audit.json",
    },
    "shopify_review_request_trustpilot_gmail_env_loading_audit": {
        "description": "Audit Gmail env loading and scope injection for Trustpilot review requests without calling Gmail or reading secret values.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local env-key and loader-marker audit report only",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_env_loading_audit.json",
    },
    "shopify_review_request_trustpilot_gmail_scope_compatibility_resolver": {
        "description": "Resolve configured Gmail scope compatibility for Trustpilot review requests without calling Gmail, creating drafts, or sending email.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local scope compatibility report only",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_scope_compatibility_resolver.json",
    },
    "shopify_review_request_trustpilot_gmail_draft_only_preflight": {
        "description": "Prepare the Trustpilot Gmail draft-only route for one future draft without calling Gmail, creating drafts, sending email, or writing Shopify.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local draft-only preflight report only",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_draft_only_preflight.json",
    },
    "shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner": {
        "description": "Explain missing requirements for one future Trustpilot Gmail draft creation without calling Gmail or creating a draft.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; locked shell report only",
        "review_file_path": "logs/shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner.json",
    },
    "shopify_review_request_order_sync_auto_refresh_hook_audit": {
        "description": "Audit the dry-run Trustpilot queue auto-refresh hook after Shopify order sync completion.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; local source/report audit only",
        "review_file_path": "logs/shopify_review_request_order_sync_auto_refresh_hook_audit.json",
    },
    "shopify_review_request_trustpilot_tag_write_design_dry_run": {
        "description": "Generate a no-write Trustpilot Shopify tag-write design package after Gmail send audit.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none",
        "review_file_path": "logs/shopify_review_request_trustpilot_tag_write_design_dry_run.json",
    },
    "shopify_review_request_trustpilot_tag_write_audit": {
        "description": "Audit the Trustpilot Shopify tag write with read-only tag readback and tolerant legacy tag matching.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify tag readback; no mutations",
        "review_file_path": "logs/shopify_review_request_trustpilot_tag_write_audit.json",
    },
    "shopify_review_request_trustpilot_tag_write_execute": {
        "description": "Validate the locked executor shell for a future one-tag Trustpilot Shopify tag write without writing.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none in Phase 3.21; future Shopify tagsAdd only behind explicit gates",
        "review_file_path": "logs/shopify_review_request_trustpilot_tag_write_execute.json",
    },
    "shopify_review_request_trustpilot_tag_write_final_preflight": {
        "description": "Generate the final no-write preflight package before a future one-tag Trustpilot Shopify tag write.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none; future Shopify tagsAdd only behind explicit gates",
        "review_file_path": "logs/shopify_review_request_trustpilot_tag_write_final_preflight.json",
    },
    "shopify_review_request_trustpilot_tag_write_locked_runner": {
        "description": "Validate locked gates for a future one-tag Trustpilot Shopify tag write without writing.",
        "allowed_modes": ["dry-run"],
        "write_risk": "none in Phase 3.19; future Shopify tagsAdd only behind explicit gates",
        "review_file_path": "logs/shopify_review_request_trustpilot_tag_write_locked_runner.json",
    },
    "shopify_review_request_trustpilot_post_send_tag_write": {
        "description": "Write the audited Trustpilot completion tag and remove review-request trigger aliases for one post-send audited order behind exact env approval.",
        "allowed_modes": ["dry-run"],
        "write_risk": "Shopify tagsAdd/tagsRemove only when SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_WRITE matches the exact approval phrase",
        "review_file_path": "logs/codex_runs/shopify_review_request_trustpilot_post_send_tag_write.json",
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
    "shopify_translation_translatable_resource_mapping_audit": {
        "description": "Read-only Shopify translatableResource mapping audit for options, variants, and metafields.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify GraphQL query",
        "review_file_path": "logs/shopify_translation_translatable_resource_mapping_audit.json",
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
    "shopify_translation_remaining_title_batch_real_write_execute": {
        "description": "Dry-run or execute the locked selected-product remaining title translation write with strict ACK, scope, digest, SEO, and readback gates.",
        "allowed_modes": ["dry-run", "real-run", "execute-real-write"],
        "write_risk": "high outside dry-run",
        "review_file_path": "logs/shopify_translation_remaining_title_batch_real_write_execute.json",
    },
    "shopify_translation_remaining_title_batch_post_write_audit": {
        "description": "Audit the selected-product remaining-title real write, confirm duplicate protection, and verify no configured SEO fields remain eligible.",
        "allowed_modes": ["dry-run"],
        "write_risk": "read-only Shopify query plus OpenAI dry-run package generation",
        "review_file_path": "logs/shopify_translation_remaining_title_batch_post_write_audit.json",
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
