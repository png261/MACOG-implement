"""
Tools available to the Engineer agent.

file_write  — project-local noninteractive writer; persists generated HCL
              inside session_dir so downstream validators can operate directly
              on filesystem files.
editor      — built-in strands_tools tool; used for targeted HCL edits during
              repair cycles without rewriting the whole file.
retrieve_memory_motifs — re-exported from Memory Curator for seeding HCL
              fragments from the verified motif store.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from strands import ToolContext, tool
from agents.memory_curator.tools import retrieve_memory_motifs  # noqa: F401


@tool(context=True, name="file_write")
def safe_file_write(path: str, content: str, tool_context: ToolContext = None) -> str:
    """
    Write generated Terraform files without interactive prompts.

    The Engineer may pass either an absolute path under its session directory or
    a relative path such as main.tf. Writes outside session_dir are rejected.
    """
    session_dir = ""
    if tool_context is not None:
        session_dir = tool_context.agent.state.get("session_dir") or ""
    if not session_dir:
        return json.dumps({"written": False, "error": "session_dir is not set"})

    session_root = Path(session_dir).resolve()
    raw_path = Path(path).expanduser()
    target = raw_path if raw_path.is_absolute() else session_root / raw_path
    target = target.resolve()

    try:
        target.relative_to(session_root)
    except ValueError:
        return json.dumps({
            "written": False,
            "error": f"Refusing to write outside session_dir: {target}",
        })

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    if tool_context is not None:
        files = tool_context.agent.state.get("files_written") or []
        if str(target) not in files:
            files.append(str(target))
        tool_context.agent.state.set("files_written", files)
    return json.dumps({"written": True, "path": str(target), "bytes": len(content.encode())})


file_write = safe_file_write


@tool(context=True, name="editor")
def safe_editor(
    command: str,
    path: str,
    file_text: str | None = None,
    insert_line: str | int | None = None,
    new_str: str | None = None,
    old_str: str | None = None,
    pattern: str | None = None,
    search_text: str | None = None,
    fuzzy: bool = False,
    view_range: list[int] | None = None,
    tool_context: ToolContext = None,
) -> str:
    """
    Noninteractive session-scoped editor for Engineer repair loops.

    Supports the subset MACOG asks Engineer to use: view, create, str_replace,
    insert, and find_line. Writes outside session_dir are rejected.
    """
    session_dir = ""
    if tool_context is not None:
        session_dir = tool_context.agent.state.get("session_dir") or ""
    if not session_dir:
        return json.dumps({"status": "error", "error": "session_dir is not set"})

    session_root = Path(session_dir).resolve()
    raw_path = Path(path).expanduser()
    target = raw_path if raw_path.is_absolute() else session_root / raw_path
    target = target.resolve()
    try:
        target.relative_to(session_root)
    except ValueError:
        return json.dumps({
            "status": "error",
            "error": f"Refusing to edit outside session_dir: {target}",
        })

    if command == "view":
        if not target.exists():
            return json.dumps({"status": "error", "error": f"File not found: {target}"})
        text = target.read_text()
        if view_range and len(view_range) == 2:
            lines = text.splitlines()
            start = max(view_range[0] - 1, 0)
            end = min(view_range[1], len(lines))
            text = "\n".join(lines[start:end])
        return json.dumps({"status": "success", "path": str(target), "content": text})

    if command == "create":
        if file_text is None:
            return json.dumps({"status": "error", "error": "file_text is required"})
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file_text)
        return json.dumps({"status": "success", "path": str(target), "created": True})

    if command == "str_replace":
        if old_str is None or new_str is None:
            return json.dumps({"status": "error", "error": "old_str and new_str are required"})
        if not target.exists():
            return json.dumps({"status": "error", "error": f"File not found: {target}"})
        text = target.read_text()
        count = text.count(old_str)
        if count == 0:
            return json.dumps({"status": "error", "error": "old_str not found"})
        target.write_text(text.replace(old_str, new_str))
        return json.dumps({"status": "success", "path": str(target), "replacements": count})

    if command == "insert":
        if insert_line is None or new_str is None:
            return json.dumps({"status": "error", "error": "insert_line and new_str are required"})
        if not target.exists():
            return json.dumps({"status": "error", "error": f"File not found: {target}"})
        lines = target.read_text().splitlines()
        if isinstance(insert_line, int):
            idx = max(min(insert_line, len(lines)), 0)
        else:
            matches = [i for i, line in enumerate(lines) if insert_line in line]
            if not matches:
                return json.dumps({"status": "error", "error": "insert_line text not found"})
            idx = matches[0] + 1
        lines[idx:idx] = new_str.splitlines()
        target.write_text("\n".join(lines) + "\n")
        return json.dumps({"status": "success", "path": str(target), "inserted_at": idx})

    if command == "find_line":
        if search_text is None:
            return json.dumps({"status": "error", "error": "search_text is required"})
        if not target.exists():
            return json.dumps({"status": "error", "error": f"File not found: {target}"})
        matches = [
            {"line": i + 1, "text": line}
            for i, line in enumerate(target.read_text().splitlines())
            if search_text in line or (fuzzy and search_text.lower() in line.lower())
        ]
        return json.dumps({"status": "success", "matches": matches})

    return json.dumps({"status": "error", "error": f"Unsupported command: {command}"})


editor = safe_editor

__all__ = ["file_write", "editor", "retrieve_memory_motifs"]
