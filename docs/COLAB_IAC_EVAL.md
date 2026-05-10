# Colab IaC-Eval Runner

Use this when the full IaC-Eval benchmark is too slow or dependency-heavy for a
local run.

## Colab MCP Setup

`googlecolab/colab-mcp` bridges a local MCP-capable agent to a Colab browser
session. Its README shows this MCP config:

```json
{
  "mcpServers": {
    "colab-mcp": {
      "command": "uvx",
      "args": ["git+https://github.com/googlecolab/colab-mcp"],
      "timeout": 30000
    }
  }
}
```

The Colab MCP server requires:

- `uv` installed locally
- an MCP client with `notifications/tools/list_changed` support
- a local browser Colab session

This Codex session does not currently expose a Colab MCP tool, so the repo now
contains a notebook that can be opened or driven through Colab MCP once the MCP
server is configured.

## Notebook

Open:

```text
notebooks/iac_eval_colab_runner.ipynb
```

Set these variables in the first code cell:

- `REPO_URL`: Git URL containing the current MACOG evaluation changes
- `BRANCH`: branch to clone in Colab
- `MODEL`: usually `custom`
- `LOCAL_RUNTIME`: set to `True` only after connecting Colab to a local Jupyter
  runtime on your machine
- `EXTERNAL_AWS_ENDPOINT_URL`: usually `http://127.0.0.1:4566` when MiniStack
  is running on your machine

Set model credentials in Colab Secrets:

- `CUSTOM_API_KEY`
- `CUSTOM_BASE_URL`
- `CUSTOM_MODEL_ID`

The notebook installs Terraform and OPA in hosted Colab mode, installs Python
dependencies, writes a runtime `.env`, runs `py_compile`, then runs:

## Local Runtime With Local MiniStack

Use this when Colab/Kaggle cannot run Docker, but your machine can. Colab keeps
the notebook UI in the browser, while code executes on your local Jupyter
runtime. Because the kernel is local, `http://127.0.0.1:4566` points to your
machine, not to a hosted Colab VM.

1. Start MiniStack locally and keep it running on port `4566`.

   ```bash
   curl http://127.0.0.1:4566/_ministack/health
   ```

2. Start a local Jupyter runtime that trusts the Colab frontend.

   ```bash
   jupyter notebook \
     --NotebookApp.allow_origin='https://colab.research.google.com' \
     --port=8888 \
     --NotebookApp.port_retries=0 \
     --NotebookApp.allow_credentials=True
   ```

3. In Colab, click `Connect` -> `Connect to local runtime...`, then paste the
   local Jupyter URL containing the token.

4. In the first notebook cell set:

   ```python
   LOCAL_RUNTIME = True
   EXTERNAL_AWS_ENDPOINT_URL = "http://127.0.0.1:4566"
   ```

5. Ensure these commands work in the same local environment that runs Jupyter:

   ```bash
   terraform version
   opa version
   git --version
   python --version
   ```

In local-runtime mode, the notebook skips `apt-get`, sets
`AWS_ENDPOINT_URL=http://127.0.0.1:4566`, switches `MACOG_DEVOPS_MODE` to
`sandbox`, checks the MiniStack health endpoint during preflight, and uses the
already-running MiniStack service. It does not pass `--use-ministack` because
the notebook should not start a second container.

Google's Colab local runtime documentation describes the same flow: start a
local runtime, then use `Connect to local runtime...` in Colab. See:
https://research.google.com/colaboratory/local-runtimes.html

## Smoke Commands

Hosted Colab mode uses structural deploy validation. Local-runtime mode uses
the same commands but with `--deploy-mode sandbox` through the notebook's
`DEPLOY_MODE` variable.

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
  --output eval/results/colab_iac_eval_v1_smoke
```

and:

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
  --output eval/results/colab_iac_eval_v2_smoke
```

After both smoke runs pass, uncomment the full-run cells for v1 and v2.

## Output

Each Colab run writes the same artifacts as the local runner:

- `results.jsonl`
- `comparison_<timestamp>.csv`
- `paper_summary_<timestamp>.json`
- `paper_summary_<timestamp>.md`

Download the `eval/results` folder from Colab after a full run.
