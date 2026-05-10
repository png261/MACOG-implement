---
name: terrashark
description: "Terraform/OpenTofu Terratest, CI drift, and deployability guidance for the MACOG DevOps agent."
---

# TerraShark DevOps Skill

Use this skill when generating deployability tests and running Terratest/MiniStack validation.

## Workflow

1. Build tests around the I-IR resource kinds and generated HCL interfaces.
2. Keep Terraform apply tests isolated, reversible, and environment-aware.
3. Check test tier, CI/runtime drift, plan/apply command flow, and reproducible failure diagnostics.
4. Load only the local reference files relevant to testing, delivery, drift, or common command failures.
5. Prefer reproducible command sequences and concise failure diagnostics.

## Local References

- `references/testing-matrix.md`
- `references/ci-delivery-patterns.md`
- `references/ci-drift.md`
- `references/quick-ops.md`

## Output Focus

Return v_deploy, phase, sandbox, Terratest status, failed tests, logs, and actionable fixes.
