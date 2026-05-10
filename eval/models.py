"""
Model registry for the iac-eval harness.

Each entry maps a short model name to the env vars that configure MACOG
to use that model backend.  Unknown names are treated as raw OPENROUTER_MODEL IDs.
"""

MODEL_REGISTRY: dict[str, dict[str, str]] = {
    "deepseek-free": {
        "MACOG_MODEL_BACKEND": "openrouter",
        "OPENROUTER_MODEL":    "deepseek/deepseek-chat-v3-0324:free",
    },
    "gemini-flash": {
        "MACOG_MODEL_BACKEND": "openrouter",
        "OPENROUTER_MODEL":    "google/gemini-2.5-flash",
    },
    "claude-haiku": {
        "MACOG_MODEL_BACKEND": "openrouter",
        "OPENROUTER_MODEL":    "anthropic/claude-3-5-haiku",
    },
    "minimax-free": {
        "MACOG_MODEL_BACKEND": "openrouter",
        "OPENROUTER_MODEL":    "minimax/minimax-m2.5:free",
    },
    "deepseek-direct": {
        "MACOG_MODEL_BACKEND": "deepseek",
    },
    "claude-direct": {
        "MACOG_MODEL_BACKEND": "claude",
    },
    "custom": {
        "MACOG_MODEL_BACKEND": "custom",
    },
}


def resolve_model(name: str) -> dict[str, str]:
    """Return env-var dict for the model name.  Unknown names treated as raw OPENROUTER_MODEL IDs."""
    return MODEL_REGISTRY.get(
        name,
        {"MACOG_MODEL_BACKEND": "openrouter", "OPENROUTER_MODEL": name},
    )
