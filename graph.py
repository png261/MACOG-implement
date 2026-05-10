"""
Strands Graph — Reviewer Gate + Parallel Validators

Graph topology:
  engineer → reviewer → (conditional) → engineer  (schema-fix loop)
  reviewer → security ┐
  reviewer → cost     ├──► collect
  reviewer → devops   ┘

Entry: engineer
Fan-out: reviewer fires security+cost+devops in parallel when v_schema==1
Collect fires after all three parallel nodes complete (unconditional edges).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any

from strands.multiagent import GraphBuilder, MultiAgentBase, MultiAgentResult, Status
from strands.session.session_manager import SessionManager

from blackboard import Blackboard, State, ValidatorOutput
from agents import (
    engineer_agent,
    reviewer_agent,
    security_prover_agent,
    cost_capacity_agent,
    devops_agent,
)
from agents.reviewer.output import ReviewerOutput
from agents.security_prover.output import SecurityProverOutput
from agents.cost_capacity.output import CostCapacityOutput
from agents.devops.output import DevOpsOutput


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ok_result() -> MultiAgentResult:
    return MultiAgentResult(status=Status.COMPLETED, execution_count=1)


def _parse_json(text: str) -> dict | None:
    """Extract first valid JSON object from agent response."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    break
    return None


def _parse_hcl(text: str) -> str:
    """Extract HCL code from agent response."""
    m = re.search(r'```(?:hcl|terraform)?\s*(.*?)```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    for kw in ("terraform {", 'provider "', 'resource "', 'variable "'):
        idx = text.find(kw)
        if idx >= 0:
            return text[idx:].strip()
    return text.strip()


def _is_retryable_agent_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "502",
            "503",
            "504",
            "bad gateway",
            "temporarily unavailable",
            "timeout",
            "connection error",
            "retryable",
            "rate limit",
        )
    )


def _invoke_agent(agent, prompt: str, label: str):
    retries = int(os.getenv("MACOG_AGENT_RETRIES", "2"))
    delay = float(os.getenv("MACOG_AGENT_RETRY_DELAY", "5"))
    for attempt in range(retries + 1):
        try:
            return agent(prompt)
        except Exception as exc:
            if attempt >= retries or not _is_retryable_agent_error(exc):
                raise
            wait = delay * (attempt + 1)
            print(
                f"[graph:{label}] transient error ({type(exc).__name__}); "
                f"retrying in {wait:.1f}s ({attempt + 1}/{retries})"
            )
            time.sleep(wait)
    raise RuntimeError(f"{label} failed unexpectedly")


# ── Node classes ──────────────────────────────────────────────────────────────

