"""
Shared Blackboard — MACOG §4.2 / §4.7

All agents read/write typed artifacts here. The orchestrator advances the FSM
and gates transitions on validator contracts.

State machine (§4.9, eq. 14):
  plan → harmonize → compile → review → prove → price → deploy → repair → done
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class State(str, Enum):
    PLAN      = "plan"
    HARMONIZE = "harmonize"
    COMPILE   = "compile"
    REVIEW    = "review"
    PROVE     = "prove"
    PRICE     = "price"
    DEPLOY    = "deploy"
    REPAIR    = "repair"
    DONE      = "done"
    FAILED    = "failed"


@dataclass
class ValidatorOutput:
    """
    Structured outcome of v(T, C) = (v_schema, v_policy, v_cost, v_deploy)  §4.1 eq.(2)
    """
    v_schema: int = 0           # {0,1}  schema / type validity
    v_policy: int = 0           # {0,1}  OPA/Rego policy satisfaction
    v_cost:   float = 0.0       # R≥0    estimated monthly USD
    v_deploy: int = 0           # {0,1}  terraform plan/apply result
    counterexamples: list[dict] = field(default_factory=list)
    # CE_k = CE^schema ∪ CE^policy ∪ CE^cost ∪ CE^run  (§4.11 eq.17)

    def routing_score(self, budget: float, lambdas: tuple = (1.0, 1.0, 0.001, 1.0)) -> float:
        """
        J(T,C) = λ1(1−v_schema) + λ2(1−v_policy) + λ3·max(0, v_cost−B) + λ4(1−v_deploy)
        §4.4 eq.(4)
        """
        l1, l2, l3, l4 = lambdas
        cost_excess = max(0.0, self.v_cost - budget)
        return (
            l1 * (1 - self.v_schema)
            + l2 * (1 - self.v_policy)
            + l3 * cost_excess
            + l4 * (1 - self.v_deploy)
        )

    def is_feasible(self, budget: float) -> bool:
        """Φ(T,C) — all four validators satisfied  §4.4 eq.(7)"""
        return (
            self.v_schema == 1
            and self.v_policy == 1
            and self.v_deploy == 1
            and self.v_cost <= budget
        )


@dataclass
class Blackboard:
    """
    Versioned shared memory for MACOG.
    Each entry is stamped implicitly by iteration counter.
    """
    # ── Inputs ─────────────────────────────────────────────────────────────────
    state:       State = State.PLAN
    intent:      str = ""
    constraints: dict[str, Any] = field(default_factory=dict)

    # ── I-IR plan versions ─────────────────────────────────────────────────────
    plan:            dict | None = None   # P0 — raw Architect output
    harmonized_plan: dict | None = None  # P1 — after Provider Harmonizer

    # ── Compiled HCL ───────────────────────────────────────────────────────────
    hcl: str = ""

    # ── Shared filesystem session ───────────────────────────────────────────────
    # Created once by the orchestrator; Engineer writes HCL here; Reviewer,
    # Security Prover, Cost Planner, and DevOps tools read/operate on these files.
    session_dir: str = ""

    # ── Validator state ────────────────────────────────────────────────────────
    validator: ValidatorOutput = field(default_factory=ValidatorOutput)

    # ── Repair loop ────────────────────────────────────────────────────────────
    iteration:      int = 0
    max_iterations: int = 5

    # ── Evidence bundle Π ──────────────────────────────────────────────────────
    evidence: list[dict] = field(default_factory=list)

    # ── Memory — verified (P, T, Π) motifs ────────────────────────────────────
    memory: list[dict] = field(default_factory=list)

    # ── Repair history ─────────────────────────────────────────────────────────
    repair_history: list[dict] = field(default_factory=list)

    # ── Graph: reviewer gate ────────────────────────────────────────────────────
    review_issues: list[dict] = field(default_factory=list)
    # Populated by ReviewNode when v_schema==0 (error-severity issues only).
    # Consumed by EngineerNode to build targeted schema-fix prompt.
    # Cleared by ReviewNode when v_schema==1.

    review_loop_count: int = 0
    # Incremented by ReviewNode each time v_schema==0 (i.e. each loop-back).
    # Used by the conditional edge to cap engineer↔reviewer iterations.

    terratest_plan_hash: str = ""
    # MD5 of the last harmonized_plan JSON used to generate test/main_test.go.
    # DevOpsNode skips test regeneration when the plan hash is unchanged and
    # test/main_test.go already exists in session_dir.

    rego_plan_hash: str = ""
    # MD5 of the last harmonized_plan JSON used to generate policy/main.rego.
    # SecurityNode skips Rego regeneration when the plan hash is unchanged and
    # policy/main.rego already exists in session_dir.

    roundtrip: dict[str, Any] = field(default_factory=dict)
    # Latest P* = parse(T) structural equivalence result.

    content_hashes: dict[str, str] = field(default_factory=dict)
    # Reproducibility digests for plan, HCL, policy, tests, and generated files.

    preserve_hcl_once: bool = False
    # Set after outer-loop HCL repair so the next validation graph reviews the
    # patched artifact instead of recompiling from the prior I-IR.

    # ── Helpers ────────────────────────────────────────────────────────────────

    def budget(self) -> float:
        b = self.constraints.get("budget")
        return float("inf") if b is None else float(b)

    def snapshot(self) -> dict:
        """Serialize current state for passing to agents."""
        return {
            "state": self.state.value,
            "intent": self.intent,
            "constraints": self.constraints,
            "plan": self.plan,
            "harmonized_plan": self.harmonized_plan,
            "hcl": self.hcl,
            "validator": {
                "v_schema":  self.validator.v_schema,
                "v_policy":  self.validator.v_policy,
                "v_cost":    self.validator.v_cost,
                "v_deploy":  self.validator.v_deploy,
                "routing_score": self.validator.routing_score(self.budget()),
                "counterexamples": self.validator.counterexamples,
            },
            "iteration": self.iteration,
            "session_dir": self.session_dir,
            "repair_history": self.repair_history[-3:],
            "memory_size": len(self.memory),
            "review_loop_count": self.review_loop_count,
            "terratest_plan_hash": self.terratest_plan_hash,
            "rego_plan_hash": self.rego_plan_hash,
            "roundtrip": self.roundtrip,
            "content_hashes": self.content_hashes,
            "preserve_hcl_once": self.preserve_hcl_once,
        }
