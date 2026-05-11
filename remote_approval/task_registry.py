from typing import Callable, Dict

from remote_approval.tasks.django_check_task import run_django_check_task
from remote_approval.tasks.demo_task import run_demo_task
from remote_approval.tasks.shopify_translation_task import run_shopify_translation_dry_run_task


TaskCallable = Callable[[str], dict]


TASK_REGISTRY: Dict[str, TaskCallable] = {
    "demo": run_demo_task,
    "django_check": run_django_check_task,
    "shopify_translation_dry_run": run_shopify_translation_dry_run_task,
}


def get_task(task_name: str) -> TaskCallable:
    try:
        return TASK_REGISTRY[task_name]
    except KeyError as exc:
        allowed = ", ".join(sorted(TASK_REGISTRY))
        raise ValueError(f"Unknown task '{task_name}'. Allowed tasks: {allowed}") from exc
