# IaC-Eval Evaluation

This repo includes a MACOG runner for the AutoIaC IaC-Eval datasets:

- v1 dataset: `autoiac-project/iac-eval`
- v2 dataset: `iac-eval-v2/iac-eval-v2`
- v1 configs: `quick_test` and `default`
- v2 config: `default`
- v1 split: `test`
- v2 split: `train`
- Core fields: v1 uses `Prompt`, `Rego intent`, `Reference output`, `Difficulty`, `Resource`; v2 uses `prompt`, `rego_policy`, `reference_output`, `difficulty`, `resource`

The paper-style pass metric is reported as `IaC-Eval`: a task passes only when
MACOG schema validation, the IaC-Eval Rego policy, and deployment validation all
pass.

## Smoke Test

Run one simple task first:

```bash
rtk python -m eval.run_eval \
  --dataset iac-eval-v1 \
  --models custom \
  --config default \
  --task-id 451 \
  --limit 1 \
  --max-iterations 2 \
  --deploy-mode structural \
  --task-timeout 900 \
  --output eval/results/iac_eval_smoke
```

`custom` uses the current `MACOG_MODEL_BACKEND=custom` configuration from the
environment or `.env`.

IaC-Eval Rego scoring requires `opa` on `PATH` or `OPA_BIN=/path/to/opa`. For
the local smoke, `/private/tmp/opa` is also detected when present.

## Full Structural Benchmark

```bash
rtk python -m eval.run_eval \
  --dataset iac-eval-v1 \
  --models custom \
  --config default \
  --max-iterations 3 \
  --deploy-mode structural \
  --task-timeout 1200 \
  --output eval/results/iac_eval_full
```

This is the practical paper-style benchmark for repeated local runs. It uses
Terraform plan JSON plus OPA Rego validation, but keeps deployment validation in
structural mode so the run does not create real AWS resources.

## IaC-Eval v2

Run v2 after the v1 smoke is green:

```bash
rtk python -m eval.run_eval \
  --dataset iac-eval-v2 \
  --config default \
  --models custom \
  --limit 1 \
  --max-iterations 2 \
  --deploy-mode structural \
  --task-timeout 900 \
  --output eval/results/iac_eval_v2_smoke
```

Then run the full v2 benchmark:

```bash
rtk python -m eval.run_eval \
  --dataset iac-eval-v2 \
  --config default \
  --models custom \
  --max-iterations 3 \
  --deploy-mode structural \
  --task-timeout 1200 \
  --output eval/results/iac_eval_v2_full
```

## Sandbox Deployment Benchmark

```bash
rtk python -m eval.run_eval \
  --dataset iac-eval-v1 \
  --models custom \
  --config default \
  --max-iterations 3 \
  --deploy-mode sandbox \
  --use-ministack \
  --task-timeout 1800 \
  --output eval/results/iac_eval_sandbox
```

Use this when a MiniStack or compatible AWS endpoint is available. It is slower
and closer to an executable deployment check.

## Outputs

Each run writes:

- `eval/results/<run>/<model>/results.jsonl`: per-task records
- `comparison_<timestamp>.csv`: flat task-level table
- `paper_summary_<timestamp>.json`: model-level summary
- `paper_summary_<timestamp>.md`: paper-style summary table

The table includes `IaC-Eval`, `v_schema`, `Rego`, `v_deploy`, `BLEU`,
`CodeBERTScore`, `LLM judge`, average iterations, and average duration.

When `terraform plan` cannot produce JSON because provider plugins or required
input variables are unavailable, the evaluator falls back to a synthetic
configuration JSON parsed from generated HCL. The per-task JSONL records this in
`rego_plan_source`.

`CodeBERTScore` is optional:

```bash
rtk python -m eval.run_eval ... --codebert
```

It requires `bert-score` and access to the `microsoft/codebert-base` model.
Without those dependencies, the value is reported as `n/a`.
