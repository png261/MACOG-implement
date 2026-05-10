"""
MACOG Observability — Strands logging + OpenTelemetry tracing.

Call setup_observability() once at startup (before any agents are created).

Usage:
    # Logging only (always works)
    setup_observability()

    # Logging + console trace spans
    setup_observability(console_traces=True)

    # Logging + Jaeger UI (run Jaeger first — see below)
    setup_observability(otlp_endpoint="http://localhost:4318")

Start Jaeger locally:
    docker run -d --name jaeger \\
      -e COLLECTOR_OTLP_ENABLED=true \\
      -p 16686:16686 -p 4317:4317 -p 4318:4318 \\
      jaegertracing/all-in-one:latest
    # View traces at http://localhost:16686
"""
from __future__ import annotations

import logging
import os


def setup_observability(
    log_level: str = "INFO",
    otlp_endpoint: str | None = None,
    console_traces: bool = False,
) -> None:
    """
    Configure Strands SDK logging and (optionally) OpenTelemetry tracing.

    Args:
        log_level:      Log level for the 'strands' SDK logger.
                        Use "DEBUG" for full tool-registration and event-loop detail.
        otlp_endpoint:  OTLP HTTP endpoint for Jaeger / any OTel collector.
                        Falls back to OTEL_EXPORTER_OTLP_ENDPOINT env var.
        console_traces: Print raw OTEL span dicts to stdout (verbose).
    """
    # ── 1. Logging ────────────────────────────────────────────────────────────
    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  |  %(message)s",
        datefmt="%H:%M:%S",
    )
    handler = logging.StreamHandler()
    handler.setFormatter(fmt)

    # Strands SDK internals (tool registry, event loop, model calls)
    strands_logger = logging.getLogger("strands")
    strands_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    if not strands_logger.handlers:
        strands_logger.addHandler(handler)
        strands_logger.propagate = False

    # ── 2. OpenTelemetry tracing ──────────────────────────────────────────────
    endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    try:
        from strands.telemetry import StrandsTelemetry  # type: ignore[import]

        telemetry = StrandsTelemetry()

        if endpoint:
            os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
            telemetry.setup_otlp_exporter()
            print(f"[observability] OTLP traces  →  {endpoint}  (view at Jaeger :16686)")

        if console_traces:
            telemetry.setup_console_exporter()
            print("[observability] Console trace exporter enabled")

        if endpoint or console_traces:
            telemetry.setup_meter(
                enable_console_exporter=console_traces,
                enable_otlp_exporter=bool(endpoint),
            )
            print("[observability] Metrics exporter configured")

    except ImportError:
        print(
            "[observability] strands-agents[otel] not installed — tracing disabled.\n"
            "  Install: pip install 'strands-agents[otel]'"
        )
