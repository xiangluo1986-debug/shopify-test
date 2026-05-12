from typing import Callable, Dict, List

from remote_approval.tasks.django_check_task import run_django_check_task
from remote_approval.tasks.demo_task import run_demo_task
from remote_approval.tasks.git_safety_check_task import run_git_safety_check_task
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
