"""
Session-manager helpers for MACOG agents and multi-agent graphs.

Strands multi-agent sessions belong at the orchestrator/graph boundary. The
specialist agents themselves intentionally stay session-manager-free so they can
be used safely inside Graph/Swarm style multi-agent systems.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from strands.session.file_session_manager import FileSessionManager

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SESSION_STORAGE_DIR = PROJECT_ROOT / ".macog_sessions"
_SAFE_SESSION_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


def _load_env_file(path: Path | None = None) -> None:
    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def normalize_session_id(value: str) -> str:
    normalized = _SAFE_SESSION_CHARS.sub("-", value.strip()).strip("-")
    return normalized or f"macog-{uuid.uuid4().hex[:12]}"


def default_session_id(scope: str = "orchestrator") -> str:
    _load_env_file()
    configured = os.getenv("MACOG_SESSION_ID")
    if configured:
        return normalize_session_id(f"{configured}-{scope}")
    return normalize_session_id(f"macog-{scope}-{uuid.uuid4().hex[:12]}")


def session_storage_dir() -> str:
    _load_env_file()
    return os.getenv("MACOG_SESSION_STORAGE_DIR", str(DEFAULT_SESSION_STORAGE_DIR))


def get_session_manager(
    scope: str = "orchestrator",
    session_id: str | None = None,
    storage_dir: str | None = None,
) -> FileSessionManager:
    return FileSessionManager(
        session_id=normalize_session_id(session_id or default_session_id(scope)),
        storage_dir=storage_dir or session_storage_dir(),
    )
