"""
Architect Agent — MACOG §4.2

Parses natural language intent and non-functional constraints into a typed
Infrastructure Intermediate Representation (I-IR) plan P0.
"""
from strands import Agent
from strands.vended_plugins.context_offloader import ContextOffloader, InMemoryStorage

import os

from agents._model import get_model, get_conversation_manager
from agents._skills import agent_terrashark_plugin
from agents.architect.output import ArchitectOutput
from agents.architect.system_prompt import SYSTEM_PROMPT
from agents.architect.tools import (
    handoff_to_user,
    retrieve_memory_motifs,
    write_ir_plan,
)

_tools = (
    [retrieve_memory_motifs, write_ir_plan]
    if os.getenv("MACOG_EVAL_MODE")
    else [
        handoff_to_user,
        retrieve_memory_motifs,
        write_ir_plan,
    ]
)

architect_agent = Agent(
    model=get_model(),
    conversation_manager=get_conversation_manager(),
    name="architect",
    description="Parses natural language intent and constraints into a typed I-IR plan P0.",
    structured_output_model=ArchitectOutput,
    system_prompt=SYSTEM_PROMPT,
    plugins=[agent_terrashark_plugin("architect"), ContextOffloader(storage=InMemoryStorage())],
    tools=_tools,
    state={
        "intent": "",
        "constraints": {},
        "memory_motifs": [],
        "session_dir": "",
    },
)
