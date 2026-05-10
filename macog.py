"""
MACOG Orchestrator — Algorithm 1 (§4.6, §4.7, §4.11)

Deterministic finite-state machine over the Blackboard.

States: plan → harmonize → compile → review → prove → price → deploy → repair → done

The orchestrator is NOT an LLM; it is a pure Python controller that:
  - Invokes agents at each state
  - Reads AgentResult.structured_output (validated Pydantic model instances)
  - Falls back to string parsing when structured_output is None
  - Computes the routing score J(T, C)
  - Maps counterexamples to edits via EεE : CE → Δ
  - Loops until J = 0 or repair budget K is exhausted
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from typing import Any

from blackboard import Blackboard, State, ValidatorOutput
from graph import build_validate_graph
from agents._session import get_session_manager, normalize_session_id, session_storage_dir
from agents.architect import ArchitectOutput
from agents.provider_harmonizer import ProviderHarmonizerOutput
from agents.memory_curator import MemoryCuratorOutput
from agents import (
    architect_agent,
    provider_harmonizer_agent,
    engineer_agent,
    memory_curator_agent,
)
from agents.memory_curator.tools import retrieve_memory_motifs
from roundtrip import check_roundtrip, content_hashes, toolchain_digests


class MACOGOrchestrator:
    """
    Implements Algorithm 1: MACOG Orchestration with Counterexample-Guided Repair.

    Require: intent x, constraints C, attempt budget K
    1.  P0, I  ← Architect(x, C, Mem)
    2.  P1     ← ProviderHarm(P0, Γprov)
    3.  T̃ = Cs(P1); T0 = D(T̃, ΣHCL, Σprov, S)
    4.  P* ← parse(T0); round-trip check
    5.  v0, CE0 ← V(T0, C)
    6.  for i = 0 … K−1:
    7.    if J(Ti, C) = 0 → return (Ti, Π)
    8.    Δi ← EεE(CEi)
    9.    (Pi+1, Ti+1) ← Ψ(Pi, Ti, Δi)
    10.   vi+1, CEi+1 ← V(Ti+1, C)
    11. return report_unsatisfied_core(CEK)
    """

    def __init__(
        self,
        max_iterations: int = 5,
        session_id: str | None = None,
        session_storage: str | None = None,
    ):
        self.K = max_iterations
        base_session_id = session_id or os.getenv("MACOG_SESSION_ID") or f"macog-{uuid.uuid4().hex[:12]}"
        self.session_id = normalize_session_id(base_session_id)
        self.session_storage = session_storage or session_storage_dir()
        self._validate_graph_runs = 0

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, intent: str, constraints: dict | None = None) -> dict:
        """
        Execute the full MACOG pipeline.
        Returns {state, hcl, plan, evidence, iterations, final_score}.
        """
        session_dir = tempfile.mkdtemp(prefix="macog_session_")
        bb = Blackboard(
            intent=intent,
            constraints=constraints or {},
            max_iterations=self.K,
            session_dir=session_dir,
        )
        print(f"[MACOG] session_dir: {session_dir}")
        print(f"[MACOG] session_manager: {self.session_id} @ {self.session_storage}")
        print(f"\n{'='*64}")
        print(f"[MACOG] intent: {intent[:80]}...")
        print(f"[MACOG] constraints: {bb.constraints}")
        print(f"{'='*64}")

        # ── Lines 1-2: Memory → Plan → Harmonize ─────────────────────────────
        self._step_memory_retrieve(bb)
        bb = self._step_plan(bb)
        bb = self._step_harmonize(bb)

        # ── Lines 3-5: Compile + Review gate + Parallel validators (graph) ────
        self._run_validate_graph(bb)
        self._enforce_roundtrip(bb)

        # ── Lines 6-10: Repair loop ───────────────────────────────────────────
        for i in range(self.K):
            bb.iteration = i
            score = bb.validator.routing_score(bb.budget())
            self._log_iteration(bb, i, score)

            if score == 0.0:                    # J(T,C) = 0 ← feasible
                bb.state = State.DONE
                break

            bb = self._step_repair(bb)          # Δi ← EεE(CEi); apply Ψ
            self._run_validate_graph(bb)        # vi+1, CEi+1
            self._enforce_roundtrip(bb)
            if bb.validator.routing_score(bb.budget()) == 0.0:
                bb.state = State.DONE
                break

        # ── Line 11: Finalise ─────────────────────────────────────────────────
        if bb.state != State.DONE:
            core = self._unsatisfied_core(bb)
            print(f"\n[MACOG] Budget exhausted. Unsatisfied: {core}")
            bb.state = State.FAILED

        evidence = self._build_evidence_bundle(bb)

        if bb.state == State.DONE:
            self._step_memory_store(bb)

        print(f"\n[MACOG] Pipeline {bb.state.value.upper()} in {bb.iteration} repairs.")
        return {
            "state":       bb.state.value,
            "hcl":         bb.hcl,
            "plan":        bb.harmonized_plan or bb.plan,
            "evidence":    evidence,
            "iterations":  bb.iteration,
            "final_score": bb.validator.routing_score(bb.budget()),
            "session_dir": bb.session_dir,
            "session_id": self.session_id,
            "session_storage": self.session_storage,
        }

    # ── FSM: State Handlers ───────────────────────────────────────────────────

    def _step_memory_retrieve(self, bb: Blackboard) -> None:
        """Retrieve verified motifs before planning (§4.8)."""
        try:
            raw = retrieve_memory_motifs(
                intent=bb.intent,
                constraints_json=json.dumps(bb.constraints),
            )
            data = json.loads(raw) if isinstance(raw, str) else raw
            motifs = data.get("motifs", []) if isinstance(data, dict) else []
            bb.memory = motifs
            print(f"\n[memory] Retrieved {len(motifs)} verified motif(s)")
            bb.evidence.append({
                "phase": "memory_retrieve",
                "motifs": [
                    {
                        "id": motif.get("id", ""),
                        "description": motif.get("description", ""),
                        "provider": motif.get("provider", ""),
                        "version": motif.get("version", ""),
                        "resource_kinds": motif.get("resource_kinds", []),
                    }
                    for motif in motifs
                    if isinstance(motif, dict)
                ],
            })
        except Exception as exc:
            print(f"\n[memory] Retrieval skipped: {type(exc).__name__}: {exc}")
            bb.memory = []
            bb.evidence.append({
                "phase": "memory_retrieve",
                "error": str(exc),
                "motifs": [],
            })

    def _step_plan(self, bb: Blackboard) -> Blackboard:
        """State: plan — Architect produces I-IR plan P0."""
        bb.state = State.PLAN
        print(f"\n[plan] Architect generating I-IR plan…")

        prompt = (
            f"Generate an I-IR plan for the following infrastructure intent.\n\n"
            f"INTENT: {bb.intent}\n\n"
            f"CONSTRAINTS: {json.dumps(bb.constraints, indent=2)}"
        )
        architect_agent.state.set("intent", bb.intent)
        architect_agent.state.set("constraints", bb.constraints)
        architect_agent.state.set("memory_motifs", bb.memory)
        architect_agent.state.set("session_dir", bb.session_dir)
        result = self._invoke_agent(architect_agent, prompt, "architect")
        out: ArchitectOutput | None = result.structured_output  # type: ignore[assignment]

        if out:
            bb.plan = out.model_dump()
            print(f"[plan]  → {len(out.resources)} resources, {len(out.edges)} edges")
        else:
            # Fallback: parse text response
            bb.plan = self._parse_json(str(result)) or {
                "resources": [], "edges": [], "specs": {}, "invariants": []
            }
            print(f"[plan]  Warning: structured_output absent, fell back to text parsing")

        bb.evidence.append({"phase": "plan", "resources": len(bb.plan.get("resources", []))})
        return bb

    def _step_harmonize(self, bb: Blackboard) -> Blackboard:
        """State: harmonize — Provider Harmonizer produces P1."""
        bb.state = State.HARMONIZE
        print(f"\n[harmonize] Provider Harmonizer resolving schemas…")

        prompt = (
            f"Harmonize the following I-IR plan against provider schemas.\n\n"
            f"PLAN:\n{json.dumps(bb.plan, indent=2)}\n\n"
            f"CONSTRAINTS: {json.dumps(bb.constraints, indent=2)}"
        )
        provider_harmonizer_agent.state.set("constraints", bb.constraints)
        provider_harmonizer_agent.state.set("session_dir", bb.session_dir)
        result = self._invoke_agent(provider_harmonizer_agent, prompt, "provider_harmonizer")
        out: ProviderHarmonizerOutput | None = result.structured_output  # type: ignore[assignment]

        if out:
            bb.harmonized_plan = out.model_dump()
            print(f"[harmonize]  → {len(out.resources)} resources, "
                  f"providers={out.provider_versions}")
        else:
            bb.harmonized_plan = self._parse_json(str(result)) or bb.plan
            print(f"[harmonize]  Warning: structured_output absent, fell back to text parsing")

        bb.evidence.append({"phase": "harmonize",
                            "resources": len(bb.harmonized_plan.get("resources", []))})
        return bb

    # ── Validators (via Strands Graph) ────────────────────────────────────────

    def _run_validate_graph(self, bb: Blackboard) -> None:
        """Run the reviewer-gated validation graph (compile → review loop → parallel validators)."""
        bb.review_issues = []
        bb.review_loop_count = 0
        bb.validator = ValidatorOutput()
        graph_run_id = f"{self.session_id}-validate-{self._validate_graph_runs}"
        self._validate_graph_runs += 1
        graph = build_validate_graph(
            bb,
            max_review_loops=3,
            session_manager=get_session_manager(
                scope="validate",
                session_id=graph_run_id,
                storage_dir=self.session_storage,
            ),
            graph_id=graph_run_id,
        )
        try:
            graph("run validation pipeline")
        except Exception as exc:
            print(f"[MACOG] validate graph error: {exc}")

    def _enforce_roundtrip(self, bb: Blackboard) -> None:
        """
        Parse compiled Terraform back into a structural artifact and verify it
        preserves the harmonized I-IR resource graph (§4.5/Algorithm 1 line 4).
        """
        plan = bb.harmonized_plan or bb.plan or {}
        result = check_roundtrip(plan, bb.hcl)
        bb.roundtrip = result.to_dict()
        bb.content_hashes = content_hashes(bb.session_dir, plan, bb.hcl)
        bb.evidence.append({
            "phase": "roundtrip",
            "roundtrip": bb.roundtrip,
            "content_hashes": bb.content_hashes,
        })
        bb.validator.counterexamples = [
            ce for ce in bb.validator.counterexamples
            if ce.get("rule") != "roundtrip_equivalence"
        ]
        if result.passed:
            print("[roundtrip] PASS — HCL preserves harmonized I-IR structure")
            return

        failures = (
            result.missing_resources
            + result.missing_edges
            + result.dangling_references
            + result.cycles
        )
        bb.validator.v_schema = 0
        bb.validator.counterexamples.append({
            "type": "schema",
            "rule": "roundtrip_equivalence",
            "severity": "error",
            "summary": "Compiled HCL failed I-IR round-trip equivalence",
            "detail": "; ".join(failures[:8]),
            "patch": "Recompile or patch main.tf so every I-IR resource and dependency is represented",
        })
        print(f"[roundtrip] FAIL — {len(failures)} structural mismatch(es)")

    # ── Repair: EεE : CE → Δ and Ψ ──────────────────────────────────────────

    def _step_repair(self, bb: Blackboard) -> Blackboard:
        """
        State: repair — Map counterexamples to edits (EεE) and apply (Ψ).

        Edit decomposition (§4.11 eq.17):
          A(CE) = ∪_{τ ∈ {schema,policy,cost,run}} A_τ(CE^τ)

        Prefer plan-level edits for structural/cost violations;
        use HCL-level patches for field-level fixes.
        """
        bb.state = State.REPAIR
        if not bb.validator.counterexamples:
            return bb

        ces_by_type: dict[str, list[dict]] = {
            "schema": [],
            "policy": [],
            "cost":   [],
            "runtime":[],
        }
        for ce in bb.validator.counterexamples:
            ces_by_type.setdefault(ce.get("type", "schema"), []).append(ce)

        edits = self._error_to_edit(ces_by_type)

        print(
            f"\n[repair] i={bb.iteration} | "
            f"schema={len(ces_by_type['schema'])} "
            f"policy={len(ces_by_type['policy'])} "
            f"cost={len(ces_by_type['cost'])} "
            f"runtime={len(ces_by_type['runtime'])} "
            f"→ {len(edits)} edits"
        )

        # I-IR-level edits (cost) → re-harmonize; compile deferred to graph re-entry
        ir_edits = [e for e in edits if e["level"] == "ir"]
        hcl_edits = [e for e in edits if e["level"] == "hcl"]

        if ir_edits:
            bb = self._apply_ir_edits(bb, ir_edits)
            bb = self._step_harmonize(bb)
            # compile + review happen inside _run_validate_graph on next outer iteration

        if hcl_edits:  # policy + runtime only (schema handled by graph loop)
            bb = self._apply_hcl_edits(bb, hcl_edits)

        bb.repair_history.append({
            "iteration": bb.iteration,
            "edits":     edits,
            "ces_count": len(bb.validator.counterexamples),
        })
        return bb

    def _error_to_edit(self, ces_by_type: dict[str, list[dict]]) -> list[dict]:
        """
        Deterministic EεE : CE → Δ mapping  (§4.6 eq.12)
        Returns a list of edit operations, tagged with level (ir|hcl).
        """
        edits: list[dict] = []

        for ce in ces_by_type["schema"]:
            edits.append({
                "level":   "hcl",
                "action":  "fix_schema",
                "target":  ce.get("resource", ""),
                "message": ce.get("message", ce.get("summary", "")),
                "fix":     ce.get("patch", ce.get("detail", "Fix the schema error")),
            })

        for ce in ces_by_type["policy"]:
            edits.append({
                "level":   "hcl",
                "action":  f"fix_policy_{ce.get('rule', 'policy')}",
                "target":  ce.get("resource", ""),
                "message": ce.get("message", ""),
                "fix":     ce.get("fix", "Fix the policy violation"),
            })

        for ce in ces_by_type["cost"]:
            edits.append({
                "level":   "ir",   # cost fixes require I-IR downgrade
                "action":  "reduce_cost",
                "message": ce.get("message", ""),
                "excess":  ce.get("excess", 0),
                "fix":     ce.get("fix", "Downgrade instance types to reduce cost"),
            })

        for ce in ces_by_type["runtime"]:
            edits.append({
                "level":   "hcl",
                "action":  f"fix_runtime_{ce.get('type', 'error')}",
                "target":  ce.get("resource", ""),
                "message": ce.get("message", ""),
                "fix":     ce.get("fix", "Fix the runtime error"),
            })

        return edits

    def _apply_hcl_edits(self, bb: Blackboard, edits: list[dict]) -> Blackboard:
        """Apply HCL-level patches — minimal targeted changes only."""
        prompt = (
            f"Apply the following targeted fixes to the HCL Terraform code in the session directory.\n\n"
            f"SESSION_DIR: {bb.session_dir}\n\n"
            f"EDITS TO APPLY (ALL of them):\n{json.dumps(edits, indent=2)}\n\n"
            f"Rules:\n"
            f"- Call file_read(path=\"{bb.session_dir}/main.tf\") first to load the current HCL\n"
            f"- Use editor(command=\"str_replace\", path=\"{bb.session_dir}/main.tf\", ...) "
            f"for each targeted patch — do NOT rewrite the whole file unless necessary\n"
            f"- Preserve all working resource blocks unchanged\n"
            f"- After all edits, list the edited file paths in files_written."
        )
        try:
            agent_result = self._invoke_agent(engineer_agent, prompt, "engineer_repair")
            main_tf = os.path.join(bb.session_dir, "main.tf")
            if os.path.exists(main_tf):
                with open(main_tf) as f:
                    patched = f.read()
                if len(patched) > 60:
                    bb.hcl = patched
                    bb.preserve_hcl_once = True
            else:
                hcl = self._parse_hcl(str(agent_result))
                if hcl and len(hcl) > 60:
                    bb.hcl = hcl
                    bb.preserve_hcl_once = True
        except Exception as exc:
            print(f"[repair]  WARNING: engineer raised {type(exc).__name__}: {exc} — keeping existing HCL")
        return bb

    def _apply_ir_edits(self, bb: Blackboard, ir_edits: list[dict]) -> Blackboard:
        """Apply I-IR-level edits — structural and cost changes."""
        prompt = (
            f"Apply the following edits to this I-IR plan to fix structural/cost issues.\n\n"
            f"CURRENT PLAN:\n{json.dumps(bb.harmonized_plan or bb.plan, indent=2)}\n\n"
            f"EDITS:\n{json.dumps(ir_edits, indent=2)}\n\n"
            f"Apply minimal required changes."
        )
        agent_result = self._invoke_agent(architect_agent, prompt, "architect_repair")
        out: ArchitectOutput | None = agent_result.structured_output  # type: ignore[assignment]
        if out:
            bb.harmonized_plan = out.model_dump()
        else:
            repaired = self._parse_json(str(agent_result))
            if repaired:
                bb.harmonized_plan = repaired
        return bb

    # ── Memory Curator ────────────────────────────────────────────────────────

    def _step_memory_store(self, bb: Blackboard) -> None:
        """Store verified (P, T, Π) tuple as motifs via Memory Curator."""
        prompt = (
            f"Store the following verified infrastructure as reusable motifs.\n\n"
            f"VERIFIED PLAN:\n{json.dumps(bb.harmonized_plan, indent=2)[:1500]}\n\n"
            f"HCL (first 500 chars):\n{bb.hcl[:500]}\n\n"
            f"CONSTRAINTS: {json.dumps(bb.constraints)}\n\n"
            f"Extract key reusable patterns and call store_memory_motif for each."
        )
        agent_result = self._invoke_agent(memory_curator_agent, prompt, "memory_curator")
        out: MemoryCuratorOutput | None = agent_result.structured_output  # type: ignore[assignment]

        if out is None:
            raw = self._parse_json(str(agent_result))
            if raw:
                out = MemoryCuratorOutput(**raw)

        if out and out.motifs:
            print(f"[memory] Stored {len(out.motifs)} motifs")

    # ── Evidence Bundle  Π = Bundle(traces, proofs, logs) ────────────────────

    def _build_evidence_bundle(self, bb: Blackboard) -> dict:
        """§4.9 — Proof-carrying bundle for offline verification."""
        budget = bb.budget()
        return {
            "static_validation": [
                e for e in bb.evidence if e.get("phase") == "review"
            ],
            "policy_traces":  [e for e in bb.evidence if e.get("phase") == "prove"],
            "cost_sheet":     next(
                (e.get("cost_sheet") for e in bb.evidence if e.get("phase") == "price"), {}
            ),
            "deploy_logs":    next(
                (e.get("deploy_logs") for e in bb.evidence if e.get("phase") == "deploy"), ""
            ),
            "roundtrip": bb.roundtrip,
            "provider_versions": (bb.harmonized_plan or {}).get("provider_versions", {}),
            "provider_schema_snapshots": [
                e for e in bb.evidence if e.get("phase") == "harmonize"
            ],
            "compiler_provenance": {
                "session_dir": bb.session_dir,
                "toolchain": toolchain_digests(),
                "content_hashes": bb.content_hashes,
            },
            "residency_redundancy": {
                "regions": bb.constraints.get("regions", []),
                "availability": bb.constraints.get("availability"),
                "invariants": (bb.harmonized_plan or bb.plan or {}).get("invariants", []),
            },
            "memory": {
                "retrieval": [
                    e for e in bb.evidence if e.get("phase") == "memory_retrieve"
                ],
                "motif_count": len(bb.memory),
            },
            "repair_history": bb.repair_history,
            "final_validators": {
                "v_schema":      bb.validator.v_schema,
                "v_policy":      bb.validator.v_policy,
                "v_cost":        bb.validator.v_cost,
                "v_deploy":      bb.validator.v_deploy,
                "routing_score": bb.validator.routing_score(budget),
            },
            "iterations": bb.iteration,
        }

    def _unsatisfied_core(self, bb: Blackboard) -> list[str]:
        """§4.11 — report_unsatisfied_core(CE_K)"""
        budget = bb.budget()
        core = []
        if not bb.validator.v_schema:
            core.append("schema")
        if not bb.validator.v_policy:
            core.append("policy")
        if bb.validator.v_cost > budget:
            core.append(f"cost(${bb.validator.v_cost:.2f} > ${budget})")
        if not bb.validator.v_deploy:
            core.append("deploy")
        return core

    def _log_iteration(self, bb: Blackboard, i: int, score: float) -> None:
        print(
            f"\n[MACOG] iter={i} J={score:.3f} | "
            f"schema={bb.validator.v_schema} "
            f"policy={bb.validator.v_policy} "
            f"cost=${bb.validator.v_cost:.2f} "
            f"deploy={bb.validator.v_deploy}"
        )

    def _invoke_agent(self, agent, prompt: str, label: str):
        retries = int(os.getenv("MACOG_AGENT_RETRIES", "2"))
        delay = float(os.getenv("MACOG_AGENT_RETRY_DELAY", "5"))
        for attempt in range(retries + 1):
            try:
                return agent(prompt)
            except Exception as exc:
                retryable = self._is_retryable_agent_error(exc)
                if attempt >= retries or not retryable:
                    raise
                wait = delay * (attempt + 1)
                print(
                    f"[MACOG] {label} transient error "
                    f"({type(exc).__name__}); retrying in {wait:.1f}s "
                    f"({attempt + 1}/{retries})"
                )
                time.sleep(wait)
        raise RuntimeError(f"{label} failed unexpectedly")

    def _is_retryable_agent_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        markers = (
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
        return any(marker in text for marker in markers)

    # ── Parsing helpers ───────────────────────────────────────────────────────

    def _parse_json(self, text: str) -> dict | None:
        """Extract first valid JSON object from agent response."""
        text = text.strip()
        # Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Markdown code fence
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # Largest brace-balanced segment
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

    def _parse_hcl(self, text: str) -> str:
        """Extract HCL code from agent response."""
        # Markdown code fence (hcl or terraform)
        m = re.search(r'```(?:hcl|terraform)?\s*(.*?)```', text, re.DOTALL)
        if m:
            return m.group(1).strip()
        # Find the start of HCL content
        for kw in ("terraform {", 'provider "', 'resource "', 'variable "'):
            idx = text.find(kw)
            if idx >= 0:
                return text[idx:].strip()
        return text.strip()
