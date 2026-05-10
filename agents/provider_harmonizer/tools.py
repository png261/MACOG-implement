"""
Tools available to the Provider Harmonizer agent.

The OpenTofu registry MCP endpoint is SSE-based. Keep MCP sessions
short-lived so a closed stream cannot be reused across later tool calls.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Literal

import json
import os

from mcp.client.sse import sse_client
from strands import tool, ToolContext
from strands.tools.mcp import MCPClient


OPENTOFU_MCP_URL = "https://mcp.opentofu.org/sse"


def _new_opentofu_client() -> MCPClient:
    return MCPClient(
        lambda: sse_client(
            OPENTOFU_MCP_URL,
            timeout=30,
            sse_read_timeout=60,
        ),
        startup_timeout=30,
    )


def _call_opentofu_tool(name: str, arguments: dict[str, Any]) -> str:
    tool_use_id = f"{name}-{uuid.uuid4()}"
    client = _new_opentofu_client()

    with client:
        result = client.call_tool_sync(tool_use_id, name, arguments)

    if result.get("status") != "success":
        return json.dumps(result, indent=2)

    content = result.get("content", [])
    text_blocks = [
        block["text"]
        for block in content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ]
    return "\n\n".join(text_blocks) if text_blocks else json.dumps(result, indent=2)


@tool(name="search-opentofu-registry")
def opentofu_search_registry(
    query: str,
    type: Literal["provider", "module", "resource", "data-source", "all"] = "all",
) -> str:
    """
    Search the OpenTofu Registry for providers, modules, resources, and data sources.

    Args:
        query: Search query, such as "aws", "database", or "s3".
        type: Registry item type to search for.
    """
    return _call_opentofu_tool(
        "search-opentofu-registry",
        {"query": query, "type": type},
    )


@tool(name="get-provider-details")
def opentofu_get_provider_details(namespace: str, name: str) -> str:
    """
    Get detailed information about a provider.

    Args:
        namespace: Provider namespace, such as "hashicorp".
        name: Provider name without terraform-provider- prefix, such as "aws".
    """
    return _call_opentofu_tool(
        "get-provider-details",
        {"namespace": namespace, "name": name},
    )


@tool(name="get-resource-docs")
def opentofu_get_resource_docs(
    namespace: str,
    name: str,
    resource: str,
    version: str | None = None,
) -> str:
    """
    Get documentation for a provider resource.

    Args:
        namespace: Provider namespace, such as "hashicorp".
        name: Provider name without terraform-provider- prefix, such as "aws".
        resource: Resource name without provider prefix, such as "s3_bucket".
        version: Optional provider version, such as "v5.100.0".
    """
    arguments = {"namespace": namespace, "name": name, "resource": resource}
    if version:
        arguments["version"] = version
    return _call_opentofu_tool("get-resource-docs", arguments)


@tool(name="get-datasource-docs")
def opentofu_get_datasource_docs(
    namespace: str,
    name: str,
    dataSource: str,
    version: str | None = None,
) -> str:
    """
    Get documentation for a provider data source.

    Args:
        namespace: Provider namespace, such as "hashicorp".
        name: Provider name without terraform-provider- prefix, such as "aws".
        dataSource: Data source name without provider prefix, such as "ami".
        version: Optional provider version, such as "v5.100.0".
    """
    arguments = {"namespace": namespace, "name": name, "dataSource": dataSource}
    if version:
        arguments["version"] = version
    return _call_opentofu_tool("get-datasource-docs", arguments)


@tool(context=True)
def write_harmonized_plan(plan_json: str, tool_context: ToolContext) -> str:
    """Write the harmonized I-IR plan P1 to {session_dir}/ir/plan_p1.json."""
    session_dir = tool_context.agent.state.get("session_dir") or ""
    ir_dir = os.path.join(session_dir, "ir")
    os.makedirs(ir_dir, exist_ok=True)
    path = os.path.join(ir_dir, "plan_p1.json")
    with open(path, "w") as f:
        f.write(plan_json)
    return json.dumps({"written": True, "path": path})


__all__ = [
    "opentofu_search_registry",
    "opentofu_get_provider_details",
    "opentofu_get_resource_docs",
    "opentofu_get_datasource_docs",
    "write_harmonized_plan",
]
