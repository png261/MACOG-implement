"""
Pydantic output model for the Engineer agent.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class EngineerOutput(BaseModel):
    """
    Metadata from the Engineer agent after writing HCL to the shared session directory.
    The actual HCL lives on disk at <session_dir>/main.tf — not in this output.
    """
    files_written: list[str] = Field(
        default_factory=list,
        description="Paths of files written to the session directory, e.g. ['<session_dir>/main.tf']",
    )
    provider: str = Field(default="aws", description="Primary cloud provider targeted")
    resource_count: int = Field(default=0, description="Number of resource blocks emitted")
    variable_count: int = Field(default=0, description="Number of variable blocks emitted")
    output_count: int = Field(default=0, description="Number of output blocks emitted")

    @field_validator("files_written", mode="before")
    @classmethod
    def coerce_files_written(cls, v: object) -> list:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v
