from typing import Callable, Dict, List

from remote_approval.tasks.django_check_task import run_django_check_task
from remote_approval.tasks.demo_task import run_demo_task
from remote_approval.tasks.git_safety_check_task import run_git_safety_check_task
from remote_approval.tasks.shopify_translation_multi_locale_task import (
    run_shopify_translation_multi_locale_dry_run_task,
)
from remote_approval.tasks.shopify_translation_task import run_shopify_translation_dry_run_task


TaskCallable = Callable[[str], dict]


TASK_REGISTRY: Dict[str, TaskCallable] = {
    "demo": run_demo_task,
    "django_check": run_django_check_task,
    "git_safety_check": run_git_safety_check_task,
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
