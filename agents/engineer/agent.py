"""
Engineer Agent — MACOG §4.2

Compiles the harmonized I-IR plan P1 into complete, valid HCL Terraform code T,
then writes it to the shared session directory so that the Reviewer, Security
Prover, Cost & Capacity Planner, and DevOps agents can run their tools directly
on the filesystem files.
"""
from strands import Agent
from strands.vended_plugins.context_offloader import ContextOffloader, InMemoryStorage
from strands_tools import file_read

from agents._model import get_model, get_conversation_manager
from agents._skills import agent_terrashark_plugin
from agents.engineer.output import EngineerOutput
from agents.engineer.system_prompt import SYSTEM_PROMPT
from agents.engineer.tools import editor, file_write, retrieve_memory_motifs

engineer_agent = Agent(
    model=get_model(max_tokens=32000),   # needs room to generate full HCL
    conversation_manager=get_conversation_manager(window_size=6),
    name="engineer",
    description=(
        "Compiles harmonized I-IR plan P1 into HCL Terraform code and "
        "writes it to the shared session directory."
    ),
    structured_output_model=EngineerOutput,
    system_prompt=SYSTEM_PROMPT,
    plugins=[agent_terrashark_plugin("engineer"), ContextOffloader(storage=InMemoryStorage())],
    tools=[file_write, file_read, editor, retrieve_memory_motifs],
    state={
        "session_dir": "",
        "constraints": {},
        "iteration": 0,
        "repair_edits": [],
        "files_written": [],
    },
)
