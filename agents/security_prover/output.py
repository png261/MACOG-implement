"""
Pydantic output model for the Security Prover agent.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PolicyViolation(BaseModel):
    rule: str = Field(description="Policy rule name, e.g. encrypt_at_rest")
    resource: str = Field(default="", description="Terraform resource address")
    severity: str = Field(description="critical | high | medium | low")
    message: str
    counterexample: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured CE: {type, rule, resource}",
    )
    fix: str = Field(default="", description="Exact HCL change needed")


class ProofTrace(BaseModel):
    rule: str
    status: str = Field(description="pass | fail")


class SecurityProverOutput(BaseModel):
    """
    Security audit result from the Security Prover agent.
    v_policy = 0 when any critical or high violation exists.
    """
    v_policy: int = Field(description="Policy validity: 0 = violations, 1 = compliant")
    passed: bool
    violations: list[PolicyViolation] = Field(default_factory=list)
    proof_traces: list[ProofTrace] = Field(default_factory=list)
