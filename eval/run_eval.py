"""
iac-eval orchestrator — spawns per-model workers and prints a comparison table.

Usage:
    python -m eval.run_eval \\
        --models deepseek-free,gemini-flash \\
        --config quick_test \\
        --limit 20 \\
        --difficulty 1,2,3 \\
        --max-iterations 3 \\
        --output eval/results/

In Docker (AWS_ENDPOINT_URL already set by compose):
    python -m eval.run_eval --models deepseek-free --limit 5

Local with MiniStack sidecar:
    python -m eval.run_eval --models deepseek-free --limit 5 --use-ministack
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from eval.dataset import load_tasks
from eval.models import resolve_model


# ── Comparison table printer ──────────────────────────────────────────────────

def _pct(n: int, d: int) -> str:
    return f"{100*n/d:.1f}%" if d else "n/a"


def _iac_eval_pct(records: list[dict]) -> str:
    """IaC-Eval% = 100 × Σ t_i / M   (uniform weights, t_i = record['pass'])"""
    M = len(records)
    if not M:
        return "n/a"
    return f"{100 * sum(1 for r in records if r.get('pass')) / M:.1f}%"


def _mean(records: list[dict], field: str) -> float | None:
    values = [r.get(field) for r in records if isinstance(r.get(field), (int, float))]
    if not values:
        return None
    return sum(values) / len(values)


def _summary_row(model: str, records: list[dict]) -> dict:
    n = len(records)
    n_schema = sum(1 for r in records if r.get("v_schema") == 1)
    n_rego = sum(1 for r in records if r.get("rego_pass") is True)
    n_deploy = sum(1 for r in records if r.get("v_deploy") == 1)
    n_pass = sum(1 for r in records if r.get("pass"))
    return {
        "model": model,
        "tasks": n,
        "iac_eval": n_pass / n if n else None,
        "v_schema": n_schema / n if n else None,
        "rego": n_rego / n if n else None,
        "v_deploy": n_deploy / n if n else None,
        "bleu": _mean(records, "bleu"),
        "codebert": _mean(records, "codebert"),
        "llm_judge": _mean(records, "llm_judge"),
        "iterations": _mean(records, "iterations"),
        "duration_s": _mean(records, "duration_s"),
    }


def _fmt_float(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _fmt_pct_value(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def print_comparison(all_results: dict[str, list[dict]]) -> None:
    models = list(all_results.keys())
    if not models:
        return

    header = (
        f"{'Model':<20} {'Tasks':>6} {'IaC-Eval%':>10} "
        f"{'v_schema%':>10} {'Rego%':>7} {'v_deploy%':>10} "
        f"{'BLEU':>7} {'CodeBERT':>9} {'LLM':>7} {'Iter':>7}"
    )
    sep = "─" * len(header)
    print(f"\n{sep}\n{header}\n{sep}")

    for model, records in all_results.items():
        row = _summary_row(model, records)
        if row["tasks"] == 0:
            continue
        print(
            f"{model:<20} {row['tasks']:>6} {_fmt_pct_value(row['iac_eval']):>10} "
            f"{_fmt_pct_value(row['v_schema']):>10} {_fmt_pct_value(row['rego']):>7} "
            f"{_fmt_pct_value(row['v_deploy']):>10} {_fmt_float(row['bleu']):>7} "
            f"{_fmt_float(row['codebert']):>9} {_fmt_float(row['llm_judge']):>7} "
            f"{_fmt_float(row['iterations'], 1):>7}"
        )

    # By-difficulty breakdown
    all_difficulties = sorted({r.get("difficulty", 0) for recs in all_results.values() for r in recs})
    if len(all_difficulties) > 1:
        diff_labels = "  ".join(f"D{d:<4}" for d in all_difficulties)
        print(f"\nBy difficulty (Pass%):\n{'Model':<20}  {diff_labels}")
        for model, records in all_results.items():
            row = f"{model:<20}"
            for d in all_difficulties:
                sub = [r for r in records if r.get("difficulty") == d]
                row += f"  {_pct(sum(1 for r in sub if r.get('pass')), len(sub)):<6}"
            print(row)
    print()


def save_comparison_csv(all_results: dict[str, list[dict]], output_dir: Path) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"comparison_{timestamp}.csv"

    rows = []
    for model, records in all_results.items():
        for r in records:
            rows.append({"model": model, **r})

    if not rows:
        return

    fieldnames = ["model"] + [k for k in rows[0] if k != "model"]
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"[eval] comparison saved to {csv_path}")


def save_paper_report(all_results: dict[str, list[dict]], output_dir: Path, metadata: dict) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary = {
        "metadata": metadata,
        "models": [_summary_row(model, records) for model, records in all_results.items()],
    }
    json_path = output_dir / f"paper_summary_{timestamp}.json"
    md_path = output_dir / f"paper_summary_{timestamp}.md"

    json_path.write_text(json.dumps(summary, indent=2))

    lines = [
        "# IaC-Eval Summary",
        "",
        f"- Dataset config: `{metadata.get('config')}`",
        f"- Dataset: `{metadata.get('dataset')}`",
        f"- Tasks: `{metadata.get('tasks')}`",
        f"- Difficulties: `{metadata.get('difficulties') or 'all'}`",
        f"- Max iterations: `{metadata.get('max_iterations')}`",
        f"- Deploy mode: `{metadata.get('deploy_mode')}`",
        f"- Task timeout: `{metadata.get('task_timeout_s')}s`",
        "",
        "| Model | Tasks | IaC-Eval | v_schema | Rego | v_deploy | BLEU | CodeBERTScore | LLM judge | Iter | Duration s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["models"]:
        lines.append(
            "| {model} | {tasks} | {iac} | {schema} | {rego} | {deploy} | {bleu} | {codebert} | {llm} | {iters} | {dur} |".format(
                model=row["model"],
                tasks=row["tasks"],
                iac=_fmt_pct_value(row["iac_eval"]),
                schema=_fmt_pct_value(row["v_schema"]),
                rego=_fmt_pct_value(row["rego"]),
                deploy=_fmt_pct_value(row["v_deploy"]),
                bleu=_fmt_float(row["bleu"]),
                codebert=_fmt_float(row["codebert"]),
                llm=_fmt_float(row["llm_judge"]),
                iters=_fmt_float(row["iterations"], 1),
                dur=_fmt_float(row["duration_s"], 1),
            )
        )
    lines.extend(
        [
            "",
            "Notes:",
            "- IaC-Eval is counted as pass only when MACOG schema validation, the IaC-Eval Rego rule, and deployment validation all pass.",
            "- CodeBERTScore is `n/a` unless `--codebert` is enabled and `bert-score` plus the CodeBERT model are available.",
            "- LLM judge is reserved for paper comparison tables and is `n/a` unless records provide `llm_judge` values.",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n")
    print(f"[eval] paper summary saved to {md_path}")
    print(f"[eval] paper summary JSON saved to {json_path}")


# ── Worker spawner ────────────────────────────────────────────────────────────

def run_model(
    model_name: str,
    tasks: list[dict],
    output_dir: Path,
    max_iterations: int,
    deploy_mode: str,
    task_timeout: int,
    codebert: bool,
) -> list[dict]:
    model_dir = output_dir / model_name
    model_dir.mkdir(parents=True, exist_ok=True)

    child_env = dict(os.environ)
    child_env["MACOG_EVAL_MODE"] = "1"
    child_env["MACOG_DEVOPS_MODE"] = deploy_mode
    if deploy_mode == "structural":
        child_env["MACOG_EVAL_FAST_SCHEMA"] = "1"
    child_env.update(resolve_model(model_name))

    print(f"\n[eval] === Model: {model_name} ===", flush=True)
    print(f"[eval] backend={child_env.get('MACOG_MODEL_BACKEND')} "
          f"model={child_env.get('OPENROUTER_MODEL', '(direct)')}", flush=True)

    results_path = model_dir / "results.jsonl"

    def append_timeout_record(task: dict, error: str) -> None:
        record = {
            "task_id": task["id"],
            "difficulty": task["difficulty"],
            "resources": task["resources"],
            "macog_state": "timeout",
            "v_schema": 0,
            "v_policy": 0,
            "v_cost": 0.0,
            "v_deploy": 0,
            "macog_score": 99.0,
            "iterations": 0,
            "rego_pass": None,
            "rego_query": None,
            "rego_plan_source": None,
            "bleu": 0.0,
            "codebert": None,
            "llm_judge": None,
            "pass": False,
            "duration_s": task_timeout,
            "error": error,
        }
        with results_path.open("a") as out:
            out.write(json.dumps(record) + "\n")

    def has_record(task_id: object) -> bool:
        if not results_path.exists():
            return False
        with results_path.open() as f:
            for line in f:
                try:
                    if json.loads(line).get("task_id") == task_id:
                        return True
                except json.JSONDecodeError:
                    pass
        return False

    for task in tasks:
        if has_record(task["id"]):
            print(f"[eval] skip task {task['id']} for {model_name} (already recorded)", flush=True)
            continue

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, dir=model_dir
        ) as tf:
            json.dump([task], tf)
            tasks_file = tf.name

        cmd = [
            sys.executable, "-m", "eval._worker",
            "--tasks-file",     tasks_file,
            "--output-dir",     str(model_dir),
            "--max-iterations", str(max_iterations),
        ]
        if codebert:
            cmd.append("--codebert")
        try:
            proc = subprocess.run(cmd, env=child_env, timeout=task_timeout)
            if proc.returncode != 0 and not has_record(task["id"]):
                append_timeout_record(task, f"worker exited with code {proc.returncode}")
        except subprocess.TimeoutExpired:
            if not has_record(task["id"]):
                append_timeout_record(task, f"task exceeded {task_timeout}s timeout")
            print(f"[eval] WARNING: task {task['id']} for {model_name} timed out", flush=True)
        finally:
            try:
                os.unlink(tasks_file)
            except FileNotFoundError:
                pass

    results: list[dict] = []
    if results_path.exists():
        with results_path.open() as f:
            for line in f:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return results


# ── MiniStack helper ──────────────────────────────────────────────────────────

def maybe_start_ministack(use_ministack: bool) -> None:
    if os.environ.get("AWS_ENDPOINT_URL"):
        print(f"[eval] AWS_ENDPOINT_URL={os.environ['AWS_ENDPOINT_URL']} — skipping MiniStack startup")
        return
    if not use_ministack:
        return
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from ministack import MiniStack  # type: ignore[import]
        ms = MiniStack()
        endpoint = ms.start()
        os.environ["AWS_ENDPOINT_URL"] = endpoint
        print(f"[eval] MiniStack started at {endpoint}")
    except Exception as exc:
        print(f"[eval] WARNING: could not start MiniStack: {exc}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run MACOG across multiple models on iac-eval and print a comparison table.",
    )
    parser.add_argument(
        "--dataset", default="iac-eval-v1",
        help='Dataset alias or HF path: "iac-eval-v1" (default) or "iac-eval-v2"',
    )
    parser.add_argument(
        "--models", default="deepseek-free",
        help="Comma-separated model names (see eval/models.py). Default: deepseek-free",
    )
    parser.add_argument(
        "--config", default="quick_test",
        help='HuggingFace dataset config. v1 supports "quick_test" or "default"; v2 supports "default". Default: quick_test',
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max tasks per model (useful for smoke tests)",
    )
    parser.add_argument(
        "--difficulty", default=None,
        help="Comma-separated difficulty levels to include, e.g. 1,2,3",
    )
    parser.add_argument(
        "--task-id", default=None,
        help="Comma-separated exact dataset task IDs or row indexes to include",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=3,
        help="MACOG repair-loop budget K. Default: 3",
    )
    parser.add_argument(
        "--deploy-mode", choices=["structural", "sandbox"], default="structural",
        help="Deployment validator mode for MACOG. Default: structural",
    )
    parser.add_argument(
        "--task-timeout", type=int, default=900,
        help="Hard timeout in seconds for each task/model run. Default: 900",
    )
    parser.add_argument(
        "--codebert", action="store_true",
        help="Compute optional CodeBERTScore if bert-score/model dependencies are available",
    )
    parser.add_argument(
        "--output", default="eval/results",
        help="Output directory for per-model JSONL and comparison CSV",
    )
    parser.add_argument(
        "--use-ministack", action="store_true",
        help="Start MiniStack locally if AWS_ENDPOINT_URL is not already set",
    )
    parser.add_argument(
        "--iac-eval-dir", default=os.environ.get("IAC_EVAL_DIR", ""),
        help="Path to local iac-eval clone with pre-cached HF dataset (default: $IAC_EVAL_DIR)",
    )
    args = parser.parse_args()

    model_names = [m.strip() for m in args.models.split(",") if m.strip()]
    difficulties = (
        [int(d.strip()) for d in args.difficulty.split(",") if d.strip()]
        if args.difficulty else None
    )
    task_ids = [t.strip() for t in args.task_id.split(",") if t.strip()] if args.task_id else None
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    maybe_start_ministack(args.use_ministack)

    print(f"[eval] Loading {args.dataset} '{args.config}' tasks…", flush=True)
    tasks = load_tasks(
        dataset=args.dataset,
        config=args.config,
        iac_eval_dir=args.iac_eval_dir or None,
        limit=args.limit,
        difficulties=difficulties,
        task_ids=task_ids,
    )
    print(f"[eval] {len(tasks)} tasks loaded", flush=True)

    if not tasks:
        print("[eval] No tasks — exiting.")
        return

    all_results: dict[str, list[dict]] = {}
    for model_name in model_names:
        all_results[model_name] = run_model(
            model_name=model_name,
            tasks=tasks,
            output_dir=output_dir,
            max_iterations=args.max_iterations,
            deploy_mode=args.deploy_mode,
            task_timeout=args.task_timeout,
            codebert=args.codebert,
        )

    print_comparison(all_results)
    save_comparison_csv(all_results, output_dir)
    save_paper_report(
        all_results,
        output_dir,
        {
            "config": args.config,
            "dataset": args.dataset,
            "tasks": len(tasks),
            "difficulties": difficulties,
            "task_ids": task_ids,
            "models": model_names,
            "max_iterations": args.max_iterations,
            "deploy_mode": args.deploy_mode,
            "task_timeout_s": args.task_timeout,
            "codebert": args.codebert,
            "iac_eval_dir": args.iac_eval_dir or None,
        },
    )


if __name__ == "__main__":
    main()
