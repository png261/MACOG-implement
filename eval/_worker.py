"""
Per-model subprocess worker for iac-eval.

Invoked as:
    python -m eval._worker --tasks-file <path> --output-dir <dir> --max-iterations <n>

The parent process sets MACOG_MODEL_BACKEND / OPENROUTER_MODEL (etc.) in the
child environment *before* spawning this process, so model selection is baked
into the module-import-time agent initialisation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def run_task(task: dict, max_iter: int, codebert: bool = False) -> dict:
    # Late imports — env vars are already set before this module is loaded.
    from macog import MACOGOrchestrator
    from eval.metrics import compute_bleu, compute_codebert_score, run_rego_eval

    t0 = time.monotonic()
    try:
        result = MACOGOrchestrator(max_iterations=max_iter).run(
            intent=task["prompt"],
            constraints={"budget": 999999},
        )
    except Exception as exc:
        duration = time.monotonic() - t0
        return {
            "task_id":     task["id"],
            "difficulty":  task["difficulty"],
            "resources":   task["resources"],
            "macog_state": "error",
            "v_schema":    0,
            "v_policy":    0,
            "v_cost":      0.0,
            "v_deploy":    0,
            "macog_score": 99.0,
            "iterations":  0,
            "rego_pass":   None,
            "bleu":        0.0,
            "codebert":    None,
            "pass":        False,
            "duration_s":  round(duration, 2),
            "error":       str(exc),
        }

    duration = time.monotonic() - t0
    session_dir = result.get("session_dir", "")
    v = result["evidence"]["final_validators"]

    rego_result = run_rego_eval(task["rego_intent"], session_dir) if session_dir else {
        "passed": None, "violations": [], "error": "no session_dir"
    }

    bleu = compute_bleu(result.get("hcl", ""), task["reference_output"])
    codebert_score = compute_codebert_score(result.get("hcl", ""), task["reference_output"]) if codebert else None
    passed = v["v_schema"] == 1 and rego_result["passed"] is True and v["v_deploy"] == 1

    return {
        "task_id":     task["id"],
        "difficulty":  task["difficulty"],
        "resources":   task["resources"],
        "macog_state": result["state"],
        "v_schema":    v["v_schema"],
        "v_policy":    v["v_policy"],
        "v_cost":      v["v_cost"],
        "v_deploy":    v["v_deploy"],
        "macog_score": result["final_score"],
        "iterations":  result["iterations"],
        "rego_pass":   rego_result["passed"],
        "rego_query":  rego_result.get("query"),
        "rego_plan_source": rego_result.get("plan_source"),
        "bleu":        round(bleu, 4),
        "codebert":    round(codebert_score, 4) if codebert_score is not None else None,
        "pass":        passed,
        "duration_s":  round(duration, 2),
        "error":       rego_result.get("error"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="MACOG iac-eval worker")
    parser.add_argument("--tasks-file",     required=True)
    parser.add_argument("--output-dir",     required=True)
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--codebert",       action="store_true")
    args = parser.parse_args()

    tasks_file = Path(args.tasks_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tasks_file.open() as f:
        tasks: list[dict] = json.load(f)

    results_path = output_dir / "results.jsonl"
    completed_ids: set = set()
    if results_path.exists():
        with results_path.open() as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    completed_ids.add(rec["task_id"])
                except (json.JSONDecodeError, KeyError):
                    pass

    total = len(tasks)
    with results_path.open("a") as out:
        for idx, task in enumerate(tasks):
            if task["id"] in completed_ids:
                print(f"[worker] skip task {task['id']} (already done)", flush=True)
                continue

            print(f"[worker] task {task['id']} ({idx+1}/{total}) …", flush=True)
            record = run_task(task, args.max_iterations, codebert=args.codebert)
            out.write(json.dumps(record) + "\n")
            out.flush()

            status = "PASS" if record["pass"] else "FAIL"
            print(
                f"[worker] task {task['id']} {status} "
                f"bleu={record['bleu']:.3f} "
                f"rego={record['rego_pass']} "
                f"v_schema={record['v_schema']} "
                f"dur={record['duration_s']:.1f}s",
                flush=True,
            )

    print(f"[worker] done — {total} tasks written to {results_path}", flush=True)


if __name__ == "__main__":
    main()
