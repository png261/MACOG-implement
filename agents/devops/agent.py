"""
DevOps Agent — MACOG §4.2

Generates an I-IR-driven Terratest deployability test, writes it to
{session_dir}/test/, and runs it against ministack.

LLM call sequence:
  Turn 1 (parallel): generate_terratest_suite AND check_deployment_structure
  Turn 2: run_go_tests (sequential — needs suite to exist first)
"""
from strands import Agent
from strands.tools.executors import ConcurrentToolExecutor
from strands.vended_plugins.context_offloader import ContextOffloader, InMemoryStorage
from strands_tools import file_read, file_write

from agents._model import get_model, get_conversation_manager
from agents._skills import agent_terrashark_plugin
from agents.devops.output import DevOpsOutput
from agents.devops.system_prompt import SYSTEM_PROMPT
from agents.devops.tools import (
    generate_terratest_suite,
    check_deployment_structure,
    run_go_tests,
)

devops_agent = Agent(
    model=get_model(),
    conversation_manager=get_conversation_manager(),
    name="devops",
    description="Generates a Terratest suite from I-IR, runs go test against ministack; returns DevOpsOutput.",
    structured_output_model=DevOpsOutput,
    system_prompt=SYSTEM_PROMPT,
    plugins=[agent_terrashark_plugin("devops"), ContextOffloader(storage=InMemoryStorage())],
    tool_executor=ConcurrentToolExecutor(),
    tools=[file_read, file_write,
           generate_terratest_suite, check_deployment_structure, run_go_tests],
    state={
        "session_dir": "",
        "test_functions": "",
        "scaffold_logs": "",
        "structural_errors": "",
        "v_deploy": 0,
        "terratest_result": "",
        "plan_hash": "",
    },
)
