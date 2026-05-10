"""
Pydantic output model for the Architect agent.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents._base_models import EdgeOut, ResourceNodeOut, SpecsOut


class ArchitectOutput(BaseModel):
    """
    Typed I-IR plan P0 produced by the Architect agent.
    P = (V, E, S) — resource graph with specs and invariants.
    """
    resources: list[ResourceNodeOut] = Field(
        description="Resource nodes V; every cloud resource must have an entry",
    )
    edges: list[EdgeOut] = Field(
        default_factory=list,
        description="Dependency and connectivity edges E",
    )
    specs: SpecsOut = Field(
        default_factory=SpecsOut,
        description="Non-functional constraints S: budget, regions, SLO",
    )
    invariants: list[str] = Field(
        default_factory=list,
        description="Plain-text invariants I, e.g. 'residency=US', 'encryption=required'",
    )