class EngineerNode(MultiAgentBase):
    """
    Compile I-IR → HCL (fresh) or apply schema fixes (loop-back mode).

    - Fresh compile: bb.review_issues is empty → compile P1 into main.tf
    - Schema-fix:    bb.review_issues not empty → apply targeted str_replace patches
    """

    def __init__(self, bb: Blackboard) -> None:
        self.id = "engineer"
        self.bb = bb

    async def invoke_async(
        self, task: Any, invocation_state: dict | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        bb = self.bb

        if bb.preserve_hcl_once and bb.hcl:
            bb.state = State.COMPILE
            bb.preserve_hcl_once = False
            main_tf = os.path.join(bb.session_dir, "main.tf")
            os.makedirs(bb.session_dir, exist_ok=True)
            with open(main_tf, "w") as f:
                f.write(bb.hcl)
            print(f"\n[graph:engineer] Preserving repaired HCL → {len(bb.hcl.splitlines())} lines")
            bb.evidence.append({
                "phase": "compile",
                "hcl_lines": len(bb.hcl.splitlines()),
                "source": "preserved_repair",
            })
            return _ok_result()

        if not bb.review_issues:
            # ── Fresh compile ──────────────────────────────────────────────────
            bb.state = State.COMPILE
            print(f"\n[graph:engineer] Compiling I-IR → HCL…")

            prompt = (
                f"Compile the following harmonized I-IR plan into complete HCL Terraform code.\n\n"
                f"PLAN:\n{json.dumps(bb.harmonized_plan, indent=2)}\n\n"
                f"CONSTRAINTS: {json.dumps(bb.constraints, indent=2)}\n\n"
                f"SESSION_DIR: {bb.session_dir}\n"
                f"After generating the HCL, call file_write(path=\"{bb.session_dir}/main.tf\", "
                f"content=<full HCL>) to persist the files to the shared session directory."
            )
        else:
            # ── Schema-fix mode ───────────────────────────────────────────────
            bb.state = State.COMPILE
            print(f"\n[graph:engineer] Schema-fix mode — {len(bb.review_issues)} issue(s) to address…")

            prompt = (
                f"Apply the following targeted fixes to the HCL Terraform code in the session directory.\n\n"
                f"SESSION_DIR: {bb.session_dir}\n\n"
                f"SCHEMA ISSUES TO FIX (ALL of them):\n{json.dumps(bb.review_issues, indent=2)}\n\n"
                f"Rules:\n"
                f"- Call file_read(path=\"{bb.session_dir}/main.tf\") first to load the current HCL\n"
                f"- Use editor(command=\"str_replace\", path=\"{bb.session_dir}/main.tf\", ...) "
                f"for each targeted patch — do NOT rewrite the whole file unless necessary\n"
                f"- Preserve all working resource blocks unchanged\n"
                f"- After all edits, list the edited file paths in files_written."
            )

        engineer_agent.state.set("session_dir", bb.session_dir)
        engineer_agent.state.set("constraints", bb.constraints)
        engineer_agent.state.set("iteration", bb.iteration)
        engineer_agent.state.set("repair_edits", bb.review_issues)
        result = _invoke_agent(engineer_agent, prompt, "engineer")

        main_tf = os.path.join(bb.session_dir, "main.tf")
        if os.path.exists(main_tf):
            with open(main_tf) as f:
                bb.hcl = f.read()
            print(f"[graph:engineer] → {len(bb.hcl.splitlines())} lines written to main.tf")
        else:
            parsed = _parse_hcl(str(result))
            if parsed:
                bb.hcl = parsed
            print(f"[graph:engineer] Warning: main.tf not found, fell back to text parsing "
                  f"({len(bb.hcl.splitlines())} lines)")

        bb.evidence.append({"phase": "compile", "hcl_lines": len(bb.hcl.splitlines())})
        return _ok_result()


class ReviewNode(MultiAgentBase):
    """
    Static review — calls Reviewer agent, sets v_schema.

    On failure (v_schema==0):
      - Populates bb.review_issues with error-severity issues
      - Increments bb.review_loop_count

    On pass (v_schema==1):
      - Clears bb.review_issues
    """

    def __init__(self, bb: Blackboard) -> None:
        self.id = "reviewer"
        self.bb = bb

    async def invoke_async(
        self, task: Any, invocation_state: dict | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        bb = self.bb
        bb.state = State.REVIEW
        print(f"\n[graph:reviewer] Running static analysis (loop={bb.review_loop_count})…")

        prompt = (
            f"Review the HCL Terraform code in the shared session directory.\n\n"
            f"SESSION_DIR: {bb.session_dir}\n\n"
            f"PLAN (for reference):\n{json.dumps(bb.harmonized_plan, indent=2)[:1500]}\n\n"
            f"Call file_read(path=\"{bb.session_dir}/main.tf\") to load the HCL, "
            f"then call run_terraform_validate(session_dir=\"{bb.session_dir}\") AND "
            f"run_tflint(session_dir=\"{bb.session_dir}\") in the same response "
            f"(they run concurrently), then output the review JSON. "
            f"v_schema=0 if either tool finds errors."
        )
        reviewer_agent.state.set("session_dir", bb.session_dir)
        try:
            agent_result = _invoke_agent(reviewer_agent, prompt, "reviewer")
            out: ReviewerOutput | None = agent_result.structured_output  # type: ignore[assignment]

            if out is None:
                raw = _parse_json(str(agent_result))
                if raw:
                    out = ReviewerOutput(**raw)
                # Fallback: read from agent state if structured_output and text parsing both fail
                if out is None:
                    v = reviewer_agent.state.get("terraform_v_schema")
                    if v is not None:
                        lint_raw = reviewer_agent.state.get("lint_errors") or "[]"
                        lint_errs = json.loads(lint_raw) if isinstance(lint_raw, str) else lint_raw
                        v_combined = v if not lint_errs else 0
                        out = ReviewerOutput(
                            v_schema=v_combined,
                            passed=v_combined == 1,
                            issues=[],
                            diagnostics=reviewer_agent.state.get("terraform_diagnostics") or "",
                        )
        except Exception as exc:
            print(f"[graph:reviewer] WARNING: {type(exc).__name__}: {exc} — skipping review")
            out = None

        if out:
            bb.validator.v_schema = out.v_schema
            schema_ces = [
                {**issue.model_dump(), "type": "schema"}
                for issue in out.issues
                if issue.severity == "error"
            ]
            bb.validator.counterexamples = (
                [ce for ce in bb.validator.counterexamples if ce.get("type") != "schema"]
                + schema_ces
            )

            if out.v_schema == 0:
                bb.review_issues = [issue.model_dump() for issue in out.issues if issue.severity == "error"]
                bb.review_loop_count += 1
                print(f"[graph:reviewer] → schema FAIL ({len(out.issues)} issues, "
                      f"loop_count={bb.review_loop_count}) — {out.diagnostics}")
            else:
                bb.review_issues = []
                print(f"[graph:reviewer] → schema PASS ({len(out.issues)} issues) — {out.diagnostics}")

            bb.evidence.append({
                "phase": "review",
                "v_schema": out.v_schema,
                "passed": out.passed,
                "issues": [issue.model_dump() for issue in out.issues],
                "diagnostics": out.diagnostics,
            })

        return _ok_result()


class SecurityNode(MultiAgentBase):
    """Security Prover — OPA/Rego policy check (v_policy). Catches all exceptions."""

    def __init__(self, bb: Blackboard) -> None:
        self.id = "security"
        self.bb = bb

    async def invoke_async(
        self, task: Any, invocation_state: dict | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        bb = self.bb
        bb.state = State.PROVE
        print(f"\n[graph:security] Evaluating policies…")

        plan_json = json.dumps(bb.harmonized_plan or {}, sort_keys=True)
        current_hash = hashlib.md5(plan_json.encode()).hexdigest()
        policy_file = os.path.join(bb.session_dir, "policy", "main.rego")
        plan_unchanged = (current_hash == bb.rego_plan_hash and os.path.exists(policy_file))

        if plan_unchanged:
            prompt = (
                f"The architecture plan is unchanged. The focused Rego policy files already exist.\n\n"
                f"SESSION_DIR: {bb.session_dir}\n\n"
                f"Do NOT regenerate policy files. Call run_encryption_check, "
                f"run_network_check, run_access_check, run_governance_check, "
                f"and run_scanner_check together in one response "
                f"(they run concurrently via ConcurrentToolExecutor):\n"
                f"  run_encryption_check(session_dir=\"{bb.session_dir}\")\n"
                f"  run_network_check(session_dir=\"{bb.session_dir}\")\n"
                f"  run_access_check(session_dir=\"{bb.session_dir}\")\n"
                f"  run_governance_check(session_dir=\"{bb.session_dir}\", "
                f"constraints_json='{json.dumps(bb.constraints)}')\n"
                f"  run_scanner_check(session_dir=\"{bb.session_dir}\")\n"
                f"Merge all violations; v_policy=0 if any critical/high violation. "
                f"Output SecurityProverOutput JSON."
            )
        else:
            bb.rego_plan_hash = current_hash
            plan_src = bb.harmonized_plan or bb.plan or {}
            prompt = (
                f"Generate security policy-as-code and check the infrastructure.\n\n"
                f"SESSION_DIR: {bb.session_dir}\n\n"
                f"I-IR ARCHITECTURE PLAN (source of truth for policy rules):\n"
                f"{json.dumps(plan_src, indent=2)[:3000]}\n\n"
                f"Steps:\n"
                f"1. Call generate_rego_suite(session_dir=\"{bb.session_dir}\", "
                f"iir_json='{json.dumps(plan_src)}')\n"
                f"2. Then call run_encryption_check, run_network_check, run_access_check, "
                f"run_governance_check, and run_scanner_check "
                f"together in one response (concurrent):\n"
                f"   run_encryption_check(session_dir=\"{bb.session_dir}\")\n"
                f"   run_network_check(session_dir=\"{bb.session_dir}\")\n"
                f"   run_access_check(session_dir=\"{bb.session_dir}\")\n"
                f"   run_governance_check(session_dir=\"{bb.session_dir}\", "
                f"constraints_json='{json.dumps(bb.constraints)}')\n"
                f"   run_scanner_check(session_dir=\"{bb.session_dir}\")\n"
                f"3. Merge violations; v_policy=0 if any critical/high violation.\n"
                f"4. Output SecurityProverOutput JSON."
            )
        security_prover_agent.state.set("session_dir", bb.session_dir)
        try:
            agent_result = _invoke_agent(security_prover_agent, prompt, "security")
            out: SecurityProverOutput | None = agent_result.structured_output  # type: ignore[assignment]

            if out is None:
                raw = _parse_json(str(agent_result))
                if raw:
                    out = SecurityProverOutput(**raw)

            if out:
                bb.validator.v_policy = out.v_policy
                policy_ces = [
                    {**viol.model_dump(), "type": "policy"}
                    for viol in out.violations
                    if viol.severity in ("critical", "high")
                ]
                bb.validator.counterexamples = (
                    [ce for ce in bb.validator.counterexamples if ce.get("type") != "policy"]
                    + policy_ces
                )
                status = "PASS" if out.v_policy else "FAIL"
                print(f"[graph:security] → policy {status} ({len(out.violations)} violations)")
                bb.evidence.append({
                    "phase": "prove",
                    "proof_traces": [t.model_dump() for t in out.proof_traces],
                })
        except Exception as exc:
            print(f"[graph:security] WARNING: {type(exc).__name__}: {exc} — skipping")

        return _ok_result()


class CostNode(MultiAgentBase):
    """Cost & Capacity Planner — infracost scan (v_cost). Catches all exceptions."""

    def __init__(self, bb: Blackboard) -> None:
        self.id = "cost"
        self.bb = bb

    async def invoke_async(
        self, task: Any, invocation_state: dict | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        bb = self.bb
        bb.state = State.PRICE
        budget = bb.budget()
        print(f"\n[graph:cost] Running cost estimation…")

        budget_arg = budget if budget != float('inf') else 0
        prompt = (
            f"Estimate costs for the Terraform code in the shared session directory.\n\n"
            f"SESSION_DIR: {bb.session_dir}\n"
            f"BUDGET: {budget if budget != float('inf') else 'none'}\n\n"
            f"Call run_infracost AND estimate_cost_from_catalog together in one response "
            f"(they run concurrently via ConcurrentToolExecutor):\n"
            f"  run_infracost(session_dir=\"{bb.session_dir}\", budget={budget_arg})\n"
            f"  estimate_cost_from_catalog(session_dir=\"{bb.session_dir}\", budget={budget_arg})\n"
            f"If run_infracost returns available=true, use it as authoritative for v_cost. "
            f"Otherwise use estimate_cost_from_catalog's v_cost value. "
            f"v_cost is the total monthly USD (ℝ≥0). Output CostCapacityOutput JSON."
        )
        cost_capacity_agent.state.set("session_dir", bb.session_dir)
        cost_capacity_agent.state.set("budget", budget)
        try:
            agent_result = _invoke_agent(cost_capacity_agent, prompt, "cost")
            out: CostCapacityOutput | None = agent_result.structured_output  # type: ignore[assignment]

            if out is None:
                raw = _parse_json(str(agent_result))
                if raw:
                    out = CostCapacityOutput(**raw)

            if out:
                bb.validator.v_cost = out.v_cost
                cost_ces = (
                    []
                    if out.within_budget
                    else [{**v.model_dump(), "type": "cost"} for v in out.violations]
                )
                bb.validator.counterexamples = (
                    [ce for ce in bb.validator.counterexamples if ce.get("type") != "cost"]
                    + cost_ces
                )
                status = "OK" if out.within_budget else "OVER BUDGET"
                finops = len(out.finops_violations)
                print(f"[graph:cost] → ${out.v_cost:.2f}/mo — {status}"
                      + (f" ({finops} FinOps issues)" if finops else ""))
                bb.evidence.append({"phase": "price", "cost_sheet": out.model_dump()})
        except Exception as exc:
            print(f"[graph:cost] WARNING: {type(exc).__name__}: {exc} — skipping")

        return _ok_result()


class DevOpsNode(MultiAgentBase):
    """DevOps — I-IR-driven Terratest (v_deploy). Catches all exceptions."""

    def __init__(self, bb: Blackboard) -> None:
        self.id = "devops"
        self.bb = bb

    async def invoke_async(
        self, task: Any, invocation_state: dict | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        bb = self.bb
        bb.state = State.DEPLOY
        print(f"\n[graph:devops] Running Terratest…")

        if os.getenv("MACOG_DEVOPS_MODE", "").lower() == "structural":
            from agents.devops.tools import check_deployment_structure

            raw = check_deployment_structure(session_dir=bb.session_dir)
            data = json.loads(raw)
            out = DevOpsOutput(
                v_deploy=data.get("v_deploy", 0),
                phase="structural",
                errors=data.get("errors", []),
                logs="MACOG_DEVOPS_MODE=structural; deterministic structural deployability check",
                sandbox="structural",
                terratest=None,
            )
            bb.validator.v_deploy = out.v_deploy
            deploy_ces = (
                []
                if out.v_deploy == 1
                else [{**e.model_dump(), "type": "runtime"} for e in out.errors]
            )
            bb.validator.counterexamples = (
                [ce for ce in bb.validator.counterexamples if ce.get("type") != "runtime"]
                + deploy_ces
            )
            print(f"[graph:devops] → {'PASS' if out.v_deploy else 'FAIL'} via structural "
                  f"{len(out.errors)} errors")
            bb.evidence.append({"phase": "deploy", "deploy_logs": out.logs})
            return _ok_result()

        plan_json = json.dumps(bb.harmonized_plan or {}, sort_keys=True)
        current_hash = hashlib.md5(plan_json.encode()).hexdigest()
        test_file = os.path.join(bb.session_dir, "test", "main_test.go")
        plan_unchanged = (current_hash == bb.terratest_plan_hash and os.path.exists(test_file))

        if plan_unchanged:
            prompt = (
                f"The architecture plan is unchanged. The Terratest suite already exists.\n\n"
                f"SESSION_DIR: {bb.session_dir}\n\n"
                f"Do NOT regenerate test files. Call run_go_tests directly:\n"
                f"  run_go_tests(session_dir=\"{bb.session_dir}\")\n"
                f"v_deploy=1 if all tests pass, 0 otherwise. Output DevOpsOutput JSON."
            )
        else:
            bb.terratest_plan_hash = current_hash
            plan_src = bb.harmonized_plan or bb.plan or {}
            prompt = (
                f"Test the deployability of the infrastructure using Terratest.\n\n"
                f"SESSION_DIR: {bb.session_dir}\n\n"
                f"I-IR ARCHITECTURE PLAN (source of truth for test assertions):\n"
                f"{json.dumps(plan_src, indent=2)[:3000]}\n\n"
                f"Steps:\n"
                f"1. Call generate_terratest_suite AND check_deployment_structure together "
                f"in one response (concurrent):\n"
                f"   generate_terratest_suite(session_dir=\"{bb.session_dir}\", "
                f"iir_json='{json.dumps(plan_src)}')\n"
                f"   check_deployment_structure(session_dir=\"{bb.session_dir}\")\n"
                f"2. After both complete, call run_go_tests:\n"
                f"   run_go_tests(session_dir=\"{bb.session_dir}\")\n"
                f"3. v_deploy=1 if all go tests pass (or structural check passes when Go "
                f"unavailable), 0 otherwise.\n"
                f"4. Output DevOpsOutput JSON."
            )

        devops_agent.state.set("session_dir", bb.session_dir)
        devops_agent.state.set("plan_hash", bb.terratest_plan_hash)
        try:
            agent_result = _invoke_agent(devops_agent, prompt, "devops")
            out: DevOpsOutput | None = agent_result.structured_output  # type: ignore[assignment]

            if out is None:
                raw = _parse_json(str(agent_result))
                if raw:
                    out = DevOpsOutput(**raw)

            if out:
                bb.validator.v_deploy = out.v_deploy
                deploy_ces = (
                    []
                    if out.v_deploy == 1
                    else [{**e.model_dump(), "type": "runtime"} for e in out.errors]
                )
                bb.validator.counterexamples = (
                    [ce for ce in bb.validator.counterexamples if ce.get("type") != "runtime"]
                    + deploy_ces
                )
                status = "PASS" if out.v_deploy else "FAIL"
                terratest_info = ""
                if out.terratest:
                    terratest_info = (
                        f" terratest={out.terratest.tests_run}tests/"
                        f"{len(out.terratest.failed_tests)}fail"
                    )
                print(f"[graph:devops] → {status} via {out.sandbox}{terratest_info} "
                      f"{len(out.errors)} errors")
                bb.evidence.append({"phase": "deploy", "deploy_logs": out.logs})
        except Exception as exc:
            print(f"[graph:devops] WARNING: {type(exc).__name__}: {exc} — skipping")

        return _ok_result()


class CollectNode(MultiAgentBase):
    """
    Terminal aggregation node — fires after all three parallel validators complete.
    Logs the final routing score; no blackboard mutations.
    """

    def __init__(self, bb: Blackboard) -> None:
        self.id = "collect"
        self.bb = bb

    async def invoke_async(
        self, task: Any, invocation_state: dict | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        bb = self.bb
        score = bb.validator.routing_score(bb.budget())
        print(
            f"[graph:collect] schema={bb.validator.v_schema} "
            f"policy={bb.validator.v_policy} "
            f"cost=${bb.validator.v_cost:.2f} "
            f"deploy={bb.validator.v_deploy} "
            f"J={score:.3f}"
        )
        return _ok_result()


# ── Graph factory ──────────────────────────────────────────────────────────────

def build_validate_graph(
    bb: Blackboard,
    max_review_loops: int = 3,
    session_manager: SessionManager | None = None,
    graph_id: str | None = None,
):
    """
    Build the reviewer-gated validation graph.

    engineer → reviewer ──► (v_schema==0, within budget) → engineer  (loop)
                        ──► (v_schema==1) → security + cost + devops → collect
    """
    builder = GraphBuilder()
    if graph_id:
        builder.set_graph_id(graph_id)
    if session_manager:
        builder.set_session_manager(session_manager)

    builder.add_node(EngineerNode(bb),  "engineer")
    builder.add_node(ReviewNode(bb),    "reviewer")
    builder.add_node(SecurityNode(bb),  "security")
    builder.add_node(CostNode(bb),      "cost")
    builder.add_node(DevOpsNode(bb),    "devops")
    builder.add_node(CollectNode(bb),   "collect")

    # Engineer → Reviewer (always)
    builder.add_edge("engineer", "reviewer")

    # Reviewer → Engineer feedback loop (schema failed, within budget)
    builder.add_edge(
        "reviewer", "engineer",
        condition=lambda s: bb.validator.v_schema == 0
                            and bb.review_loop_count < max_review_loops,
    )

    # Reviewer → parallel validators (schema passed)
    schema_ok = lambda s: bb.validator.v_schema == 1
    builder.add_edge("reviewer", "security", condition=schema_ok)
    builder.add_edge("reviewer", "cost",     condition=schema_ok)
    builder.add_edge("reviewer", "devops",   condition=schema_ok)

    # Parallel validators → collect (unconditional)
    builder.add_edge("security", "collect")
    builder.add_edge("cost",     "collect")
    builder.add_edge("devops",   "collect")

    builder.set_entry_point("engineer")
    # (max_review_loops+1) engineer+reviewer pairs + 3 validators + 1 collect
    builder.set_max_node_executions((max_review_loops + 1) * 2 + 5)
    builder.reset_on_revisit(True)

    return builder.build()
