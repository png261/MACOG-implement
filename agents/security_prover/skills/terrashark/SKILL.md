---
name: terrashark
description: "Terraform/OpenTofu security, compliance, and policy guidance for the MACOG Security Prover agent. Use when generating Rego policies and evaluating secret, encryption, ingress, IAM, and compliance controls."
---

# TerraShark Security Prover Skill

Use this skill when generating or evaluating policy-as-code for the I-IR and HCL.

## Workflow

1. Map I-IR effects to concrete policy checks with pass/fail evidence.
2. Prioritize secret exposure, encryption, public ingress, IAM least privilege, and compliance gates.
3. Load only the local reference files relevant to the policy or evidence requirement.
4. Emit Rego that conftest can run, and provide Python-fallback-compatible findings when external policy tools are unavailable.
5. Include precise fixes and proof traces for every failed high-impact rule.

## Local References

- `references/secret-exposure.md`
- `references/compliance-gates.md`
- `references/security-and-governance.md`
- `references/do-dont-patterns.md`

## Output Focus

Return v_policy, pass/fail status, violations, counterexamples, fixes, and proof traces.
