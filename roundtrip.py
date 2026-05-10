"""
Round-trip and provenance helpers for MACOG.

The paper requires compiled Terraform to be parsed back into a structural
artifact and checked against the harmonized I-IR before dynamic validators run.
This module implements a deterministic, dependency-light approximation of that
contract: resource identity coverage, dependency-reference coverage, graph
acyclicity, content hashes, and local toolchain digests.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RoundTripResult:
    passed: bool
    parsed_resources: list[dict[str, str]] = field(default_factory=list)
    missing_resources: list[str] = field(default_factory=list)
    extra_resources: list[str] = field(default_factory=list)
    missing_edges: list[str] = field(default_factory=list)
    dangling_references: list[str] = field(default_factory=list)
    cycles: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "parsed_resources": self.parsed_resources,
            "missing_resources": self.missing_resources,
            "extra_resources": self.extra_resources,
            "missing_edges": self.missing_edges,
            "dangling_references": self.dangling_references,
            "cycles": self.cycles,
            "notes": self.notes,
        }


def parse_hcl_structure(hcl: str) -> dict[str, Any]:
    resources = [
        {"kind": kind, "id": name, "address": f"{kind}.{name}"}
        for kind, name in re.findall(r'resource\s+"([A-Za-z0-9_]+)"\s+"([A-Za-z0-9_]+)"', hcl)
    ]
    defined = {r["address"] for r in resources}
    references = _references_in(hcl)

    dependencies: list[dict[str, str]] = []
    for block_kind, block_name, block_body in _resource_blocks(hcl):
        target = f"{block_kind}.{block_name}"
        for source in _references_in(block_body):
            if source != target:
                dependencies.append({"source": source, "target": target})

    return {
        "resources": resources,
        "defined": defined,
        "references": references,
        "dependencies": dependencies,
    }


def check_roundtrip(plan: dict | None, hcl: str) -> RoundTripResult:
    plan = plan or {}
    parsed = parse_hcl_structure(hcl)
    expected = {
        f"{r.get('kind')}.{r.get('id')}"
        for r in plan.get("resources", [])
        if r.get("kind") and r.get("id")
    }
    actual = set(parsed["defined"])
    dangling = sorted(ref for ref in parsed["references"] if ref not in actual)

    edges_by_id = []
    id_to_addr = {
        r.get("id"): f"{r.get('kind')}.{r.get('id')}"
        for r in plan.get("resources", [])
        if r.get("kind") and r.get("id")
    }
    actual_edges = {(d["source"], d["target"]) for d in parsed["dependencies"]}
    for edge in plan.get("edges", []):
        src = id_to_addr.get(edge.get("source"))
        tgt = id_to_addr.get(edge.get("target"))
        if src and tgt:
            edges_by_id.append((src, tgt, edge.get("type", "depends")))

    missing_edges = [
        f"{src}->{tgt} ({kind})"
        for src, tgt, kind in edges_by_id
        if kind == "depends"
        and (src, tgt) not in actual_edges
        and (tgt, src) not in actual_edges
    ]
    cycles = _find_cycles(list(actual_edges))
    missing_resources = sorted(expected - actual)
    extra_resources = sorted(actual - expected)
    passed = not missing_resources and not missing_edges and not dangling and not cycles
    notes = []
    if extra_resources:
        notes.append("extra resources are tolerated as benign compiler expansion")
    return RoundTripResult(
        passed=passed,
        parsed_resources=parsed["resources"],
        missing_resources=missing_resources,
        extra_resources=extra_resources,
        missing_edges=missing_edges,
        dangling_references=dangling,
        cycles=cycles,
        notes=notes,
    )


def content_hashes(session_dir: str, plan: dict | None, hcl: str) -> dict[str, str]:
    hashes = {
        "plan_sha256": _sha256_json(plan or {}),
        "hcl_sha256": _sha256_text(hcl),
    }
    if session_dir and os.path.isdir(session_dir):
        for root, _, files in os.walk(session_dir):
            for fname in sorted(files):
                if not fname.endswith((".tf", ".rego", ".go", ".mod", ".json")):
                    continue
                path = os.path.join(root, fname)
                rel = os.path.relpath(path, session_dir)
                try:
                    with open(path, "rb") as fh:
                        hashes[f"file:{rel}"] = hashlib.sha256(fh.read()).hexdigest()
                except OSError:
                    continue
    return hashes


def toolchain_digests() -> dict[str, str]:
    tools = {
        "terraform": ["terraform", "version", "-json"],
        "tflint": ["tflint", "--version"],
        "conftest": ["conftest", "--version"],
        "infracost": ["infracost", "--version"],
        "go": ["go", "version"],
    }
    return {name: _tool_digest(cmd) for name, cmd in tools.items()}


def _resource_blocks(hcl: str) -> list[tuple[str, str, str]]:
    matches: list[tuple[str, str, str]] = []
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
        matches.append((match.group(1), match.group(2), hcl[start : i - 1]))
    return matches


def _references_in(hcl: str) -> set[str]:
    ignored = {
        "var", "local", "module", "data", "path", "terraform", "provider",
        "each", "count", "aws", "google", "azurerm",
    }
    refs: set[str] = set()
    for ref_kind, ref_name in re.findall(
        r"\b([A-Za-z][A-Za-z0-9_]*)\.([A-Za-z0-9_]+)(?:\.[A-Za-z0-9_]+)?",
        hcl,
    ):
        if ref_kind in ignored:
            continue
        refs.add(f"{ref_kind}.{ref_name}")
    return refs


def _find_cycles(edges: list[tuple[str, str]]) -> list[str]:
    graph: dict[str, list[str]] = {}
    for src, tgt in edges:
        graph.setdefault(src, []).append(tgt)
    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: list[str] = []

    def visit(node: str, stack: list[str]) -> None:
        if node in visiting:
            idx = stack.index(node) if node in stack else 0
            cycles.append(" -> ".join(stack[idx:] + [node]))
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for nxt in graph.get(node, []):
            visit(nxt, stack)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node, [])
    return cycles


def _sha256_json(value: dict) -> str:
    return _sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _tool_digest(cmd: list[str]) -> str:
    if shutil.which(cmd[0]) is None:
        return "unavailable"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"error:{type(exc).__name__}"
    raw = (proc.stdout or proc.stderr).strip()
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            if "terraform_version" in parsed:
                return f"Terraform v{parsed['terraform_version']}"
        except json.JSONDecodeError:
            pass
    out = raw.splitlines()
    return out[0][:200] if out else f"exit:{proc.returncode}"
