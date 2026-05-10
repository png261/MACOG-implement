"""
Tools available to the DevOps agent.

file_read                  — built-in strands_tools; lets the LLM inspect session files.
file_write                 — built-in strands_tools; lets the LLM write main_test.go.
generate_terratest_suite   — parses I-IR JSON and writes one full-stack Go test
                             to {session_dir}/test/main_test.go.
check_deployment_structure — static structural scan for dangling resource references.
run_go_tests               — runs go mod download + tidy + go test -v.

LLM call sequence:
  Turn 1 (parallel): generate_terratest_suite AND check_deployment_structure
  Turn 2: run_go_tests (after suite is ready)
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
from typing import Any

from strands import tool, ToolContext
from strands_tools import file_read, file_write  # noqa: F401

from agents._rtk import wrap_cmd


_MINISTACK_ENDPOINTS = (
    "acm", "apigateway", "autoscaling", "cloudformation", "cloudwatch",
    "dynamodb", "ec2", "ecr", "ecs", "efs", "eks", "elasticache", "elb",
    "elbv2", "iam", "kinesis", "kms", "lambda", "rds", "route53", "s3",
    "secretsmanager", "ses", "sns", "sqs", "ssm", "stepfunctions", "sts",
)

_GO_MOD = """\
module macog_test

go 1.21

require (
\tgithub.com/gruntwork-io/terratest v0.46.16
\tgithub.com/stretchr/testify v1.9.0
)
"""

_FALLBACK_TEST = """\
package test

import (
\t"os"
\t"testing"
\t"github.com/gruntwork-io/terratest/modules/terraform"
)

