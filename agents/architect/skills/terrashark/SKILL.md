---
name: terrashark
description: "Architecture-focused Terraform/OpenTofu planning guidance for the MACOG Architect agent. Use when turning intent and constraints into I-IR resources, boundaries, security effects, invariants, and high-level stack shape."
---

# TerraShark Architect Skill

Use this skill when producing the MACOG P0 architecture plan.

## Workflow

1. Capture provider, region, environment criticality, availability, residency, and state/backend assumptions when known.
2. Identify architecture risks before emitting I-IR: blast radius, state boundaries, module boundaries, compliance-sensitive effects, and security/governance obligations.
3. Load only the local reference files relevant to the detected risk.
4. Prefer explicit resource boundaries, stable identifiers, clear edges, and security effects that downstream agents can prove.
5. Keep provider implementation details and registry/module lookup out of P0 unless the user explicitly asks for them.

## Local References

- `references/structure-and-state.md`
- `references/blast-radius.md`
- `references/module-architecture.md`
- `references/compliance-gates.md`
- `references/security-and-governance.md`

## Output Focus

Return a complete I-IR plan with explicit assumptions, all implied resources, lifecycle boundaries, invariants, effects, and provider/region choices.
