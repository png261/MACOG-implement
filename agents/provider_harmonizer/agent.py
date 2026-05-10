"""
Provider Harmonizer Agent — MACOG §4.2

Instantiates abstract I-IR resources against provider schemas and regions,
resolves version constraints, and expands defaults to produce plan P1.

Uses the OpenTofu registry (https://mcp.opentofu.org) via on-demand tool
functions — no persistent MCP connection, no blocking at import time.
"""
from strands import Agent
from strands.vended_plugins.context_offloader import ContextOffloader, InMemoryStorage

from agents._model import get_model, get_conversation_manager
from agents._skills import agent_terrashark_plugin
from agents.provider_harmonizer.output import ProviderHarmonizerOutput
from agents.provider_harmonizer.system_prompt import SYSTEM_PROMPT
from agents.provider_harmonizer.tools import (
    opentofu_get_datasource_docs,
    opentofu_get_provider_details,
    opentofu_get_resource_docs,
    opentofu_search_registry,
    write_harmonized_plan,
)

provider_harmonizer_agent = Agent(
    model=get_model(),
    conversation_manager=get_conversation_manager(),
    name="provider_harmonizer",
    description="Instantiates abstract I-IR resources against provider schemas to produce P1.",
    structured_output_model=ProviderHarmonizerOutput,
    system_prompt=SYSTEM_PROMPT,
    plugins=[agent_terrashark_plugin("provider_harmonizer"), ContextOffloader(storage=InMemoryStorage())],
    tools=[
        opentofu_search_registry,
        opentofu_get_provider_details,
        opentofu_get_resource_docs,
        opentofu_get_datasource_docs,
        write_harmonized_plan,
    ],
    state={
        "constraints": {},
        "session_dir": "",
    },
)
