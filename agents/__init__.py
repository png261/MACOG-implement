"""MACOG agents package with lazy agent construction.

Agent instances require model credentials at import time. Keeping this package
lazy lets deterministic tool tests import `agents.<role>.tools` without
instantiating every Strands agent or requiring live model API keys.
"""

_AGENT_MODULES = {
    "architect_agent": "agents.architect",
    "provider_harmonizer_agent": "agents.provider_harmonizer",
    "engineer_agent": "agents.engineer",
    "reviewer_agent": "agents.reviewer",
    "security_prover_agent": "agents.security_prover",
    "cost_capacity_agent": "agents.cost_capacity",
    "devops_agent": "agents.devops",
    "memory_curator_agent": "agents.memory_curator",
}

__all__ = [
    "architect_agent",
    "provider_harmonizer_agent",
    "engineer_agent",
    "reviewer_agent",
    "security_prover_agent",
    "cost_capacity_agent",
    "devops_agent",
    "memory_curator_agent",
]


def __getattr__(name: str):
    if name not in _AGENT_MODULES:
        raise AttributeError(name)
    module_name = _AGENT_MODULES[name]
    module = __import__(module_name, fromlist=[name])
    value = getattr(module, name)
    globals()[name] = value
    return value
