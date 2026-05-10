"""
Tools available to the MACOG Orchestrator agent.

run_macog_pipeline wraps the deterministic MACOGOrchestrator FSM so the
orchestrator agent can trigger the full plan→harmonize→compile→validate→repair
loop with a single tool call.  The import of MACOGOrchestrator is deferred
inside the function body to prevent a circular import (macog.py imports from
agents.*, while agents.orchestrator.tools would import macog).
"""
from __future__ import annotations

import json

from strands import tool


@tool
def run_macog_pipeline(
    intent: str,
    constraints_json: str = "{}",
    max_iterations: int = 5,
    session_id: str = "",
    session_storage: str = "",
) -> str:
    """
    Execute the full MACOG Algorithm 1 pipeline for the given infrastructure intent.

    Runs the deterministic FSM:
      plan → harmonize → compile → review → prove → price → deploy → repair* → done

    Args:
        intent: Natural language description of the desired infrastructure.
        constraints_json: JSON object with optional keys:
            budget (float), regions (list[str]),
            encryption_required (bool), availability (float).
        max_iterations: Maximum repair iterations (default 5).
        session_id: Optional stable Strands session id for this pipeline run.
        session_storage: Optional directory for Strands session files.

    Returns:
        JSON with keys: state, hcl, plan, evidence, iterations, final_score.
    """
    # Deferred import to avoid circular dependency:
    # macog.py imports from agents.*, so importing it at module level here
    # would create agents → orchestrator/tools → macog → agents.
    from macog import MACOGOrchestrator  # noqa: PLC0415

    constraints: dict = json.loads(constraints_json) if constraints_json else {}
    orchestrator = MACOGOrchestrator(
        max_iterations=max_iterations,
        session_id=session_id or None,
        session_storage=session_storage or None,
    )
    result = orchestrator.run(intent=intent, constraints=constraints)
    return json.dumps(result)
