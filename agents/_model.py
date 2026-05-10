"""
Shared model and conversation-manager factories for all MACOG agents.

Models:
  - OpenRouter Free (default) — zero-cost OpenAI-compatible router.
      Filters for request features such as tool calling and structured outputs.
      Uses standard multi-turn chat messages.
  - DeepSeek V4 Pro — via custom DeepSeekModel wrapper.
      Strips tool_choice so deepseek-reasoner (v4-pro) accepts tool-call requests.
      Strips <think>...</think> blocks from responses (thinking mode cleanup).
  - Claude via OpenAI-compatible proxy (llm.chiasegpu.vn/v1).

SlidingWindowConversationManager with per_turn=True + should_truncate_results=True:
  - Proactively trims context before each model call (not just at the end)
  - Truncates large tool results (full HCL strings, terraform JSON, infracost output)
  - window_size=10 keeps the last 10 message exchanges
"""
from __future__ import annotations

import os
from pathlib import Path

from agents._deepseek_model import DeepSeekModel
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models.openai import OpenAIModel


def _load_env_file(path: Path | None = None) -> None:
    """
    Load KEY=VALUE pairs from .env into os.environ without overriding
    values that were already exported by the caller.
    """
    env_path = path or Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env_required(*names: str) -> str:
    _load_env_file()
    for name in names:
        value = os.getenv(name)
        if value:
            return value

    joined = " or ".join(names)
    raise RuntimeError(f"Missing required API key. Set {joined} in .env or the environment.")


def get_model(max_tokens: int = 16000):
    _load_env_file()
    backend = os.getenv("MACOG_MODEL_BACKEND")
    if not backend:
        backend = "custom" if os.getenv("CUSTOM_API_KEY") and os.getenv("CUSTOM_BASE_URL") else "openrouter"
    if backend == "deepseek":
        return get_deepseek_model(max_tokens)
    if backend == "claude":
        return get_claude_model(max_tokens)
    if backend == "custom":
        return get_custom_model(max_tokens)
    return get_openrouter_model(max_tokens)


def get_openrouter_model(max_tokens: int = 16000) -> OpenAIModel:
    _load_env_file()
    return OpenAIModel(
        model_id=os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat-v3-0324:free"),
        client_args={
            "api_key": _env_required("OPENROUTER_API_KEY"),
            "base_url": "https://openrouter.ai/api/v1",
            "default_headers": {
                "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost"),
                "X-Title": os.getenv("OPENROUTER_APP_TITLE", "MACOG"),
            },
        },
        params={"max_tokens": max_tokens},
    )


def get_deepseek_model(max_tokens: int = 16000) -> DeepSeekModel:
    return DeepSeekModel(
        model_id="deepseek-v4-pro",
        client_args={
            "api_key": _env_required("DEEPSEEK_API_KEY"),
            "base_url": "https://api.deepseek.com",
        },
        params={"max_tokens": max_tokens},
    )


def get_claude_model(max_tokens: int = 16000) -> OpenAIModel:
    """
    Claude via OpenAI-compatible proxy at https://llm.chiasegpu.vn/v1.
    Set CLAUDE_API_KEY (or ANTHROPIC_API_KEY / ARTHROPIC_API_KEY) in .env.
    Set CLAUDE_MODEL_ID to override the default model (default: claude-sonnet-4-6).
    """
    _load_env_file()
    return OpenAIModel(
        model_id=os.getenv("CLAUDE_MODEL_ID", "claude-sonnet-4-6"),
        client_args={
            "api_key": _env_required(
                "CLAUDE_API_KEY",
                "ANTHROPIC_API_KEY",
                "ARTHROPIC_API_KEY",
                "ARTHORPIC_API_KEY",
            ),
            "base_url": os.getenv("CLAUDE_BASE_URL", "https://llm.chiasegpu.vn/v1"),
        },
        params={"max_tokens": max_tokens},
    )


def get_custom_model(max_tokens: int = 16000) -> OpenAIModel:
    _load_env_file()
    return OpenAIModel(
        model_id=os.getenv("CUSTOM_MODEL_ID"),
        client_args={
            "api_key": _env_required(
                "CUSTOM_API_KEY",
            ),
            "base_url": os.getenv("CUSTOM_BASE_URL"),
        },
        params={"max_tokens": max_tokens},
    )

def get_conversation_manager(
    window_size: int = 10,
    per_turn: bool = True,
) -> SlidingWindowConversationManager:
    """
    Returns a SlidingWindowConversationManager configured for MACOG agents.

    per_turn=True  — trim context before every model call, not just at the end.
    should_truncate_results=True — replace oversized tool results with a short
                                   placeholder instead of evicting whole messages.
    window_size    — number of recent messages to retain.
    """
    return SlidingWindowConversationManager(
        window_size=window_size,
        per_turn=per_turn,
        should_truncate_results=True,
    )
