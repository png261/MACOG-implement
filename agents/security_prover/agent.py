"""
Security Prover Agent — MACOG §4.2

Generates Rego policy-as-code from the I-IR architecture plan, writes focused
Rego files per rule group to {session_dir}/policy/, then runs conftest (OPA)
against each rule group. Falls back to Python-based checks when conftest is
not installed.

LLM call sequence:
  Turn 1: generate_rego_suite (writes focused Rego files)
  Turn 2: run_encryption_check + run_network_check + run_access_check +
          run_governance_check + run_scanner_check (parallel via ConcurrentToolExecutor)
"""
from strands import Agent
from strands.tools.executors import ConcurrentToolExecutor
from strands.vended_plugins.context_offloader import ContextOffloader, InMemoryStorage
from strands_tools import file_read, file_write

from agents._model import get_model, get_conversation_manager
from agents._skills import agent_terrashark_plugin
from agents.security_prover.output import SecurityProverOutput
from agents.security_prover.system_prompt import SYSTEM_PROMPT
from agents.security_prover.tools import (
    generate_rego_suite,
    run_encryption_check,
    run_network_check,
    run_access_check,
    run_governance_check,
    run_scanner_check,
)

security_prover_agent = Agent(
    model=get_model(),
    conversation_manager=get_conversation_manager(),
    name="security_prover",
    description="Generates focused Rego policies from I-IR plan and runs parallel OPA/conftest checks; returns SecurityProverOutput.",
    structured_output_model=SecurityProverOutput,
    system_prompt=SYSTEM_PROMPT,
    plugins=[agent_terrashark_plugin("security_prover"), ContextOffloader(storage=InMemoryStorage())],
    tool_executor=ConcurrentToolExecutor(),
    tools=[file_read, file_write, generate_rego_suite,
           run_encryption_check, run_network_check, run_access_check,
           run_governance_check, run_scanner_check],
    state={
        "session_dir": "",
        "rego_files": "",
        "encryption_violations": "",
        "network_violations": "",
        "access_violations": "",
        "governance_violations": "",
        "scanner_violations": "",
    },
)
