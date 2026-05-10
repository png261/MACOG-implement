"""
Pydantic output model for the Cost & Capacity Planner agent.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class CostLineItem(BaseModel):
    resource: str = Field(description="Terraform resource address, e.g. aws_instance.web")
    monthly_cost: float = Field(description="Estimated monthly cost in USD")


class FinOpsViolation(BaseModel):
    policy: str = Field(description="Infracost FinOps policy name")
    resource: str = Field(description="Terraform resource address")
    description: str = Field(description="Issue description and recommended fix")
    monthly_savings: str = Field(default="0", description="Potential savings in USD")


class CostViolation(BaseModel):
    type: str = Field(description="budget_exceeded | sku_unavailable | quota_exceeded")
    resource: str = Field(default="")
    message: str
    counterexample: dict[str, Any] = Field(default_factory=dict)
    fix: str = Field(default="")

    @field_validator("counterexample", mode="before")
    @classmethod
    def coerce_counterexample(cls, v: object) -> dict:
        if isinstance(v, dict):
            return v
        if v is None or v == "":
            return {}
        return {"value": v}


class CostCapacityOutput(BaseModel):
    """
    Cost and capacity result from the Cost & Capacity Planner agent.
    v_cost is the total monthly USD estimate.
    """
    v_cost: float = Field(description="Total estimated monthly cost in USD")
    within_budget: bool
    total_monthly_cost: float
    line_items: list[CostLineItem] = Field(default_factory=list)
    finops_violations: list[FinOpsViolation] = Field(
        default_factory=list,
        description="FinOps policy violations surfaced by infracost",
    )
    violations: list[CostViolation] = Field(default_factory=list)
    capacity_notes: str = Field(default="", description="Region/quota concerns")
