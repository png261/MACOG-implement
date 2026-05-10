---
name: terrashark
description: "Infracost-oriented Terraform/OpenTofu guidance for the MACOG Cost and Capacity Planner agent."
---

# TerraShark Cost and Capacity Skill

Use this skill when estimating cost and identifying cost/capacity risk.

## Workflow

1. Inspect the generated HCL and run cost estimation from the shared session directory.
2. Compare total monthly cost with budget constraints and surface FinOps policy issues.
3. Use Infracost delivery guidance for artifact shape, auditability, and cost visibility.
4. Prefer concrete line items, budget deltas, and capacity notes over generic cost advice.
5. Do not expand into test, deploy, or architecture blast-radius advice unless it directly affects cost output.

## Local References

- `references/ci-delivery-patterns.md`

## Output Focus

Return v_cost, total monthly cost, budget status, line items, FinOps violations, and capacity notes.
