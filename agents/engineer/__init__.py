from agents.engineer.output import EngineerOutput

__all__ = ["engineer_agent", "EngineerOutput"]


def __getattr__(name: str):
    if name != "engineer_agent":
        raise AttributeError(name)
    from agents.engineer.agent import engineer_agent

    globals()[name] = engineer_agent
    return engineer_agent
