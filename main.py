"""
MACOG entry point — Multi-Agent Code-Orchestrated Generation for IaC
Paper: "Multi-Agent Code-Orchestrated Generation for Reliable Infrastructure-as-Code"
       Khan et al., Virginia Tech, 2025 (arXiv:2510.03902)
"""
import os
import socket

os.environ["BYPASS_TOOL_CONSENT"] = "true"  # allow strands_tools.file_write without TTY prompt

# Force IPv4 for all outbound connections — NAT64/IPv6 causes TLS hangs on api.deepseek.com
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_preferred_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    results = _orig_getaddrinfo(host, port, family, type, proto, flags)
    ipv4 = [r for r in results if r[0] == socket.AF_INET]
    return ipv4 if ipv4 else results
socket.getaddrinfo = _ipv4_preferred_getaddrinfo

from observability import setup_observability
from macog import MACOGOrchestrator


def main() -> None:
    # Set log_level="DEBUG" for full tool-registration + event-loop detail.
    # Pass otlp_endpoint="http://localhost:4318" to send traces to Jaeger.
    setup_observability(log_level="INFO")

    intent = """Create a single S3 bucket on AWS with server-side encryption enabled."""

    constraints = {
        "budget": 50,
        "regions": ["us-east-1"],
        "encryption_required": True,
    }

    result = MACOGOrchestrator(max_iterations=5).run(intent=intent, constraints=constraints)

    state = result["state"]
    iterations = result["iterations"]
    final_score = result["final_score"]
    evidence = result.get("evidence", {})
    validators = evidence.get("final_validators", {})
    hcl = result.get("hcl", "")

    print("\n" + "=" * 64)
    print(f"  MACOG Result : {state.upper()}")
    print(f"  Iterations   : {iterations}")
    print(f"  Routing score: {final_score:.4f}  (0 = fully feasible)")
    print("=" * 64)

    print(f"\n  v_schema={validators.get('v_schema', 0)}  "
          f"v_policy={validators.get('v_policy', 0)}  "
          f"v_cost=${validators.get('v_cost', 0.0):.2f}  "
          f"v_deploy={validators.get('v_deploy', 0)}")

    if hcl:
        print(f"\n{'─'*64}")
        print("  Generated Terraform HCL")
        print(f"{'─'*64}")
        preview = hcl[:3000]
        print(preview)
        if len(hcl) > 3000:
            print(f"\n  … ({len(hcl)} chars total, {len(hcl.splitlines())} lines)")


if __name__ == "__main__":
    main()
