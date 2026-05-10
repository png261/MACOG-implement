"""
Tools available to the Reviewer agent.

file_read               — built-in strands_tools; lets the LLM read .tf files from
                          the session directory for its own static analysis.
run_terraform_validate  — runs `terraform init + validate` on session files.
run_tflint              — runs `tflint --format json` on session files.

Both tool runs are independent and can be called in the same LLM response turn
so that ConcurrentToolExecutor runs them in parallel.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any

from strands import tool, ToolContext
from strands_tools import file_read  # noqa: F401

from agents._rtk import wrap_cmd


@tool(context=True)
def run_terraform_validate(
    session_dir: str = "",
    hcl_code: str = "",
    tool_context: ToolContext = None,
) -> str:
    """
    Run terraform init + validate on session files.

    Preferred: pass session_dir — .tf files are copied to a fresh tmpdir and
    validated with `terraform validate -json`.
    Fallback: pass hcl_code string when session_dir is unavailable, OR when
    terraform is not installed (structural brace/reference check used).

    Writes state keys: terraform_v_schema, terraform_diagnostics.
    Returns JSON: {v_schema, diagnostics, counterexamples}.
    """
    result: dict[str, Any] = {"v_schema": 0, "diagnostics": [], "counterexamples": []}

    with tempfile.TemporaryDirectory() as tmpdir:
        if session_dir and os.path.isdir(session_dir):
            for fname in os.listdir(session_dir):
                if fname.endswith(".tf"):
                    shutil.copy2(os.path.join(session_dir, fname), tmpdir)
        elif hcl_code:
            with open(os.path.join(tmpdir, "main.tf"), "w") as fh:
                fh.write(hcl_code)
        else:
            result["counterexamples"].append({
                "type": "schema", "summary": "No session_dir or hcl_code provided"
            })
            if tool_context is not None:
                tool_context.agent.state.set("terraform_v_schema", 0)
                tool_context.agent.state.set("terraform_diagnostics", json.dumps([]))
            return json.dumps(result)

        combined = _read_tf_dir(tmpdir)
        contract_errors = _macog_contract_check(combined)

        if os.environ.get("MACOG_EVAL_FAST_SCHEMA") == "1":
            ok, errs = _structural_check(combined)
            result["v_schema"] = 1 if ok else 0
            result["counterexamples"] = errs
        else:
            try:
                subprocess.run(
                    wrap_cmd(["terraform", "init", "-backend=false", "-no-color", "-input=false"]),
                    cwd=tmpdir, capture_output=True, text=True, timeout=90,
                )
                val = subprocess.run(
                    wrap_cmd(["terraform", "validate", "-json", "-no-color"]),
                    cwd=tmpdir, capture_output=True, text=True, timeout=30,
                )
                if val.stdout:
                    out = json.loads(val.stdout)
                    result["v_schema"] = 1 if out.get("valid", False) else 0
                    diags = out.get("diagnostics", [])
                    result["diagnostics"] = diags
                    result["counterexamples"] = [
                        {
                            "type": "schema",
                            "severity": d.get("severity", "error"),
                            "summary": d.get("summary", ""),
                            "detail": d.get("detail", ""),
                            "resource": d.get("address", ""),
                        }
                        for d in diags
                        if d.get("severity") == "error"
                    ]
            except (subprocess.TimeoutExpired, FileNotFoundError):
                ok, errs = _structural_check(combined)
                result["v_schema"] = 1 if ok else 0
                result["counterexamples"] = errs

        if contract_errors:
            result["v_schema"] = 0
            result["counterexamples"].extend(contract_errors)
            diagnostics = result.get("diagnostics", [])
            if not isinstance(diagnostics, list):
                diagnostics = [{"severity": "error", "summary": str(diagnostics)}]
            diagnostics.extend(contract_errors)
            result["diagnostics"] = diagnostics

    if tool_context is not None:
        tool_context.agent.state.set("terraform_v_schema", result["v_schema"])
        diags = result.get("diagnostics", [])
        tool_context.agent.state.set(
            "terraform_diagnostics",
            diags if isinstance(diags, str) else json.dumps(diags),
        )

    return json.dumps(result)


@tool(context=True)
def run_tflint(
    session_dir: str = "",
    hcl_code: str = "",
    tool_context: ToolContext = None,
) -> str:
    """
    Run tflint linter on session files.

    Preferred: pass session_dir — .tf files are copied to a fresh tmpdir and
    linted with `tflint --format json`.
    Fallback: pass hcl_code string.
    Returns {"available": false} silently if tflint is not installed.

    Writes state keys: lint_errors, lint_diagnostics.
    Returns JSON: {available, lint_diagnostics, lint_errors}.
    """
    result: dict[str, Any] = {"available": False, "lint_diagnostics": [], "lint_errors": []}

    with tempfile.TemporaryDirectory() as tmpdir:
        if session_dir and os.path.isdir(session_dir):
            for fname in os.listdir(session_dir):
                if fname.endswith(".tf"):
                    shutil.copy2(os.path.join(session_dir, fname), tmpdir)
        elif hcl_code:
            with open(os.path.join(tmpdir, "main.tf"), "w") as fh:
                fh.write(hcl_code)
        else:
            if tool_context is not None:
                tool_context.agent.state.set("lint_errors", json.dumps([]))
                tool_context.agent.state.set("lint_diagnostics", json.dumps([]))
            return json.dumps(result)

        try:
            lint = subprocess.run(
                wrap_cmd(["tflint", "--format", "json", "--no-color"]),
                cwd=tmpdir, capture_output=True, text=True, timeout=60,
            )
            result["available"] = True
            if lint.stdout:
                lint_out = json.loads(lint.stdout)
                for issue in lint_out.get("issues", []):
                    rule = issue.get("rule", {})
                    sev = rule.get("severity", "warning")
                    msg = issue.get("message", "")
                    fname = issue.get("range", {}).get("filename", "")
                    diag = {
                        "severity": sev,
                        "summary": msg,
                        "detail": f"tflint rule: {rule.get('name', '')} — {fname}",
                    }
                    result["lint_diagnostics"].append(diag)
                    if sev == "error":
                        result["lint_errors"].append({
                            "type": "schema", "severity": "error",
                            "summary": msg, "resource": "",
                        })
        except FileNotFoundError:
            pass  # tflint not installed
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            result["available"] = True  # installed but failed

    if tool_context is not None:
        errs = result.get("lint_errors", [])
        tool_context.agent.state.set(
            "lint_errors", errs if isinstance(errs, str) else json.dumps(errs)
        )
        diags = result.get("lint_diagnostics", [])
        tool_context.agent.state.set(
            "lint_diagnostics", diags if isinstance(diags, str) else json.dumps(diags)
        )

    return json.dumps(result)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _read_tf_dir(directory: str) -> str:
    parts: list[str] = []
    for fname in sorted(os.listdir(directory)):
        if fname.endswith(".tf"):
            with open(os.path.join(directory, fname)) as fh:
                parts.append(fh.read())
    return "\n".join(parts)


def _structural_check(hcl: str) -> tuple[bool, list[dict]]:
    errors: list[dict] = []
    depth = 0
    for ch in hcl:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if depth < 0:
            errors.append({"type": "schema", "summary": "Unmatched closing brace"})
            return False, errors
    if depth != 0:
        errors.append({"type": "schema", "summary": f"Unbalanced braces (depth={depth})"})
        return False, errors

    defined = {
        f"{kind}.{name}"
        for kind, name in re.findall(r'resource\s+"(\w+)"\s+"(\w+)"', hcl)
    }
    for ref_kind, ref_name in re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z_][A-Za-z0-9_]*', hcl):
        if ref_kind in ("var", "local", "module", "data", "path", "terraform", "aws", "google"):
            continue
        ref = f"{ref_kind}.{ref_name}"
        if ref not in defined:
            errors.append({
                "type": "schema",
                "summary": f"Possibly undefined reference: {ref}",
                "resource": ref,
            })
    return len(errors) == 0, errors


_REQUIRED_FIELDS: dict[str, set[str]] = {
    "aws_vpc": {"cidr_block"},
    "aws_subnet": {"vpc_id", "cidr_block"},
    "aws_instance": {"ami", "instance_type"},
    "aws_security_group": {"name", "description", "vpc_id"},
    "aws_db_instance": {"engine", "instance_class", "allocated_storage", "username"},
    "aws_db_subnet_group": {"subnet_ids"},
    "aws_lb": {"load_balancer_type", "subnets"},
    "aws_route53_record": {"zone_id", "name", "type"},
    "aws_s3_bucket_server_side_encryption_configuration": {"bucket", "rule"},
}

_TAGGABLE_TYPES = {
    "aws_s3_bucket",
    "aws_instance",
    "aws_vpc",
    "aws_subnet",
    "aws_security_group",
    "aws_db_instance",
    "aws_lb",
}


def _macog_contract_check(hcl: str) -> list[dict]:
    """
    Deterministic guard for the paper's constrained-realization contract.

    It does not replace provider validation; it catches generation patterns that
    are forbidden by MACOG before later validators spend work on the candidate.
    """
    errors: list[dict] = []
    if "${" in hcl:
        errors.append({
            "type": "schema",
            "severity": "error",
            "summary": "Legacy interpolation syntax is not allowed",
            "detail": "Use native Terraform references such as aws_vpc.main.id",
            "resource": "",
        })
    if "required_providers" not in hcl:
        errors.append({
            "type": "schema",
            "severity": "error",
            "summary": "Missing terraform.required_providers block",
            "detail": "Engineer output must pin provider versions",
            "resource": "terraform",
        })

    for rtype, rname, body in _resource_blocks(hcl):
        required = _REQUIRED_FIELDS.get(rtype, set())
        missing = sorted(
            field for field in required
            if not re.search(rf"\b{field}\s*(=|\{{)", body)
        )
        if missing:
            errors.append({
                "type": "schema",
                "severity": "error",
                "summary": f"{rtype}.{rname} missing required fields: {', '.join(missing)}",
                "detail": "Required-field guard from MACOG constrained compilation contract",
                "resource": f"{rtype}.{rname}",
            })
        if rtype in _TAGGABLE_TYPES:
            if "tags" not in body:
                errors.append({
                    "type": "schema",
                    "severity": "error",
                    "summary": f"{rtype}.{rname} missing required tags block",
                    "detail": "Governance tag guard from MACOG constrained compilation contract",
                    "resource": f"{rtype}.{rname}",
                })
            elif "Environment" not in body:
                errors.append({
                    "type": "schema",
                    "severity": "error",
                    "summary": f"{rtype}.{rname} missing required Environment tag",
                    "detail": "Governance tag guard from MACOG constrained compilation contract",
                    "resource": f"{rtype}.{rname}",
                })
    return errors


def _resource_blocks(hcl: str) -> list[tuple[str, str, str]]:
    blocks: list[tuple[str, str, str]] = []
    rx = re.compile(r'resource\s+"([A-Za-z0-9_]+)"\s+"([A-Za-z0-9_]+)"\s*\{')
    for match in rx.finditer(hcl):
        start = match.end()
        depth = 1
        i = start
        while i < len(hcl) and depth:
            if hcl[i] == "{":
                depth += 1
            elif hcl[i] == "}":
                depth -= 1
            i += 1
        blocks.append((match.group(1), match.group(2), hcl[start : i - 1]))
    return blocks
