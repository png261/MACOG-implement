from agents.provider_harmonizer.output import ProviderHarmonizerOutput

__all__ = ["provider_harmonizer_agent", "ProviderHarmonizerOutput"]


def __getattr__(name: str):
    if name != "provider_harmonizer_agent":
        raise AttributeError(name)
    from agents.provider_harmonizer.agent import provider_harmonizer_agent

    globals()[name] = provider_harmonizer_agent
    return provider_harmonizer_agent
