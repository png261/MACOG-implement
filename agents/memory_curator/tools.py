"""
Memory tools — verified I-IR motif store.

This module owns the in-process memory store.  Architect and Engineer agents
import retrieve_memory_motifs from here.  Memory Curator also imports
store_memory_motif from here.

In production: replace _memory_store with a dense vector index over I-IR motifs.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from strands import tool

_STORE_PATH = Path(os.getenv("MACOG_MEMORY_STORE", ".macog_memory/motifs.json"))
_memory_store: list[dict] = []


def _load_store() -> None:
    global _memory_store
    if _memory_store or not _STORE_PATH.exists():
        return
    try:
        _memory_store = json.loads(_STORE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        _memory_store = []


def _save_store() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(_memory_store, indent=2, sort_keys=True))


def _resource_kinds(fragment: dict) -> set[str]:
    resources = fragment.get("resources", fragment.get("nodes", []))
    return {
        str(r.get("kind", r.get("resource_type", r.get("type", ""))))
        for r in resources
        if r.get("kind") or r.get("resource_type") or r.get("type")
    }


def _fingerprint(fragment: dict) -> str:
    kinds = sorted(_resource_kinds(fragment))
    edges = fragment.get("edges", [])
    shape = {
        "kinds": kinds,
        "edge_count": len(edges) if isinstance(edges, list) else 0,
    }
    return json.dumps(shape, sort_keys=True)


@tool
def retrieve_memory_motifs(intent: str, constraints_json: str = "{}") -> str:
    """
    Retrieve previously verified I-IR motifs from memory that are structurally
    relevant to the intent and constraints. Returns top-3 matches as JSON.
    """
    _load_store()
    if not _memory_store:
        return json.dumps({"motifs": [], "total": 0})

    constraints: dict = json.loads(constraints_json) if constraints_json else {}
    intent_words = set(intent.lower().split())
    scored: list[tuple[float, dict]] = []

    for motif in _memory_store:
        desc_words = set(motif.get("description", "").lower().split())
        score = len(intent_words & desc_words) / max(len(intent_words), 1)
        motif_constraints = set(motif.get("constraints_satisfied", []))
        constraint_keys = set(str(k) for k in constraints)
        score += 0.2 * len(motif_constraints & constraint_keys)
        for kind in motif.get("resource_kinds", []):
            if kind.replace("_", " ") in intent.lower() or kind in intent.lower():
                score += 0.25
        scored.append((score, motif))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [m for s, m in scored[:3] if s > 0]

    return json.dumps({"motifs": top, "total": len(top)})


@tool
def store_memory_motif(motif_json: str) -> str:
    """
    Store a verified I-IR motif in the shared memory catalog.
    motif_json: JSON object with id, description, ir_fragment, hcl_fragment,
                constraints_satisfied, provider, version fields.
    Returns confirmation JSON.
    """
    try:
        _load_store()
        motif: dict = json.loads(motif_json)
        if "id" not in motif:
            motif["id"] = str(uuid.uuid4())
        fragment = motif.get("ir_fragment") or motif.get("plan") or {}
        if isinstance(fragment, dict):
            motif["resource_kinds"] = sorted(_resource_kinds(fragment))
            motif["graph_fingerprint"] = _fingerprint(fragment)
        existing_descs = {m.get("description") for m in _memory_store}
        if motif.get("description") not in existing_descs:
            _memory_store.append(motif)
            _save_store()
        return json.dumps({"stored": True, "id": motif["id"], "total": len(_memory_store)})
    except (json.JSONDecodeError, KeyError) as exc:
        return json.dumps({"stored": False, "error": str(exc)})
