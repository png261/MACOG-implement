"""
Reviewer Agent — MACOG §4.2

Runs static validators (terraform validate, HCL linters) and performs
interface sanity checks, detecting missing variables, stray outputs, dead
resources, and inconsistent naming. Emits precise diagnostics and patches.

run_terraform_validate and run_tflint are independent and run concurrently
via ConcurrentToolExecutor when the LLM calls them in the same response.
"""
from strands import Agent
from strands.tools.executors import ConcurrentToolExecutor
from strands.vended_plugins.context_offloader import ContextOffloader, InMemoryStorage
from strands_tools import file_read

from agents._model import get_model, get_conversation_manager
from agents._skills import agent_terrashark_plugin
from agents.reviewer.output import ReviewerOutput
from agents.reviewer.system_prompt import SYSTEM_PROMPT
from agents.reviewer.tools import run_terraform_validate, run_tflint

reviewer_agent = Agent(
    model=get_model(),
    conversation_manager=get_conversation_manager(),
    name="reviewer",
    description="Runs static analysis and terraform validate on session files; returns ReviewerOutput.",
    structured_output_model=ReviewerOutput,
    system_prompt=SYSTEM_PROMPT,
    plugins=[agent_terrashark_plugin("reviewer"), ContextOffloader(storage=InMemoryStorage())],
    tool_executor=ConcurrentToolExecutor(),
    tools=[file_read, run_terraform_validate, run_tflint],
    state={
        "session_dir": "",
        "terraform_v_schema": 0,
        "terraform_diagnostics": "",
        "lint_errors": "",
        "lint_diagnostics": "",
    },
)
