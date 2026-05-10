# MACOG Paper Implementation Audit

Source paper: `2510.03902v1.pdf`, "Multi-Agent Code-Orchestrated Generation for Reliable Infrastructure-as-Code".

## Objective

Implement MACOG with Strands and verify that the implementation covers the paper's concrete system requirements:

- typed I-IR plan `P = <V,E,S>`
- eight role-specialized agents
- shared blackboard and deterministic FSM
- I-IR to Terraform compilation with schema/grammar constraints
- round-trip structural equivalence
- validator family `v_schema`, `v_policy`, `v_cost`, `v_deploy`
- counterexample-guided repair
- proof-carrying evidence bundle
- verified motif memory
- simple smoke gate before benchmark/evaluation runs

## Prompt-To-Artifact Checklist

| Paper requirement | Artifact/evidence | Status |
| --- | --- | --- |
| Architect agent produces typed P0 with resources, edges, specs, invariants | `agents/architect/*`, `agents/_base_models.py`, `ir.py` | Implemented |
| Provider Harmonizer resolves provider docs, versions, required fields | `agents/provider_harmonizer/*`, OpenTofu MCP tools | Implemented; live tool path depends on network/model endpoint |
| Engineer compiles I-IR to Terraform HCL | `agents/engineer/*`, `graph.py::EngineerNode` | Implemented |
| Noninteractive Strands artifact edits for automation | `agents/engineer/tools.py::safe_file_write`, `agents/engineer/tools.py::safe_editor` | Implemented; writes/edits are restricted to the active session directory |
| Constrained realization guard for HCL/provider contracts | `agents/reviewer/tools.py::_macog_contract_check` | Implemented as deterministic post-generation guard |
| Shared blackboard with artifacts, validators, repair state | `blackboard.py` | Implemented |
| Deterministic FSM: plan, harmonize, compile, review, prove, price, deploy, repair, done | `macog.py`, `graph.py` | Implemented |
| Reviewer static validation with Terraform and linter fallback | `agents/reviewer/tools.py` | Implemented |
| Security Prover with OPA/Rego and complementary scanners | `agents/security_prover/tools.py` | Implemented; Python scanner is always merged with conftest when conftest is available |
| Governance policy obligations: tags and residency | `run_governance_check`, `governance.rego` | Implemented |
| Checkov/Regula complementary scanner cross-check | `run_scanner_check` | Implemented; advisory by default, strict mode available |
| Cost and capacity planner with pinned catalog and Infracost | `agents/cost_capacity/tools.py` | Implemented; local catalog also reports unknown SKU/capacity notes |
| DevOps sandbox/deployability test | `agents/devops/tools.py` | Implemented with Terratest/MiniStack path and structural fallback when the local sandbox endpoint is unavailable |
| Round-trip parse/equivalence check `P* = parse(T)` | `roundtrip.py`, `macog.py::_enforce_roundtrip` | Implemented |
| Counterexample-to-edit mapping `CE -> Δ` and repair loop | `macog.py::_error_to_edit`, `_step_repair` | Implemented |
| Evidence bundle with traces, logs, hashes, toolchain, provider versions | `macog.py::_build_evidence_bundle`, `roundtrip.py` | Implemented |
| Memory Curator retrieves and stores verified motifs | `macog.py::_step_memory_retrieve`, `macog.py::_step_memory_store`, `agents/memory_curator/tools.py` | Implemented with pre-plan retrieval, post-success storage, and persistent `.macog_memory/motifs.json` catalog |
| Evaluation harness for IaC-Eval | `eval/*` | Implemented; requires configured model API and toolchain |
| Simple first smoke query | `scripts/macog-smoke.py` | Implemented |

## Verification Commands

Deterministic local fixture, no model/API dependency:

```bash
rtk python scripts/macog-smoke.py --local-fixture --budget 25 --region us-east-1
```

Expected summary:

- `state: done`
- `validators.v_schema: 1`
- `validators.v_policy: 1`
- `validators.v_cost: 5.0`
- `validators.v_deploy: 1`
- `validators.routing_score: 0.0`
- `roundtrip.passed: true`
- `policy.governance.v_policy: 1`
- `policy.scanner.v_policy: 1` with any generic Checkov/Regula findings reported as advisory `medium` severity unless strict mode is requested

Memory retrieval smoke, no model/API dependency:

```bash
MACOG_MEMORY_STORE=/private/tmp/macog_motifs_test.json rtk python -c 'import json; from agents.memory_curator.tools import store_memory_motif; from macog import MACOGOrchestrator; from blackboard import Blackboard; store_memory_motif(json.dumps({"id":"s3_enc","description":"encrypted s3 bucket","ir_fragment":{"resources":[{"kind":"aws_s3_bucket"}],"edges":[]},"hcl_fragment":"resource \"aws_s3_bucket\" \"bucket\" {}","constraints_satisfied":["budget","encryption_required"],"provider":"aws","version":"~> 5.0"})); bb=Blackboard(intent="Create encrypted S3 bucket", constraints={"budget":25,"encryption_required":True}); MACOGOrchestrator(max_iterations=0)._step_memory_retrieve(bb); print(json.dumps({"memory_count":len(bb.memory),"evidence_phase":bb.evidence[-1]["phase"],"first":bb.memory[0]["id"] if bb.memory else None}, sort_keys=True))'
```

Expected summary:

- `memory_count: 1`
- `evidence_phase: memory_retrieve`
- `first: s3_enc`

Live minimal Strands query:

```bash
rtk python scripts/macog-smoke.py \
  --backend custom \
  --intent 'Create one AWS S3 bucket with server-side encryption.' \
  --max-iterations 1 \
  --budget 25 \
  --region us-east-1 \
  --deploy-mode structural
```

If the configured custom model is inactive, override it without editing `.env`:

```bash
rtk python scripts/macog-smoke.py \
  --backend custom \
  --model-id '<active-model-id>' \
  --intent 'Create one AWS S3 bucket with server-side encryption.' \
  --max-iterations 1 \
  --deploy-mode structural
```

Use `--deploy-mode sandbox` when MiniStack/LocalStack is healthy and the live smoke should exercise Terratest apply/destroy instead of the deterministic structural deployability fallback.

Backend-specific live alternatives:

```bash
rtk python scripts/macog-smoke.py --max-iterations 1
rtk python scripts/macog-smoke.py --backend openrouter --max-iterations 1
rtk python scripts/macog-smoke.py --backend deepseek --max-iterations 1
rtk python scripts/macog-smoke.py --backend claude --max-iterations 1
```

When `MACOG_MODEL_BACKEND` is unset, `agents/_model.py` auto-selects `custom` if `CUSTOM_API_KEY` and `CUSTOM_BASE_URL` are configured; otherwise it falls back to `openrouter`.

## Current Live-Smoke Findings

- `--backend openrouter` fails fast in this workspace because `OPENROUTER_API_KEY` is not configured.
- `--backend deepseek` fails fast in this workspace because `DEEPSEEK_API_KEY` is not configured.
- The configured custom/Claude-compatible proxy reached Architect once, then failed during Provider Harmonizer with a retryable `502 Bad Gateway` from `llm.chiasegpu.vn`.
- A later custom live run failed with `APIConnectionError`.
- A subsequent custom live run reached the proxy but failed with `MODEL_INACTIVE` for configured model `gpt-5.5`.
- A custom live run with `--model-id claude-sonnet-4-6` surfaced an Architect structured-output validation issue (`availability: null`, `extra` not a dict); `agents/_base_models.py::SpecsOut` now coerces those values.
- The orchestrator and graph now retry transient `502/503/504`, timeout, rate limit, and connection errors.
- `scripts/macog-smoke.py` supports `--backend`, `--model-id`, and `--base-url` so live smoke can target a known-active provider.
- The simple custom-backend live smoke now passes in structural deploy mode:

```bash
rtk python scripts/macog-smoke.py \
  --backend custom \
  --intent 'Create one AWS S3 bucket with server-side encryption.' \
  --max-iterations 2 \
  --budget 25 \
  --region us-east-1 \
  --deploy-mode structural \
  --timeout 700
```

Observed summary:

- `state: done`
- `validators.v_schema: 1`
- `validators.v_policy: 1`
- `validators.v_cost: 0.0`
- `validators.v_deploy: 1`
- `validators.routing_score: 0.0`
- `final_score: 0.0`
- `roundtrip: PASS`
- memory curator stored 3 verified motifs
- The Terratest/MiniStack sandbox path was also exercised directly on a generated S3 session after changing generated tests to one full-stack apply and non-failing cleanup; `run_go_tests` returned `v_deploy: 1`.

## Residual Risks

- True grammar-constrained token masking is represented by deterministic contract checks plus Terraform validation, not a decoder-level token mask inside the LLM provider.
- Ephemeral real-cloud-account confirmation is not automated; the implemented DevOps path uses MiniStack/Terratest and structural fallback.
- Checkov/Regula are optional direct CLI integrations. Their broad default policy packs are advisory unless `run_scanner_check(strict=true)` is used.
- Full IaC-Eval scoring requires stable model API credentials and external tools (`terraform`, optional `tflint`, `conftest`, `infracost`, `go`, Docker/MiniStack).
