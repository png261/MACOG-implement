"""
Small MACOG smoke runner.

Use this before larger IaC-Eval runs. It sends a deliberately tiny intent
through the full Strands MACOG pipeline with a low repair budget.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a tiny MACOG smoke query.")
    parser.add_argument(
        "--local-fixture",
        action="store_true",
        help="Run deterministic no-model checks against a tiny encrypted S3 fixture.",
    )
    parser.add_argument(
        "--intent",
        default="Create one AWS S3 bucket with server-side encryption.",
        help="Infrastructure intent to test.",
    )
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument("--budget", type=float, default=25.0)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--backend",
        choices=["openrouter", "deepseek", "claude", "custom"],
        default=None,
        help="Override MACOG_MODEL_BACKEND for the live Strands smoke.",
    )
    parser.add_argument(
        "--model-id",
        default=None,
        help="Override backend model id for live smoke (CUSTOM_MODEL_ID, OPENROUTER_MODEL, or CLAUDE_MODEL_ID).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override CUSTOM_BASE_URL for custom OpenAI-compatible backend.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Live smoke timeout in seconds. Ignored for --local-fixture.",
    )
    parser.add_argument(
        "--deploy-mode",
        choices=["structural", "sandbox"],
        default="structural",
        help="DevOps validator mode for live smoke. Use sandbox for Terratest/MiniStack.",
    )
    args = parser.parse_args()

    if args.local_fixture:
        print(json.dumps(_run_local_fixture(args.budget, args.region), indent=2, sort_keys=True))
        return

    if os.getenv("MACOG_SMOKE_CHILD") != "1":
        env = os.environ.copy()
        env["MACOG_SMOKE_CHILD"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        cmd = [sys.executable, "-u", str(Path(__file__).resolve()), *sys.argv[1:]]
        proc = subprocess.Popen(
            cmd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )
        try:
            stdout, stderr = proc.communicate(timeout=args.timeout)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                stdout, stderr = proc.communicate()
            if stdout:
                print(stdout, end="")
            if stderr:
                print(stderr, end="", file=sys.stderr)
            print(json.dumps({
                "state": "error",
                "phase": "live_strands_pipeline",
                "error_type": "TimeoutExpired",
                "error": f"Live MACOG smoke exceeded {args.timeout}s",
                "hint": "Run --local-fixture for deterministic validators or increase --timeout for live model/toolchain checks.",
            }, indent=2, sort_keys=True))
            raise SystemExit(124)
        if stdout:
            print(stdout, end="")
        if stderr:
            print(stderr, end="", file=sys.stderr)
        raise SystemExit(proc.returncode)

    if args.backend:
        os.environ["MACOG_MODEL_BACKEND"] = args.backend
    if args.deploy_mode == "structural":
        os.environ["MACOG_DEVOPS_MODE"] = "structural"
    else:
        os.environ.pop("MACOG_DEVOPS_MODE", None)
    if args.model_id:
        if args.backend == "openrouter":
            os.environ["OPENROUTER_MODEL"] = args.model_id
        elif args.backend == "claude":
            os.environ["CLAUDE_MODEL_ID"] = args.model_id
        else:
            os.environ["CUSTOM_MODEL_ID"] = args.model_id
    if args.base_url:
        os.environ["CUSTOM_BASE_URL"] = args.base_url
    from observability import setup_observability
    from macog import MACOGOrchestrator

    setup_observability(log_level="WARNING")
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(args.timeout)
    try:
        result = MACOGOrchestrator(max_iterations=args.max_iterations).run(
            intent=args.intent,
            constraints={
                "budget": args.budget,
                "regions": [args.region],
                "encryption_required": True,
            },
        )
    except Exception as exc:
        print(json.dumps({
            "state": "error",
            "phase": "live_strands_pipeline",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "hint": "Retry later or run --local-fixture to test deterministic validators first.",
        }, indent=2, sort_keys=True))
        raise SystemExit(1)
    finally:
        signal.alarm(0)
    validators = result.get("evidence", {}).get("final_validators", {})
    summary = {
        "state": result.get("state"),
        "iterations": result.get("iterations"),
        "final_score": result.get("final_score"),
        "validators": validators,
        "session_dir": result.get("session_dir"),
        "hcl_lines": len((result.get("hcl") or "").splitlines()),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


def _run_local_fixture(budget: float, region: str) -> dict:
    from agents.cost_capacity.tools import estimate_cost_from_catalog
    from agents.devops.tools import check_deployment_structure
    from agents.reviewer.tools import _macog_contract_check, _structural_check
    from agents.security_prover.tools import (
        run_access_check,
        run_encryption_check,
        run_governance_check,
        run_network_check,
        run_scanner_check,
    )
    from roundtrip import check_roundtrip, content_hashes, toolchain_digests

    session_dir = tempfile.mkdtemp(prefix="macog_local_smoke_")
    hcl = f'''terraform {{
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }}
  }}
}}

provider "aws" {{
  region = "{region}"
}}

resource "aws_s3_bucket" "bucket" {{
  bucket = "macog-local-smoke-bucket"
  tags = {{
    Name        = "macog-local-smoke-bucket"
    Environment = "test"
  }}
}}

resource "aws_s3_bucket_server_side_encryption_configuration" "bucket_sse" {{
  bucket = aws_s3_bucket.bucket.id

  rule {{
    apply_server_side_encryption_by_default {{
      sse_algorithm = "AES256"
    }}
  }}
}}
'''
    Path(session_dir, "main.tf").write_text(hcl)
    plan = {
        "resources": [
            {
                "id": "bucket",
                "kind": "aws_s3_bucket",
                "provider": "aws",
                "region": region,
                "fields": {"bucket": "macog-local-smoke-bucket"},
                "effects": ["encrypt_at_rest", "tag_required"],
            },
            {
                "id": "bucket_sse",
                "kind": "aws_s3_bucket_server_side_encryption_configuration",
                "provider": "aws",
                "region": region,
                "fields": {"bucket": "aws_s3_bucket.bucket.id"},
                "effects": ["encrypt_at_rest"],
            },
        ],
        "edges": [
            {
                "type": "depends",
                "source": "bucket",
                "target": "bucket_sse",
            }
        ],
        "provider_versions": {"aws": "~> 5.0"},
    }

    structural_ok, structural_errors = _structural_check(hcl)
    contract_errors = _macog_contract_check(hcl)
    encryption = json.loads(run_encryption_check(session_dir=session_dir))
    network = json.loads(run_network_check(session_dir=session_dir))
    access = json.loads(run_access_check(session_dir=session_dir))
    governance = json.loads(run_governance_check(
        session_dir=session_dir,
        constraints_json=json.dumps({"regions": [region]}),
    ))
    scanner = json.loads(run_scanner_check(session_dir=session_dir))
    cost = json.loads(estimate_cost_from_catalog(session_dir=session_dir, budget=budget))
    deploy = json.loads(check_deployment_structure(session_dir=session_dir))
    roundtrip = check_roundtrip(plan, hcl).to_dict()

    all_policy_violations = (
        encryption.get("violations", [])
        + network.get("violations", [])
        + access.get("violations", [])
        + governance.get("violations", [])
        + scanner.get("violations", [])
    )
    v_policy = 0 if any(
        v.get("severity") in ("critical", "high") for v in all_policy_violations
    ) else 1
    v_schema = 1 if structural_ok and not contract_errors and roundtrip["passed"] else 0
    v_deploy = deploy.get("v_deploy", 0)
    v_cost = cost.get("v_cost", 0.0)
    final_score = (1 - v_schema) + (1 - v_policy) + max(0, v_cost - budget) * 0.001 + (1 - v_deploy)

    return {
        "state": "done" if final_score == 0 else "failed",
        "mode": "local_fixture_no_model",
        "session_dir": session_dir,
        "validators": {
            "v_schema": v_schema,
            "v_policy": v_policy,
            "v_cost": v_cost,
            "v_deploy": v_deploy,
            "routing_score": final_score,
        },
        "structural_errors": structural_errors,
        "contract_errors": contract_errors,
        "policy": {
            "encryption": encryption,
            "network": network,
            "access": access,
            "governance": governance,
            "scanner": scanner,
        },
        "cost": cost,
        "deploy": deploy,
        "roundtrip": roundtrip,
        "provenance": {
            "content_hashes": content_hashes(session_dir, plan, hcl),
            "toolchain": toolchain_digests(),
        },
        "hcl_lines": len(hcl.splitlines()),
    }


def _timeout_handler(signum, frame) -> None:
    raise TimeoutError("Live MACOG smoke timed out")


if __name__ == "__main__":
    main()
