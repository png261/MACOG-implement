---
name: terrashark
description: "Reusable Terraform/OpenTofu motif quality guidance for the MACOG Memory Curator agent. Use when storing or retrieving verified I-IR/HCL/proof motifs."
---

# TerraShark Memory Curator Skill

Use this skill when selecting reusable motifs from verified MACOG runs.

## Workflow

1. Store only motifs that are self-contained, typed, provider-versioned, and validated by schema, policy, cost, and deploy checks.
2. Prefer proven reusable examples and context-aware tradeoff notes over environment-specific details.
3. Avoid preserving bad patterns such as unstable identity keys, plaintext secrets, floating versions, or broad outputs.
4. Load only the local reference files relevant to motif quality or examples.
5. Keep retrieved motifs small enough to seed planning or HCL generation without overwhelming the agent context.

## Local References

- `references/examples-good.md`
- `references/examples-bad.md`
- `references/examples-neutral.md`
- `references/module-architecture.md`
- `references/token-balance-rationale.md`

## Output Focus

Return extracted or retrieved motifs with descriptions, provider/version metadata, I-IR fragments, HCL fragments, and satisfied constraints.
