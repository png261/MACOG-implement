from agents.architect.output import ArchitectOutput

__all__ = ["architect_agent", "ArchitectOutput"]


def __getattr__(name: str):
    if name != "architect_agent":
        raise AttributeError(name)
    from agents.architect.agent import architect_agent

    globals()[name] = architect_agent
    return architect_agent
