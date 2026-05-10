"""
Pydantic output model for the DevOps agent.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DeployError(BaseModel):
    type: str = Field(
        description=(
            "dependency_cycle | missing_arn | unsupported_instance | "
            "provider_error | missing_reference | init_error | plan_error"
        )
    )
    resource: str = Field(default="")
    message: str
    counterexample: dict[str, Any] = Field(default_factory=dict)
    fix: str = Field(default="")


class PlanSummary(BaseModel):
    add: int = 0
    change: int = 0
    destroy: int = 0


class TerratestResult(BaseModel):
    passed: bool = False
    tests_run: int = 0
    failed_tests: list[str] = Field(default_factory=list)
    logs: str = ""


class DevOpsOutput(BaseModel):
    """
    Sandbox deployment result from the DevOps agent.
    v_deploy = 1 when all Terratest assertions pass against ministack.
    """
    v_deploy: int = Field(description="Deploy validity: 0 = errors, 1 = success")
    phase: str = Field(description="terratest | structural")
    errors: list[DeployError] = Field(default_factory=list)
    plan_summary: PlanSummary = Field(default_factory=PlanSummary)
    logs: str = Field(default="")
    sandbox: str = Field(default="ministack")
    terratest: TerratestResult | None = None
