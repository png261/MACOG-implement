"""
Cost & Capacity Planner Agent — MACOG §4.2

Runs infracost scan and catalog-based estimation concurrently via
ConcurrentToolExecutor. If infracost returns available=true, uses it as
authoritative; otherwise uses the catalog estimate (which always succeeds).
"""
from strands import Agent
from strands.tools.executors import ConcurrentToolExecutor
from strands.vended_plugins.context_offloader import ContextOffloader, InMemoryStorage
from strands_tools import file_read

from agents._model import get_model, get_conversation_manager
from agents._skills import agent_terrashark_plugin
from agents.cost_capacity.output import CostCapacityOutput
from agents.cost_capacity.system_prompt import SYSTEM_PROMPT
from agents.cost_capacity.tools import (
    run_infracost,
    estimate_cost_from_catalog,
)

cost_capacity_agent = Agent(
    model=get_model(),
    conversation_manager=get_conversation_manager(),
    name="cost_capacity_planner",
    description="Runs infracost scan and catalog estimate concurrently on session files; returns CostCapacityOutput.",
    structured_output_model=CostCapacityOutput,
    system_prompt=SYSTEM_PROMPT,
    plugins=[agent_terrashark_plugin("cost_capacity"), ContextOffloader(storage=InMemoryStorage())],
    tool_executor=ConcurrentToolExecutor(),
    tools=[
        file_read,
        run_infracost,
        estimate_cost_from_catalog,
    ],
    state={
        "session_dir": "",
        "budget": 0.0,
        "infracost_available": False,
        "infracost_result": "",
        "catalog_result": "",
    },
)
