"""
Pydantic output model for the Provider Harmonizer agent.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents._base_models import EdgeOut, ResourceNodeOut, SpecsOut


class ProviderHarmonizerOutput(BaseModel):
    """
    Harmonized I-IR plan P1 with all provider-specific fields expanded,
    versions resolved, and region names normalised.
    """
    resources: list[ResourceNodeOut] = Field(
        description="Provider-instantiated resource nodes with all required fields filled",
    )
    edges: list[EdgeOut] = Field(default_factory=list)
    specs: SpecsOut = Field(default_factory=SpecsOut)
    invariants: list[str] = Field(default_factory=list)
    provider_versions: dict[str, str] = Field(
        default_factory=dict,
        description="Pinned provider versions used, e.g. {'aws': '~> 5.0'}",
    )
