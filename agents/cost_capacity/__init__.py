from agents.cost_capacity.output import CostCapacityOutput, CostLineItem, CostViolation, FinOpsViolation

__all__ = [
    "cost_capacity_agent",
    "CostCapacityOutput",
    "CostLineItem",
    "CostViolation",
    "FinOpsViolation",
]


def __getattr__(name: str):
    if name != "cost_capacity_agent":
        raise AttributeError(name)
    from agents.cost_capacity.agent import cost_capacity_agent

    globals()[name] = cost_capacity_agent
    return cost_capacity_agent
