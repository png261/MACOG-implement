---
name: terrashark
description: "Provider-schema, registry, and versioning guidance for the MACOG Provider Harmonizer agent. Use when resolving provider details, resource docs, module trust, and schema-safe defaults."
---

# TerraShark Provider Harmonizer Skill

Use this skill when converting abstract I-IR resources into provider-aligned P1 resources.

## Workflow

1. Resolve provider namespaces, versions, and resource schemas from authoritative docs or tools.
2. Keep provider versions bounded and intentional.
3. Preserve Architect resource IDs, edges, invariants, and effects unless a schema fact makes a change necessary.
4. Load only the local reference files relevant to provider trust, schema shape, versioning, or external fact retrieval.
5. Document assumptions for placeholder values such as AMIs, SKUs, or region-specific defaults.

## Local References

- `references/coding-standards.md`
- `references/mcp-integration.md`
- `references/conditional/trusted-modules.md`

## Output Focus

Return a harmonized plan with concrete provider resource fields, pinned provider versions, and no ID churn.
