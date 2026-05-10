# Kaggle IaC-Eval Runner

Use this notebook when running the MACOG IaC-Eval benchmark on Kaggle.

## Kaggle Setup

In the Kaggle notebook settings:

- Enable Internet.
- Use a CPU session unless you enable optional CodeBERT scoring.
- Add Kaggle Secrets for the `custom` backend:
  - `CUSTOM_API_KEY`
  - `CUSTOM_BASE_URL`
  - `CUSTOM_MODEL_ID`

## Notebook

Open or upload:

```text
notebooks/iac_eval_kaggle_runner.ipynb
```

The notebook clones:

```text
https://github.com/png261/MACOG-implement.git
```

It installs Terraform and OPA into `/kaggle/working/bin`, installs Python
dependencies from `requirements.txt`, installs the explicit eval packages
(`datasets`, `sacrebleu`, `pandas`, `python-dotenv`), writes a runtime `.env`
inside the cloned repo from Kaggle Secrets, runs a preflight check first, then
runs the v1 smoke task:

```bash
python -m eval.run_eval \
  --dataset iac-eval-v1 \
  --models custom \
  --config default \
  --task-id 451 \
  --limit 1 \
  --max-iterations 1 \
  --deploy-mode structural \
  --task-timeout 900 \
  --output eval/results/kaggle_iac_eval_v1_smoke
```

After v1 passes, run the v2 smoke task:

```bash
python -m eval.run_eval \
  --dataset iac-eval-v2 \
  --models custom \
  --config default \
  --task-id aws/task-057 \
  --limit 1 \
  --max-iterations 1 \
  --deploy-mode structural \
  --task-timeout 900 \
  --output eval/results/kaggle_iac_eval_v2_smoke
```

Full-run cells are included but commented out. Run them only after both smoke
tests pass.

Set `INSTALL_CODEBERT_DEPS = True` in the first cell only if you plan to run
`eval.run_eval --codebert`; it installs `bert-score`, `torch`, and
`transformers`, which is slower and heavier than the smoke test path.

## Outputs

Kaggle writes benchmark artifacts under:

```text
/kaggle/working/strands-agent/eval/results
```

Expected files include:

- `results.jsonl`
- `comparison_<timestamp>.csv`
- `paper_summary_<timestamp>.json`
- `paper_summary_<timestamp>.md`
