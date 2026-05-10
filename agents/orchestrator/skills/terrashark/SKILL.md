---
name: terrashark
description: "Pipeline-level Terraform/OpenTofu validation routing guidance for the MACOG Orchestrator agent. Use when deciding repair loops, validation gates, and done/failed outcomes."
---

# TerraShark Orchestrator Skill

Use this skill when coordinating the full MACOG pipeline.

## Workflow

1. Capture intent, constraints, runtime assumptions, and validation gates before routing.
2. Track failure modes across stages: CI drift, compliance gates, testing gaps, and operational quick fixes.
3. Load only the local reference files relevant to the current stage or failed validator.
4. Prefer repair loops that target the failing validator without destabilizing passed validators.
5. Finalize only when schema, policy, cost, and deploy evidence satisfy the routing score.

## Local References

- `references/ci-drift.md`
- `references/compliance-gates.md`
- `references/testing-matrix.md`
- `references/quick-ops.md`

## Output Focus

Return final state, plan, HCL, validator evidence, routing score, iterations, summary, and unsatisfied constraints.
