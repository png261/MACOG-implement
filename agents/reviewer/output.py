"""
Pydantic output model for the Reviewer agent.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewIssue(BaseModel):
    severity: str = Field(description="error | warning")
    resource: str = Field(description="resource_type.resource_name or block identifier")
    message: str = Field(description="Concise issue description")
    patch: str = Field(default="", description="Exact HCL line(s) to add or change")


class ReviewerOutput(BaseModel):
    """
    Static review result from the Reviewer agent.
    v_schema = 1 when no error-severity issues exist.
    """
    passed: bool
    v_schema: int = Field(description="Schema validity: 0 = invalid, 1 = valid")
    issues: list[ReviewIssue] = Field(default_factory=list)
    diagnostics: str = Field(default="", description="One-line summary")
