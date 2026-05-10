---
name: terrashark
description: "Terraform/OpenTofu HCL generation guidance for the MACOG Engineer agent. Use when compiling harmonized I-IR into stable, typed, secret-safe, reviewable HCL."
---

# TerraShark Engineer Skill

Use this skill when writing or repairing Terraform/OpenTofu HCL.

## Workflow

1. Choose stable resource addresses and iteration keys before writing HCL.
2. Use typed variables, bounded provider versions, clear outputs, and explicit provider wiring.
3. Prevent secret leakage through defaults, outputs, logs, and generated artifacts.
4. Load only the local reference files relevant to code generation, identity stability, module shape, or security hygiene.
5. For repair cycles, make targeted edits and preserve state addresses unless an explicit migration plan exists.

## Local References

- `references/coding-standards.md`
- `references/module-architecture.md`
- `references/identity-churn.md`
- `references/secret-exposure.md`
- `references/examples-good.md`
- `references/examples-bad.md`
- `references/examples-neutral.md`
- `references/do-dont-patterns.md`

## Output Focus

Write complete HCL to the requested session directory and return only structured metadata about files, resource counts, variables, outputs, and provider.
