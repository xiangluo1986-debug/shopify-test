def run_demo_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError("The demo task only supports dry-run mode in this phase.")

    return {
        "checked_items": 10,
        "warnings": 2,
        "next_step": "generate_review_file",
    }
