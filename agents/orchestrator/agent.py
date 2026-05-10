"""
MACOG Orchestrator Agent — Algorithm 1 (§4.6, §4.7, §4.11)

A Strands Agent that drives the full MACOG pipeline.  It accepts a natural
language infrastructure request, delegates to the run_macog_pipeline tool
(which runs the deterministic FSM with the 8 specialist agents), and returns
a structured OrchestratorOutput.

The 8 specialist agents are also available directly as sub-tools so the
orchestrator can re-invoke any single stage independently (e.g. to recompile
after an ad-hoc plan edit without running the full loop).
"""
from strands import Agent

from agents._model import get_model, get_conversation_manager
from agents._session import get_session_manager
from agents._skills import agent_terrashark_plugin
from agents.orchestrator.output import OrchestratorOutput
from agents.orchestrator.system_prompt import SYSTEM_PROMPT
from agents.orchestrator.tools import run_macog_pipeline

# Import specialist agents for direct sub-tool access
from agents.architect import architect_agent
from agents.provider_harmonizer import provider_harmonizer_agent
from agents.engineer import engineer_agent
from agents.reviewer import reviewer_agent
from agents.security_prover import security_prover_agent
from agents.cost_capacity import cost_capacity_agent
from agents.devops import devops_agent
from agents.memory_curator import memory_curator_agent

orchestrator_agent = Agent(
    model=get_model(),
    conversation_manager=get_conversation_manager(window_size=20),  # orchestrator needs longer context
    session_manager=get_session_manager("orchestrator"),
    name="macog_orchestrator",
    description=(
        "Drives the full MACOG IaC pipeline: plan → harmonize → compile → "
        "review → prove → price → deploy → repair* → done. "
        "Accepts a natural language infrastructure request and returns "
        "verified HCL Terraform code with a proof-carrying evidence bundle."
    ),
    structured_output_model=OrchestratorOutput,
    system_prompt=SYSTEM_PROMPT,
    plugins=[agent_terrashark_plugin("orchestrator")],
    tools=[
        run_macog_pipeline,
        architect_agent.as_tool(
            name="architect",
            description="Generate I-IR plan P0 from intent and constraints.",
        ),
        provider_harmonizer_agent.as_tool(
            name="provider_harmonizer",
            description="Harmonize I-IR plan against provider schemas to produce P1.",
        ),
        engineer_agent.as_tool(
            name="engineer",
            description="Compile harmonized I-IR plan P1 into HCL Terraform code.",
        ),
        reviewer_agent.as_tool(
            name="reviewer",
            description="Run static analysis and terraform validate on HCL.",
        ),
        security_prover_agent.as_tool(
            name="security_prover",
            description="Evaluate OPA/Rego security policies against HCL.",
        ),
        cost_capacity_agent.as_tool(
            name="cost_capacity_planner",
            description="Run infracost scan and validate cost/capacity constraints.",
        ),
        devops_agent.as_tool(
            name="devops",
            description="Run terraform plan against ministack sandbox.",
        ),
        memory_curator_agent.as_tool(
            name="memory_curator",
            description="Store or retrieve verified I-IR motifs from memory.",
        ),
    ],
)
