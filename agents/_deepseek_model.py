"""
Custom DeepSeek model for MACOG agents.

Handles three DeepSeek-specific requirements:
  1. Multi-round chat  — reasoning_content from each turn is preserved and
                         passed back in the next request (DeepSeek requirement)
  2. Thinking mode     — <think>...</think> text blocks are stripped from
                         visible output so they don't pollute conversation history
  3. Tool calls        — deepseek-reasoner does NOT support `tool_choice`;
                         this wrapper removes it so both deepseek-chat and
                         deepseek-reasoner work transparently

References:
  https://api-docs.deepseek.com/guides/multi_round_chat
  https://api-docs.deepseek.com/guides/thinking_mode
  https://api-docs.deepseek.com/guides/tool_calls
"""
from __future__ import annotations

import re
from typing import Any, AsyncIterator

from strands.models.openai import OpenAIModel


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

# Models that do NOT support tool_choice (reasoner family)
_NO_TOOL_CHOICE_MODELS = {"deepseek-reasoner", "deepseek-v4-pro"}


class DeepSeekModel(OpenAIModel):
    """
    OpenAI-compatible DeepSeek model with multi-turn reasoning_content support,
    tool_choice stripping for reasoner models, and thinking block cleanup.
    """

    @classmethod
    def _format_regular_messages(cls, messages: list, **kwargs: Any) -> list[dict]:
        """
        Re-inject reasoning_content into formatted assistant messages.

        DeepSeek REQUIRES reasoning_content from each assistant turn to be passed
        back in the next request (400 error otherwise). Strands strips it in
        _format_regular_messages, so we re-inject it after the parent processes.
        """
        # Collect reasoning_content per assistant message from Strands internal format
        assistant_reasoning: list[str] = []
        for msg in messages:
            if msg["role"] != "assistant":
                continue
            parts = [
                content["reasoningContent"]["reasoningText"]["text"]
                for content in msg.get("content", [])
                if isinstance(content, dict)
                and "reasoningContent" in content
                and "reasoningText" in content.get("reasoningContent", {})
            ]
            assistant_reasoning.append("\n".join(parts) if parts else "")

        # Parent strips reasoningContent blocks (and emits a warning — expected)
        formatted = super()._format_regular_messages(messages, **kwargs)

        # Re-inject reasoning_content into each formatted assistant message
        asst_idx = 0
        for fmt_msg in formatted:
            if fmt_msg.get("role") == "assistant":
                if asst_idx < len(assistant_reasoning) and assistant_reasoning[asst_idx]:
                    fmt_msg["reasoning_content"] = assistant_reasoning[asst_idx]
                asst_idx += 1

        return formatted

    async def stream(  # type: ignore[override]
        self,
        messages: list,
        tool_specs: list | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator:
        # Strip tool_choice for reasoner models that reject it
        if self.config.get("model_id") in _NO_TOOL_CHOICE_MODELS:
            tool_choice = None

        async for chunk in super().stream(
            messages,
            tool_specs=tool_specs,
            system_prompt=system_prompt,
            tool_choice=tool_choice,
            **kwargs,
        ):
            # Strip <think>...</think> from visible text deltas
            if isinstance(chunk, dict):
                delta = chunk.get("delta", {})
                if isinstance(delta, dict) and "text" in delta:
                    delta["text"] = _THINK_RE.sub("", delta["text"]).lstrip()
            yield chunk
