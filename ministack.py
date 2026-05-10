"""
MiniStack lifecycle management for MACOG.

Usage:
  # Start and keep running (blocks):
  python ministack.py

  # As a context manager in code:
  from ministack import MiniStack
  with MiniStack() as endpoint:
      # endpoint == "http://localhost:4566" (or dynamic host:port)
      run_macog()
"""
from __future__ import annotations

import sys
import time

import requests
from testcontainers.core.container import DockerContainer

_IMAGE = "ministackorg/ministack:latest"
_PORT = 4566
_HEALTH_TIMEOUT = 60  # seconds


class MiniStack:
    """
    Starts a MiniStack container and waits until it is healthy.

    Attributes
    ----------
    endpoint : str
        The HTTP endpoint (e.g. "http://localhost:4566") once started.
    """

    def __init__(
        self,
        image: str = _IMAGE,
        port: int = _PORT,
        health_timeout: int = _HEALTH_TIMEOUT,
    ) -> None:
        self._image = image
        self._port = port
        self._health_timeout = health_timeout
        self._container: DockerContainer | None = None
        self.endpoint: str = ""

    # ── context-manager protocol ──────────────────────────────────────────────

    def __enter__(self) -> str:
        self.start()
        return self.endpoint

    def __exit__(self, *_) -> None:
        self.stop()

    # ── public API ────────────────────────────────────────────────────────────

    def start(self) -> str:
        """Start the container and return the endpoint URL."""
        print(f"[ministack] Pulling and starting {self._image} …", flush=True)
        self._container = (
            DockerContainer(self._image)
            .with_exposed_ports(self._port)
        )
        self._container.start()

        host = self._container.get_container_host_ip()
        port = self._container.get_exposed_port(self._port)
        self.endpoint = f"http://{host}:{port}"

        self._wait_healthy()
        return self.endpoint

    def stop(self) -> None:
        """Stop and remove the container."""
        if self._container is not None:
            print("[ministack] Stopping container …", flush=True)
            self._container.stop()
            self._container = None
            self.endpoint = ""

    # ── internals ─────────────────────────────────────────────────────────────

    def _wait_healthy(self) -> None:
        health_url = f"{self.endpoint}/_ministack/health"
        deadline = time.monotonic() + self._health_timeout
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            try:
                resp = requests.get(health_url, timeout=2)
                if resp.status_code == 200:
                    print(
                        f"[ministack] Ready at {self.endpoint} "
                        f"(attempt {attempt})",
                        flush=True,
                    )
                    return
            except requests.RequestException:
                pass
            time.sleep(0.5)

        raise RuntimeError(
            f"MiniStack did not become healthy within {self._health_timeout}s "
            f"({health_url})"
        )


# ── standalone entry point ────────────────────────────────────────────────────

def _run_macog_with_ministack() -> None:
    """Start MiniStack, run the MACOG pipeline, then stop."""
    import os
    import socket

    os.environ["BYPASS_TOOL_CONSENT"] = "true"

    # Force IPv4 (same fix as main.py)
    _orig = socket.getaddrinfo
    def _ipv4(host, port, family=0, type=0, proto=0, flags=0):
        results = _orig(host, port, family, type, proto, flags)
        ipv4 = [r for r in results if r[0] == socket.AF_INET]
        return ipv4 if ipv4 else results
    socket.getaddrinfo = _ipv4

    with MiniStack() as endpoint:
        # Expose endpoint to DevOps tools via env
        os.environ["AWS_ENDPOINT_URL"] = endpoint
        print(f"[ministack] AWS_ENDPOINT_URL={endpoint}", flush=True)

        from observability import setup_observability
        from macog import MACOGOrchestrator

        setup_observability(log_level="INFO")

        intent = """Deploy a 3-tier web application on AWS with the following requirements:
- VPC with public and private subnets across 2 availability zones
- Application Load Balancer in the public subnet
- EC2 instances (t3.medium) in private subnets for the application tier
- RDS PostgreSQL (db.t3.medium) in private subnets
- S3 bucket for static assets with server-side encryption
- Encryption at rest for RDS and S3
- Least-privilege IAM roles for EC2 instances
- Security groups with restricted ingress (no 0.0.0.0/0 on sensitive ports)
- NAT Gateway for outbound traffic from private subnets"""

        constraints = {
            "budget": 500,
            "regions": ["us-east-1"],
            "encryption_required": True,
            "availability": 99.9,
        }

        result = MACOGOrchestrator(max_iterations=5).run(
            intent=intent, constraints=constraints
        )

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
        print(
            f"\n  v_schema={validators.get('v_schema', 0)}  "
            f"v_policy={validators.get('v_policy', 0)}  "
            f"v_cost=${validators.get('v_cost', 0.0):.2f}  "
            f"v_deploy={validators.get('v_deploy', 0)}"
        )

        if hcl:
            print(f"\n{'─'*64}")
            print("  Generated Terraform HCL")
            print(f"{'─'*64}")
            preview = hcl[:3000]
            print(preview)
            if len(hcl) > 3000:
                print(f"\n  … ({len(hcl)} chars total, {len(hcl.splitlines())} lines)")


if __name__ == "__main__":
    _run_macog_with_ministack()
