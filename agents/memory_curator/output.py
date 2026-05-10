"""
Pydantic output model for the Memory Curator agent.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MemoryMotif(BaseModel):
    id: str = Field(description="UUID or descriptive slug")
    description: str = Field(description="What this motif represents, used for retrieval scoring")
    ir_fragment: dict[str, Any] = Field(
        default_factory=dict,
        description="Partial I-IR resource node (reusable sub-pattern)",
    )
    hcl_fragment: str = Field(default="", description="Corresponding HCL snippet")
    constraints_satisfied: list[str] = Field(
        default_factory=list,
        description="Constraint names this motif satisfies, e.g. ['encrypt_at_rest']",
    )
    provider: str = Field(default="", description="Cloud provider: aws | google | azurerm")
    version: str = Field(default="", description="Provider version this motif was verified against")


class MemoryCuratorOutput(BaseModel):
    """Memory Curator result: either a retrieval list or a storage confirmation."""
    action: str = Field(description="store | retrieve")
    motifs: list[MemoryMotif] = Field(default_factory=list)
