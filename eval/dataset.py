"""
IaC-Eval dataset loader.

Sources:
  v1: HuggingFace autoiac-project/iac-eval (CC-BY-4.0)
  v2: HuggingFace iac-eval-v2/iac-eval-v2 (Apache-2.0)

Configs:
  v1: "quick_test" or "default"
  v2: "default"

Key fields per task:
  prompt            — natural-language IaC request
  resources         — comma-separated AWS resource types
  difficulty        — int 1-6
  reference_output  — ground-truth HCL
  rego_intent       — per-task OPA/Rego policy string
"""
from __future__ import annotations

import os


DATASETS = {
    "iac-eval-v1": "autoiac-project/iac-eval",
    "iac-eval": "autoiac-project/iac-eval",
    "autoiac-project/iac-eval": "autoiac-project/iac-eval",
    "iac-eval-v2": "iac-eval-v2/iac-eval-v2",
    "iac-eval-v2/iac-eval-v2": "iac-eval-v2/iac-eval-v2",
}


def _row_value(row: dict, *keys: str, default: object = "") -> object:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return default


def _difficulty(value: object) -> int:
    try:
        return int(value) if value is not None and value != "" else 0
    except (TypeError, ValueError):
        return 0


def load_tasks(
    dataset: str = "iac-eval-v1",
    config: str = "quick_test",
    iac_eval_dir: str | None = None,
    limit: int | None = None,
    difficulties: list[int] | None = None,
    task_ids: list[str] | None = None,
) -> list[dict]:
    """
    Load and filter IaC-Eval tasks.

    If iac_eval_dir points to a local clone of autoiac-project/iac-eval that
    contains a pre-downloaded HuggingFace cache at <iac_eval_dir>/.hf_cache,
    the dataset is loaded offline from that cache.  Falls back to a live HF
    download when the cache is absent.

    Returns list of dicts with normalized keys:
      id, prompt, resources, difficulty, reference_output, rego_intent
    """
    from datasets import load_dataset  # type: ignore[import]

    dataset_id = DATASETS.get(dataset, dataset)

    cache_dir: str | None = None
    if iac_eval_dir:
        candidate = os.path.join(iac_eval_dir, ".hf_cache")
        if os.path.isdir(candidate):
            cache_dir = candidate

    ds = load_dataset(
        dataset_id,
        config,
        cache_dir=cache_dir,  # None → default HF cache (live download)
    )
    # The dataset typically has a single "train" split
    split = ds["train"] if "train" in ds else ds[list(ds.keys())[0]]

    tasks: list[dict] = []
    for i, row in enumerate(split):
        prompt = str(_row_value(row, "Prompt", "prompt", "Intent", "intent", default="") or "")
        rego = str(_row_value(row, "Rego_intent", "Rego intent", "rego_policy", "rego_intent", default="") or "")
        if not prompt.strip() or not rego.strip():
            continue

        task_id = _row_value(row, "task_id", default=i)
        if task_ids and str(task_id) not in task_ids and str(i) not in task_ids:
            continue

        difficulty = _difficulty(_row_value(row, "Difficulty", "difficulty", default=0))
        if difficulties and difficulty not in difficulties:
            continue

        tasks.append({
            "id":               task_id,
            "prompt":           prompt,
            "resources":        _row_value(row, "Resource", "resource", default=""),
            "difficulty":       difficulty,
            "reference_output": _row_value(row, "Reference_output", "Reference output", "reference_output", default=""),
            "rego_intent":      rego,
            "dataset":          dataset_id,
            "suite":            _row_value(row, "suite", default="aws"),
            "opa_input_path":   _row_value(row, "opa_input_path", default=""),
        })

        if limit and len(tasks) >= limit:
            break

    return tasks
