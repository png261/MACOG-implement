from agents.reviewer.output import ReviewerOutput, ReviewIssue

__all__ = ["reviewer_agent", "ReviewerOutput", "ReviewIssue"]


def __getattr__(name: str):
    if name != "reviewer_agent":
        raise AttributeError(name)
    from agents.reviewer.agent import reviewer_agent

    globals()[name] = reviewer_agent
    return reviewer_agent