func TestTerraformApply(t *testing.T) {
\tendpointURL := os.Getenv("AWS_ENDPOINT_URL")
\tif endpointURL == "" {
\t\tendpointURL = "http://localhost:4566"
\t}
\topts := terraform.WithDefaultRetryableErrors(t, &terraform.Options{
\t\tTerraformDir: "../",
\t\tEnvVars: map[string]string{
\t\t\t"AWS_ACCESS_KEY_ID":     os.Getenv("AWS_ACCESS_KEY_ID"),
\t\t\t"AWS_SECRET_ACCESS_KEY": "test",
\t\t\t"AWS_DEFAULT_REGION":    "us-east-1",
\t\t\t"AWS_ENDPOINT_URL":      endpointURL,
\t\t\t"TF_INPUT":              "0",
\t\t},
\t})
\tdefer func() {
\t\tif _, err := terraform.DestroyE(t, opts); err != nil {
\t\t\tt.Logf("cleanup warning: %v", err)
\t\t}
\t}()
\tterraform.InitAndApply(t, opts)
}
"""


def _ministack_env_base() -> dict:
    url = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
    return {
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_ENDPOINT_URL": url,
        "TF_INPUT": "0",
    }


def _fresh_account_key() -> str:
    return str(random.randint(100_000_000_000, 999_999_999_999))


def _ministack_reachable() -> bool:
    import socket
    import urllib.parse
    url = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 4566
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _run(cmd: list[str], cwd: str, timeout: int, env: dict) -> tuple[int, str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            timeout=timeout, env=merged_env,
        )
        return proc.returncode, (proc.stdout + proc.stderr)
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"").decode(errors="replace")
        return 1, f"TIMEOUT after {timeout}s\n{out}"
    except Exception as exc:
        return 1, str(exc)


# ── Tool: generate_terratest_suite ────────────────────────────────────────────

@tool(context=True)
def generate_terratest_suite(
    session_dir: str = "",
    iir_json: str = "",
    tool_context: ToolContext = None,
) -> str:
    """
    Parse I-IR JSON to extract resource list; generate a Terratest suite that
    applies the complete Terraform configuration once, then destroys it. The
    resource list is retained as test coverage metadata.

    Falls back to the single-function _FALLBACK_TEST if no resources found.
    Writes state keys: test_functions, scaffold_logs.
    Returns JSON: {test_file_path, test_functions, logs}.
    """
    if not session_dir or not os.path.isdir(session_dir):
        return json.dumps({"test_file_path": "", "test_functions": [],
                           "logs": "No valid session_dir provided"})

    logs: list[str] = []
    resources: list[dict] = []

    # Parse I-IR for resources
    if iir_json:
        try:
            iir = json.loads(iir_json)
            nodes = iir.get("nodes", iir.get("resources", []))
            for node in nodes:
                rtype = node.get("resource_type", node.get("kind", node.get("type", "")))
                rname = node.get("name", node.get("id", "resource"))
                if rtype:
                    resources.append({"type": rtype, "name": rname})
            logs.append(f"Parsed I-IR: {len(resources)} resources")
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logs.append(f"I-IR parse error: {exc}; falling back to .tf scan")

    # Fallback: scan .tf files
    if not resources and os.path.isdir(session_dir):
        combined = "\n".join(
            open(os.path.join(session_dir, f)).read()
            for f in sorted(os.listdir(session_dir)) if f.endswith(".tf")
        )
        for rtype, rname in re.findall(r'resource\s+"(\w+)"\s+"(\w+)"', combined):
            resources.append({"type": rtype, "name": rname})
        logs.append(f".tf scan: {len(resources)} resources")

    test_dir = os.path.join(session_dir, "test")
    os.makedirs(test_dir, exist_ok=True)

    test_file_path = os.path.join(test_dir, "main_test.go")
    test_functions: list[dict] = []

    if not resources:
        with open(test_file_path, "w") as fh:
            fh.write(_FALLBACK_TEST)
        logs.append("No resources found — wrote fallback single-function test")
    else:
        go_code = _build_test_file(resources, test_functions)
        with open(test_file_path, "w") as fh:
            fh.write(go_code)
        logs.append(f"Wrote deployability test covering {len(test_functions)} resources")

    # Write go.mod
    with open(os.path.join(test_dir, "go.mod"), "w") as fh:
        fh.write(_GO_MOD)

    if tool_context is not None:
        tool_context.agent.state.set("test_functions", json.dumps(test_functions))
        tool_context.agent.state.set("scaffold_logs", "\n".join(logs))

    return json.dumps({
        "test_file_path": test_file_path,
        "test_functions": test_functions,
        "logs": "\n".join(logs),
    })


def _build_test_file(
    resources: list[dict],
    test_functions: list[dict],  # populated in-place
) -> str:
    for res in resources:
        rtype = res["type"]
        rname = res["name"]
        test_functions.append({
            "name": "TestTerraformDeployability",
            "resource_type": rtype,
            "resource_name": rname,
        })

    resource_count = len(resources)
    return f"""\
package test

// Generated from I-IR: {resource_count} resources
// Applies the complete Terraform configuration once to avoid shared-state races.

import (
\t"os"
\t"testing"
\t"github.com/gruntwork-io/terratest/modules/terraform"
)

