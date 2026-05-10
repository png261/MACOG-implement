"""
Pydantic output model for the MACOG Orchestrator agent.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ValidatorSummary(BaseModel):
    v_schema: int = Field(description="1 = HCL valid, 0 = schema errors")
    v_policy: int = Field(description="1 = policies satisfied, 0 = violations")
    v_cost: float = Field(description="Total estimated monthly USD")
    v_deploy: int = Field(description="1 = terraform plan succeeded, 0 = errors")
    routing_score: float = Field(description="J(T,C) — 0.0 means fully feasible")


class OrchestratorOutput(BaseModel):
    """
    Final output of the MACOG Orchestration pipeline.
    Carries the verified (P, T, Π) tuple and execution metadata.
    """
    state: str = Field(description="done | failed")
    hcl: str = Field(default="", description="Final generated HCL Terraform code")
    plan: dict[str, Any] = Field(
        default_factory=dict,
        description="Final harmonized I-IR plan P1",
    )
    validators: ValidatorSummary = Field(
        default_factory=lambda: ValidatorSummary(
            v_schema=0, v_policy=0, v_cost=0.0, v_deploy=0, routing_score=1.0
        ),
        description="Final validator scores and routing score J(T,C)",
    )
    iterations: int = Field(default=0, description="Number of repair iterations used")
    summary: str = Field(
        default="",
        description="Human-readable summary of the pipeline result",
    )
    unsatisfied_core: list[str] = Field(
        default_factory=list,
        description="Unsatisfied constraint categories when state=failed",
    )
