"""
Infrastructure Intermediate Representation (I-IR) — MACOG §4.3

A typed resource graph P = (V, E, S) where:
  V  — resource nodes  n = ⟨kind, fields, provider, region, effects⟩
  E  — dependency / connectivity edges
  S  — specifications: quantitative constraints, region rules, security obligations
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResourceNode:
    id: str
    kind: str           # Terraform resource type, e.g. aws_vpc
    provider: str       # aws | google | azurerm
    region: str
    fields: dict[str, Any] = field(default_factory=dict)
    effects: list[str] = field(default_factory=list)
    # effects ⊆ {encrypt_at_rest, least_privilege, restricted_ingress,
    #             tag_required, residency_eu, encrypt_in_transit}


@dataclass
class Edge:
    type: str       # depends | connects
    source: str     # resource id
    target: str     # resource id
    proto: str | None = None    # tcp / udp / https …
    port: int | None = None


@dataclass
class Specs:
    budget: float = float("inf")    # monthly USD ceiling B
    regions: list[str] = field(default_factory=list)
    encryption_required: bool = False
    availability: float = 0.0       # % SLO, e.g. 99.9
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class IIRPlan:
    resources: list[ResourceNode] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    specs: Specs = field(default_factory=Specs)
    invariants: list[str] = field(default_factory=list)
    version: int = 0

    # ── Serialisation ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        budget = self.specs.budget
        return {
            "resources": [
                {
                    "id": r.id,
                    "kind": r.kind,
                    "provider": r.provider,
                    "region": r.region,
                    "fields": r.fields,
                    "effects": r.effects,
                }
                for r in self.resources
            ],
            "edges": [
                {
                    "type": e.type,
                    "source": e.source,
                    "target": e.target,
                    "proto": e.proto,
                    "port": e.port,
                }
                for e in self.edges
            ],
            "specs": {
                "budget": None if budget == float("inf") else budget,
                "regions": self.specs.regions,
                "encryption_required": self.specs.encryption_required,
                "availability": self.specs.availability,
                "extra": self.specs.extra,
            },
            "invariants": self.invariants,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> IIRPlan:
        resources = [
            ResourceNode(
                id=r["id"],
                kind=r["kind"],
                provider=r["provider"],
                region=r["region"],
                fields=r.get("fields", {}),
                effects=r.get("effects", []),
            )
            for r in data.get("resources", [])
        ]
        edges = [
            Edge(
                type=e["type"],
                source=e["source"],
                target=e["target"],
                proto=e.get("proto"),
                port=e.get("port"),
            )
            for e in data.get("edges", [])
        ]
        s = data.get("specs", {})
        raw_budget = s.get("budget")
        specs = Specs(
            budget=float("inf") if raw_budget is None else float(raw_budget),
            regions=s.get("regions", []),
            encryption_required=s.get("encryption_required", False),
            availability=s.get("availability", 0.0),
            extra=s.get("extra", {}),
        )
        return cls(
            resources=resources,
            edges=edges,
            specs=specs,
            invariants=data.get("invariants", []),
            version=data.get("version", 0),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
