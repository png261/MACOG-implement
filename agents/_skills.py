"""
Shared Strands skill plugin configuration.
"""
from pathlib import Path

from strands.vended_plugins.skills import AgentSkills


PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_SKILL_DIRS = {
    "architect": PROJECT_ROOT / "agents" / "architect" / "skills" / "terrashark",
    "provider_harmonizer": PROJECT_ROOT / "agents" / "provider_harmonizer" / "skills" / "terrashark",
    "engineer": PROJECT_ROOT / "agents" / "engineer" / "skills" / "terrashark",
    "reviewer": PROJECT_ROOT / "agents" / "reviewer" / "skills" / "terrashark",
    "security_prover": PROJECT_ROOT / "agents" / "security_prover" / "skills" / "terrashark",
    "cost_capacity": PROJECT_ROOT / "agents" / "cost_capacity" / "skills" / "terrashark",
    "devops": PROJECT_ROOT / "agents" / "devops" / "skills" / "terrashark",
    "memory_curator": PROJECT_ROOT / "agents" / "memory_curator" / "skills" / "terrashark",
    "orchestrator": PROJECT_ROOT / "agents" / "orchestrator" / "skills" / "terrashark",
}


def agent_terrashark_plugin(agent_name: str) -> AgentSkills:
    """Return a fresh TerraShark skills plugin instance for one MACOG agent."""
    try:
        skill_dir = AGENT_SKILL_DIRS[agent_name]
    except KeyError as exc:
        known = ", ".join(sorted(AGENT_SKILL_DIRS))
        raise ValueError(f"Unknown TerraShark agent skill '{agent_name}'. Known: {known}") from exc

    return AgentSkills(skills=[skill_dir])


__all__ = ["agent_terrashark_plugin"]
