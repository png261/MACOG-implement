"""
Memory Curator Agent — MACOG §4.2

Stores verified (P, T, Π) tuples with metadata, indexes motifs in a symbolic
catalog keyed by structure and constraints, and serves reusable I-IR fragments
to the Architect and Engineer when plans match by structure and constraints.
"""
from strands import Agent
from strands.vended_plugins.context_offloader import ContextOffloader, InMemoryStorage

from agents._model import get_model, get_conversation_manager
from agents._skills import agent_terrashark_plugin
from agents.memory_curator.output import MemoryCuratorOutput
from agents.memory_curator.system_prompt import SYSTEM_PROMPT
from agents.memory_curator.tools import retrieve_memory_motifs, store_memory_motif

memory_curator_agent = Agent(
    model=get_model(),
    conversation_manager=get_conversation_manager(),
    name="memory_curator",
    description="Stores/retrieves verified I-IR motifs; returns MemoryCuratorOutput.",
    structured_output_model=MemoryCuratorOutput,
    system_prompt=SYSTEM_PROMPT,
    plugins=[agent_terrashark_plugin("memory_curator"), ContextOffloader(storage=InMemoryStorage())],
    tools=[retrieve_memory_motifs, store_memory_motif],
    state={
        "action": "",
        "query": "",
    },
)