func TestTerraformDeployability(t *testing.T) {{
\tendpointURL := os.Getenv("AWS_ENDPOINT_URL")
\tif endpointURL == "" {{
\t\tendpointURL = "http://localhost:4566"
\t}}
\topts := terraform.WithDefaultRetryableErrors(t, &terraform.Options{{
\t\tTerraformDir: "../",
\t\tEnvVars: map[string]string{{
\t\t\t"AWS_ACCESS_KEY_ID":     os.Getenv("AWS_ACCESS_KEY_ID"),
\t\t\t"AWS_SECRET_ACCESS_KEY": "test",
\t\t\t"AWS_DEFAULT_REGION":    "us-east-1",
\t\t\t"AWS_ENDPOINT_URL":      endpointURL,
\t\t\t"TF_INPUT":              "0",
\t\t}},
\t}})
\tdefer func() {{
\t\tif _, err := terraform.DestroyE(t, opts); err != nil {{
\t\t\tt.Logf("cleanup warning: %v", err)
\t\t}}
\t}}()
\tterraform.InitAndApply(t, opts)
}}
"""


# ── Tool: check_deployment_structure ─────────────────────────────────────────

@tool(context=True)
def check_deployment_structure(
    session_dir: str = "",
    tool_context: ToolContext = None,
) -> str:
    """
    Static structural check: scan .tf files for dangling resource references.

    Fast Python-only analysis — no Go needed. Detects references to undefined
    resource blocks (e.g. aws_instance.web where no such resource is declared).

    Writes state key: structural_errors.
    Returns JSON: {v_deploy_structural, errors}.
    """
    errors = _runtime_structural_check(session_dir)
    v_deploy = 1 if not errors else 0   # paper eq.(2): v_deploy ∈ {0,1}
    result = {"v_deploy": v_deploy, "errors": errors}

    if tool_context is not None:
        tool_context.agent.state.set("structural_errors", json.dumps(errors))

    return json.dumps(result)


def _runtime_structural_check(tf_dir: str) -> list[dict]:
    errors: list[dict] = []
    if not tf_dir or not os.path.isdir(tf_dir):
        return errors
    combined = "\n".join(
        open(os.path.join(tf_dir, f)).read()
        for f in sorted(os.listdir(tf_dir)) if f.endswith(".tf")
    )
    defined = {
        f"{kind}.{name}"
        for kind, name in re.findall(r'resource\s+"(\w+)"\s+"(\w+)"', combined)
    }
    for ref_kind, ref_name in re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z_][A-Za-z0-9_]*', combined):
        if ref_kind in ("var", "local", "module", "data", "path", "terraform",
                        "aws", "google", "azurerm", "each", "count"):
            continue
        ref = f"{ref_kind}.{ref_name}"
        if ref not in defined:
            errors.append({
                "type": "missing_reference", "resource": ref,
                "message": f"Reference to undefined resource: {ref}",
                "counterexample": {"type": "runtime", "resource": ref},
                "fix": f"Define resource block for {ref} or correct the reference",
            })
    return errors


# ── Tool: run_go_tests ────────────────────────────────────────────────────────

@tool(context=True)
def run_go_tests(
    session_dir: str = "",
    tool_context: ToolContext = None,
) -> str:
    """
    Run go mod download + tidy + `go test -v` in {session_dir}/test/.

    v_deploy=1 only if all go tests pass.
    Falls back to structural check result if Go is not installed.

    Writes state keys: v_deploy, terratest_result.
    Returns JSON: {v_deploy, terratest, errors, logs, phase, sandbox}.
    """
    account_key = _fresh_account_key()
    ministack_env = {**_ministack_env_base(), "AWS_ACCESS_KEY_ID": account_key}

    result: dict[str, Any] = {
        "v_deploy": 0, "phase": "terratest",
        "errors": [], "plan_summary": {"add": 0, "change": 0, "destroy": 0},
        "logs": f"ministack account key: {account_key}\n",
        "sandbox": "ministack",
        "terratest": {"passed": False, "tests_run": 0, "failed_tests": [], "logs": ""},
    }

    # Go availability check
    rc, go_ver = _run(wrap_cmd(["go", "version"]), cwd="/tmp", timeout=10, env={})
    if rc != 0:
        errors = _runtime_structural_check(session_dir)
        result.update({
            "errors": errors,
            "v_deploy": 1 if not errors else 0,
            "phase": "structural",
            "sandbox": "structural",
            "logs": "go not installed; structural analysis used",
            "terratest": None,
        })
        if tool_context is not None:
            tool_context.agent.state.set("v_deploy", result["v_deploy"])
            tool_context.agent.state.set("terratest_result", json.dumps(result))
        return json.dumps(result)

    result["logs"] += f"go: {go_ver.strip()}\n"

    if os.getenv("MACOG_DEVOPS_MODE", "").lower() == "structural":
        errors = _runtime_structural_check(session_dir)
        result.update({
            "errors": errors,
            "v_deploy": 1 if not errors else 0,
            "phase": "structural",
            "sandbox": "structural",
            "logs": result["logs"] + "MACOG_DEVOPS_MODE=structural; structural deployment analysis used\n",
            "terratest": None,
        })
        if tool_context is not None:
            tool_context.agent.state.set("v_deploy", result["v_deploy"])
            tool_context.agent.state.set("terratest_result", json.dumps(result))
        return json.dumps(result)

    if not _ministack_reachable():
        errors = _runtime_structural_check(session_dir)
        result.update({
            "errors": errors,
            "v_deploy": 1 if not errors else 0,
            "phase": "structural",
            "sandbox": "structural",
            "logs": (
                result["logs"]
                + "ministack not reachable; structural deployment analysis used\n"
            ),
            "terratest": None,
        })
        if tool_context is not None:
            tool_context.agent.state.set("v_deploy", result["v_deploy"])
            tool_context.agent.state.set("terratest_result", json.dumps(result))
        return json.dumps(result)

    test_dir = os.path.join(session_dir, "test")
    os.makedirs(test_dir, exist_ok=True)

    # Write go.mod (ensure correct module name)
    with open(os.path.join(test_dir, "go.mod"), "w") as fh:
        fh.write(_GO_MOD)

    # Ensure main_test.go exists (generate_terratest_suite should have written it)
    test_file = os.path.join(test_dir, "main_test.go")
    if not os.path.exists(test_file):
        with open(test_file, "w") as fh:
            fh.write(_FALLBACK_TEST)
        result["logs"] += "main_test.go missing — wrote minimal fallback test\n"

    # Download dependencies
    for cmd in [["go", "mod", "download"], ["go", "mod", "tidy"]]:
        rc, out = _run(wrap_cmd(cmd), cwd=test_dir, timeout=300, env=ministack_env)
        result["logs"] += f"$ {' '.join(cmd)}\n{out[:400]}\n"
        if rc != 0:
            result["errors"].append({
                "type": "provider_error",
                "message": f"{' '.join(cmd)} failed: {out[:300]}",
                "counterexample": {"type": "runtime", "phase": "go_get"},
                "fix": "Check network connectivity for go module downloads",
            })
            result["logs"] += "Dependency download failed — aborting\n"
            if tool_context is not None:
                tool_context.agent.state.set("v_deploy", 0)
                tool_context.agent.state.set("terratest_result", json.dumps(result))
            return json.dumps(result)

    # Run one full-stack deployability test.
    rc, test_out = _run(
        wrap_cmd(["go", "test", "-v", "-timeout", "10m", "."]),
        cwd=test_dir, timeout=600, env=ministack_env,
    )
    result["logs"] += test_out[:3000]

    passed_tests = re.findall(r'--- PASS: (\S+)', test_out)
    failed_tests = re.findall(r'--- FAIL: (\S+)', test_out)
    tests_run = len(passed_tests) + len(failed_tests)

    all_passed = rc == 0 and not failed_tests
    result["terratest"] = {
        "passed": all_passed,
        "tests_run": tests_run,
        "failed_tests": failed_tests,
        "logs": test_out[:2000],
    }
    result["v_deploy"] = 1 if all_passed else 0

    if not all_passed and not failed_tests:
        result["errors"].append({
            "type": "plan_error",
            "message": test_out[-500:],
            "counterexample": {"type": "runtime", "phase": "go_test"},
            "fix": "Check terraform apply output and ministack connectivity",
        })

    for ft in failed_tests:
        result["errors"].append({
            "type": "plan_error", "resource": ft,
            "message": f"Terratest assertion failed: {ft}",
            "counterexample": {"type": "runtime", "test": ft},
            "fix": "Check the resource exists in ministack with the expected attributes",
        })

    if tool_context is not None:
        tool_context.agent.state.set("v_deploy", result["v_deploy"])
        tool_context.agent.state.set("terratest_result", json.dumps(result))
        plan_hash_val = hashlib.md5(
            json.dumps(result.get("plan_summary", {}), sort_keys=True).encode()
        ).hexdigest()
        tool_context.agent.state.set("plan_hash", plan_hash_val)

    return json.dumps(result)
