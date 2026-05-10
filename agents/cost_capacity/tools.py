"""
Tools available to the Cost & Capacity Planner agent.

file_read                — built-in strands_tools; lets the LLM inspect .tf files.
run_infracost            — runs `infracost scan --json` on the session directory.
estimate_cost_from_catalog — parses HCL and estimates cost from a pinned AWS price
                             catalog. Always returns a result (never fails).

Both tools are independent and can be called in the same LLM response turn so
that ConcurrentToolExecutor runs them in parallel. If infracost returns
available=true, use it as authoritative; otherwise use the catalog estimate.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from typing import Any

from strands import tool, ToolContext
from strands_tools import file_read  # noqa: F401

from agents._rtk import wrap_cmd


# ── Price catalog (pinned AWS on-demand us-east-1, monthly USD) ───────────────

_PRICE_CATALOG: dict[str, Any] = {
    "aws_instance": {
        "t3.micro": 8.47, "t3.small": 16.93, "t3.medium": 33.87,
        "t3.large": 67.74, "t3.xlarge": 135.49, "t2.micro": 8.47,
        "t2.small": 16.93, "t2.medium": 33.87, "m5.large": 70.08,
        "m5.xlarge": 140.16, "default": 50.0,
    },
    "aws_db_instance": {
        "db.t3.micro": 24.82, "db.t3.small": 49.64, "db.t3.medium": 99.28,
        "db.t3.large": 198.56, "db.m5.large": 175.20, "default": 100.0,
    },
    "aws_s3_bucket": 5.0,
    "aws_lb": 16.43,
    "aws_alb": 16.43,
    "aws_elb": 16.43,
    "aws_elasticache_cluster": 25.0,
    "aws_elasticache_replication_group": 50.0,
    "aws_vpc": 0.0,
    "aws_subnet": 0.0,
    "aws_security_group": 0.0,
    "aws_internet_gateway": 0.0,
    "aws_route_table": 0.0,
    "aws_iam_role": 0.0,
    "aws_iam_policy": 0.0,
    "aws_iam_role_policy_attachment": 0.0,
    "aws_ebs_volume": 8.0,
    "aws_lambda_function": 5.0,
    "aws_cloudwatch_log_group": 2.0,
    "aws_sqs_queue": 1.0,
    "aws_sns_topic": 0.5,
    "aws_dynamodb_table": 10.0,
    "aws_eks_cluster": 144.0,
    "aws_ecr_repository": 2.0,
}


# ── Tool: run_infracost ────────────────────────────────────────────────────────

@tool(context=True)
def run_infracost(
    session_dir: str = "",
    hcl_code: str = "",
    budget: float = 0.0,
    tool_context: ToolContext = None,
) -> str:
    """
    Run `infracost scan --json` on session files. Returns real AWS pricing data.

    Preferred: pass session_dir — scans the shared session workspace directly.
    Fallback: pass hcl_code — written to a fresh tmpdir for scanning.

    Returns {"available": false} on FileNotFoundError or TimeoutExpired so the
    LLM can fall back to estimate_cost_from_catalog.

    Writes state keys: infracost_available, infracost_result.
    Returns JSON: {available, v_cost, total_monthly_cost, within_budget,
                   line_items, finops_violations, violations}.
    """
    effective_budget = float("inf") if budget <= 0 else budget
    result: dict[str, Any] = {
        "available": False,
        "v_cost": 0.0, "total_monthly_cost": 0.0, "within_budget": True,
        "line_items": [], "finops_violations": [], "violations": [], "currency": "USD",
    }

    _tmpdir_ctx = None
    if session_dir and os.path.isdir(session_dir):
        scan_target = session_dir
    elif hcl_code:
        _tmpdir_ctx = tempfile.mkdtemp(prefix="macog_cost_")
        with open(os.path.join(_tmpdir_ctx, "main.tf"), "w") as fh:
            fh.write(hcl_code)
        scan_target = _tmpdir_ctx
    else:
        result["violations"].append({"type": "input_error",
                                     "message": "No session_dir or hcl_code provided"})
        if tool_context is not None:
            tool_context.agent.state.set("infracost_available", False)
            tool_context.agent.state.set("infracost_result", json.dumps(result))
        return json.dumps(result)

    try:
        proc = subprocess.run(
            wrap_cmd(["infracost", "scan", scan_target, "--json"]),
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        if _tmpdir_ctx:
            import shutil
            shutil.rmtree(_tmpdir_ctx, ignore_errors=True)
        if tool_context is not None:
            tool_context.agent.state.set("infracost_available", False)
            tool_context.agent.state.set("infracost_result", json.dumps(result))
        return json.dumps(result)
    except subprocess.TimeoutExpired:
        if _tmpdir_ctx:
            import shutil
            shutil.rmtree(_tmpdir_ctx, ignore_errors=True)
        if tool_context is not None:
            tool_context.agent.state.set("infracost_available", False)
            tool_context.agent.state.set("infracost_result", json.dumps(result))
        return json.dumps(result)
    finally:
        if _tmpdir_ctx:
            import shutil
            shutil.rmtree(_tmpdir_ctx, ignore_errors=True)

    result["available"] = True

    # infracost emits two JSON objects on stdout (first is empty, second is real)
    raw = proc.stdout.strip()
    scan_data: dict = {}
    for chunk in raw.split("\n{"):
        candidate = chunk if chunk.startswith("{") else "{" + chunk
        try:
            parsed = json.loads(candidate)
            if parsed.get("summary", {}).get("resources", 0) > 0 or parsed.get("projects"):
                scan_data = parsed
                break
        except json.JSONDecodeError:
            continue

    if not scan_data:
        result["violations"].append({"type": "parse_error",
                                     "message": "Could not parse infracost output",
                                     "raw": raw[:300]})
        if tool_context is not None:
            tool_context.agent.state.set("infracost_available", True)
            tool_context.agent.state.set("infracost_result", json.dumps(result))
        return json.dumps(result)

    summary = scan_data.get("summary", {})
    total = float(summary.get("total_monthly_cost", 0))
    result["v_cost"] = total
    result["total_monthly_cost"] = total

    for project in scan_data.get("projects", []):
        for res in project.get("resources", []):
            monthly = sum(float(cc.get("total_monthly_cost", 0))
                          for cc in res.get("cost_components", []))
            for sub in res.get("subresources", []):
                monthly += sum(float(cc.get("total_monthly_cost", 0))
                               for cc in sub.get("cost_components", []))
            result["line_items"].append({"resource": res["name"],
                                         "monthly_cost": round(monthly, 3)})
        for policy in project.get("finops_results", []):
            for failing_res in policy.get("failing_resources", []):
                for issue in failing_res.get("issues", []):
                    result["finops_violations"].append({
                        "policy": policy.get("policy_name", ""),
                        "resource": failing_res.get("name", ""),
                        "description": issue.get("description", ""),
                        "monthly_savings": issue.get("monthly_savings", "0"),
                    })

    within_budget = total <= effective_budget
    result["within_budget"] = within_budget
    if not within_budget:
        result["violations"].append({
            "type": "budget_exceeded", "estimated": total,
            "budget": effective_budget, "excess": round(total - effective_budget, 2),
            "counterexample": {"type": "cost", "v_cost": total, "budget": effective_budget},
            "fix": "Downgrade instance types or remove non-essential resources",
        })

    if tool_context is not None:
        tool_context.agent.state.set("infracost_available", True)
        tool_context.agent.state.set("infracost_result", json.dumps(result))

    return json.dumps(result)


# ── Tool: estimate_cost_from_catalog ──────────────────────────────────────────

@tool(context=True)
def estimate_cost_from_catalog(
    session_dir: str = "",
    hcl_code: str = "",
    budget: float = 0.0,
    tool_context: ToolContext = None,
) -> str:
    """
    Parse HCL resources and estimate monthly cost from a pinned AWS price catalog.

    Always returns a real estimate — never fails. Regex-scans .tf files for
    resource blocks, extracts instance_type where present, and looks up each
    resource in _PRICE_CATALOG.

    Writes state key: catalog_result.
    Returns JSON: {resources, estimated_monthly_cost, within_budget, line_items}.
    """
    effective_budget = float("inf") if budget <= 0 else budget

    # Collect HCL content
    hcl = ""
    if session_dir and os.path.isdir(session_dir):
        hcl = _read_tf_dir(session_dir)
    elif hcl_code:
        hcl = hcl_code
    else:
        result = {
            "resources": [], "estimated_monthly_cost": 0.0,
            "within_budget": True, "line_items": [],
            "note": "No session_dir or hcl_code provided",
        }
        if tool_context is not None:
            tool_context.agent.state.set("catalog_result", json.dumps(result))
        return json.dumps(result)

    # Parse resource blocks: resource "type" "name" { ... }
    resource_blocks = re.findall(r'resource\s+"(\w+)"\s+"(\w+)"\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}',
                                  hcl, re.DOTALL)
    if not resource_blocks:
        # Simpler fallback: just find type + name pairs
        resource_blocks = [
            (rtype, rname, "")
            for rtype, rname in re.findall(r'resource\s+"(\w+)"\s+"(\w+)"', hcl)
        ]

    line_items: list[dict] = []
    finops_violations: list[dict] = []
    violations: list[dict] = []
    total = 0.0
    unknown_skus: list[str] = []

    for rtype, rname, rbody in resource_blocks:
        # Try to find instance_type or node_type attribute
        instance_type = ""
        m = re.search(r'(?:instance_type|node_type)\s*=\s*"([^"]+)"', rbody)
        if m:
            instance_type = m.group(1)

        catalog_entry = _PRICE_CATALOG.get(rtype)
        if catalog_entry is None:
            monthly = 0.0
        elif isinstance(catalog_entry, dict):
            if instance_type and instance_type not in catalog_entry:
                unknown_skus.append(f"{rtype}.{rname}:{instance_type}")
                monthly = catalog_entry.get("default", 0.0)
                violations.append({
                    "type": "sku_unavailable",
                    "resource": f"{rtype}.{rname}",
                    "message": f"Instance/SKU {instance_type} is not in the pinned price catalog",
                    "counterexample": {
                        "type": "cost",
                        "resource": f"{rtype}.{rname}",
                        "sku": instance_type,
                    },
                    "fix": "Select a cataloged, region-supported instance class",
                })
            else:
                monthly = catalog_entry.get(instance_type, catalog_entry.get("default", 0.0))
        else:
            monthly = float(catalog_entry)

        line_items.append({
            "resource": f"{rtype}.{rname}",
            "instance_type": instance_type,
            "monthly_cost": round(monthly, 2),
        })
        total += monthly

    total = round(total, 2)
    within_budget = total <= effective_budget

    result: dict[str, Any] = {
        "v_cost": total,          # paper eq.(2): v_cost ∈ ℝ≥0
        "resources": [f"{rt}.{rn}" for rt, rn, _ in resource_blocks],
        "estimated_monthly_cost": total,
        "within_budget": within_budget,
        "line_items": line_items,
    }
    if not within_budget:
        budget_violation = {
            "type": "budget_exceeded", "estimated": total,
            "budget": effective_budget, "excess": round(total - effective_budget, 2),
            "counterexample": {"type": "cost", "v_cost": total, "budget": effective_budget},
            "fix": "Downgrade instance types or remove non-essential resources",
        }
        result["budget_violation"] = budget_violation
        violations.append(budget_violation)

    if len(resource_blocks) > 20:
        finops_violations.append({
            "policy": "capacity_review",
            "resource": "module",
            "description": "Large resource count may require quota and regional capacity review",
            "monthly_savings": "0",
        })

    result["violations"] = violations
    result["finops_violations"] = finops_violations
    result["capacity_notes"] = (
        "Unknown SKUs: " + ", ".join(unknown_skus)
        if unknown_skus
        else "No SKU/catalog capacity concerns detected by local catalog"
    )

    if tool_context is not None:
        tool_context.agent.state.set("catalog_result", json.dumps(result))

    return json.dumps(result)




# ── Internal helpers ──────────────────────────────────────────────────────────

def _read_tf_dir(directory: str) -> str:
    parts: list[str] = []
    for fname in sorted(os.listdir(directory)):
        if fname.endswith(".tf"):
            with open(os.path.join(directory, fname)) as fh:
                parts.append(fh.read())
    return "\n".join(parts)
