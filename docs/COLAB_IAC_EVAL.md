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

Set model credentials in Colab Secrets:

- `CUSTOM_API_KEY`
- `CUSTOM_BASE_URL`
- `CUSTOM_MODEL_ID`

The notebook installs Terraform and OPA, installs Python dependencies, runs
`py_compile`, then runs:

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
