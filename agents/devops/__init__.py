from agents.devops.output import DevOpsOutput, DeployError, PlanSummary, TerratestResult

__all__ = ["devops_agent", "DevOpsOutput", "DeployError", "PlanSummary", "TerratestResult"]


def __getattr__(name: str):
    if name != "devops_agent":
        raise AttributeError(name)
    from agents.devops.agent import devops_agent

    globals()[name] = devops_agent
    return devops_agent
