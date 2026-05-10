"""
Shared I-IR sub-models reused by Architect and Provider Harmonizer output models.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ResourceNodeOut(BaseModel):
    id: str = Field(description="Unique snake_case identifier for the resource")
    kind: str = Field(description="Exact Terraform resource type, e.g. aws_vpc")
    provider: str = Field(description="Cloud provider: aws | google | azurerm")
    region: str = Field(description="Provider region string, e.g. us-east-1")
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific field values",
    )
    effects: list[str] = Field(
        default_factory=list,
        description=(
            "Security/compliance obligations: "
            "encrypt_at_rest | least_privilege | restricted_ingress | "
            "tag_required | residency_eu | encrypt_in_transit"
        ),
    )

    @field_validator("effects", mode="before")
    @classmethod
    def coerce_effects(cls, v: object) -> list:
        return v if v is not None else []


class EdgeOut(BaseModel):
    type: str = Field(description="Edge kind: depends | connects")
    source: str = Field(description="Source resource id")
    target: str = Field(description="Target resource id")
    proto: str | None = Field(default=None, description="Protocol for connects edges, e.g. tcp")
    port: int | None = Field(default=None, description="Port for connects edges")


class SpecsOut(BaseModel):
    budget: float | None = Field(default=None, description="Monthly USD ceiling; null = unlimited")
    regions: list[str] = Field(default_factory=list)
    encryption_required: bool = False
    availability: float = Field(default=0.0, description="SLO percentage, e.g. 99.9")
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("regions", mode="before")
    @classmethod
    def coerce_regions(cls, v: object) -> list:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("availability", mode="before")
    @classmethod
    def coerce_availability(cls, v: object) -> float:
        if v is None or v == "":
            return 0.0
        return v

    @field_validator("extra", mode="before")
    @classmethod
    def coerce_extra(cls, v: object) -> dict:
        return v if isinstance(v, dict) else {}
