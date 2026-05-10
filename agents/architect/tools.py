"""
Tools available to the Architect agent.
"""
import json
import os

from strands import tool, ToolContext
from strands_tools import handoff_to_user

from agents.memory_curator.tools import retrieve_memory_motifs


@tool(context=True)
def write_ir_plan(plan_json: str, tool_context: ToolContext) -> str:
    """Write the I-IR plan P0 to {session_dir}/ir/plan_p0.json."""
    session_dir = tool_context.agent.state.get("session_dir") or ""
    ir_dir = os.path.join(session_dir, "ir")
    os.makedirs(ir_dir, exist_ok=True)
    path = os.path.join(ir_dir, "plan_p0.json")
    with open(path, "w") as f:
        f.write(plan_json)
    return json.dumps({"written": True, "path": path})


__all__ = [
    "handoff_to_user",
    "retrieve_memory_motifs",
    "write_ir_plan",
]
