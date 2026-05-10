---
name: terrashark
description: "Terraform/OpenTofu static review guidance for the MACOG Reviewer agent. Use when finding schema, identity, secret, contract, and common LLM-generated HCL issues."
---

# TerraShark Reviewer Skill

Use this skill when statically reviewing generated HCL.

## Workflow

1. Validate syntax/schema first, then inspect for LLM-specific Terraform mistakes.
2. Check address stability, variable contracts, provider pins, secret exposure, unsafe outputs, and known bad patterns.
3. Load only the local reference files relevant to the detected issue class.
4. Report concrete counterexamples and minimal patches; avoid broad rewrites when a targeted fix is enough.
5. Treat error-severity issues as pipeline blockers.

## Local References

- `references/coding-standards.md`
- `references/identity-churn.md`
- `references/secret-exposure.md`
- `references/quick-ops.md`
- `references/examples-good.md`
- `references/examples-bad.md`
- `references/do-dont-patterns.md`

## Output Focus

Return pass/fail, v_schema, diagnostics, issues, and exact HCL patch guidance for blocking problems.
