#!/usr/bin/env python3
"""Remove only this skill's matching MCP registrations and owned local runtime."""

from __future__ import annotations

import argparse
import filecmp
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import install_mcp


NAME = install_mcp.NAME
ROOT = install_mcp.ROOT
SERVER = install_mcp.SERVER
STATE = install_mcp.VENV.parent
KNOWN_STATE = {"mcp-venv", "mcp-venv.upgrade-old", "adapter-cache", "send-token.key", "send.lock",
               "plans", "compatibility", "compatibility.json"}


def _json_servers(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _entry_matches(entry: dict) -> bool:
    return entry.get("command") == install_mcp.python() and entry.get("args") == [str(SERVER)]


def registrations() -> list[str]:
    found: list[str] = []
    codex = shutil.which("codex")
    if codex:
        result = subprocess.run([codex, "mcp", "get", NAME, "--json"], capture_output=True, text=True)
        if result.returncode == 0:
            entry = json.loads(result.stdout).get("transport", {})
            if entry.get("type") != "stdio" or not _entry_matches(entry):
                raise RuntimeError("Codex registration with this name belongs to a different server")
            found.append("codex")
    gemini_path = Path.home() / ".gemini" / "settings.json"
    gemini_entry = _json_servers(gemini_path).get("mcpServers", {}).get(NAME)
    if gemini_entry is not None:
        if not _entry_matches(gemini_entry):
            raise RuntimeError("Gemini registration with this name belongs to a different server")
        if not shutil.which("gemini"):
            raise RuntimeError("Gemini registration exists but Gemini CLI is unavailable")
        found.append("gemini")
    claude_path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    claude_entry = _json_servers(claude_path).get("mcpServers", {}).get(NAME)
    if claude_entry is not None:
        if not _entry_matches(claude_entry):
            raise RuntimeError("Claude registration with this name belongs to a different server")
        found.append("claude")
    return found


def owned_state_paths() -> list[Path]:
    if not STATE.exists():
        return []
    if STATE.is_symlink() or not STATE.is_dir():
        raise RuntimeError(f"Refusing non-directory or symbolic-link runtime state: {STATE}")
    items = list(STATE.iterdir())
    for item in items:
        if item.name not in KNOWN_STATE or item.is_symlink():
            raise RuntimeError(f"Unknown or symbolic-link runtime item; inspect before uninstalling: {item}")
    return items


def installed_skill_paths() -> list[Path]:
    found = []
    for base in (Path.home() / ".agents" / "skills", Path.home() / ".codex" / "skills"):
        candidate = base / NAME
        if candidate.is_symlink():
            if candidate.resolve() == ROOT.resolve():
                found.append(candidate)
            else:
                raise RuntimeError(f"Skill with this name points elsewhere: {candidate}")
        elif candidate.is_dir():
            def files(root: Path) -> dict[Path, Path]:
                result = {}
                for path in root.rglob("*"):
                    if "__pycache__" in path.parts or path.name == ".DS_Store":
                        continue
                    if path.is_symlink():
                        raise RuntimeError(f"Unexpected symbolic link in installed skill: {path}")
                    if path.is_file():
                        result[path.relative_to(root)] = path
                return result
            source = files(ROOT)
            installed = files(candidate)
            if source.keys() != installed.keys() or any(
                not filecmp.cmp(source[relative], path, shallow=False) for relative, path in installed.items()
            ):
                raise RuntimeError(f"Installed skill differs from this checkout; inspect before removal: {candidate}")
            found.append(candidate)
    return found


def _stop_servers() -> None:
    result = subprocess.run(["ps", "-axo", "pid=,command="], text=True, capture_output=True, check=True)
    matches: list[int] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid, command = parts
        if command.startswith(f"{install_mcp.python()} {SERVER}"):
            matches.append(int(pid))
    for pid in matches:
        os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        if not matches:
            break
        matches = [pid for pid in matches if _running(pid)]
        if matches:
            time.sleep(0.25)
    if matches:
        raise RuntimeError(f"MCP server is still running: {matches}; close its client and retry")


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _remove_claude() -> None:
    path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    value = _json_servers(path)
    if not _entry_matches(value.get("mcpServers", {}).get(NAME, {})):
        raise RuntimeError("Claude registration changed during uninstall")
    value["mcpServers"].pop(NAME)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def uninstall(dry_run: bool = False) -> dict:
    found = registrations()
    state_items = owned_state_paths()
    skills = installed_skill_paths()
    summary = {"registrations": found, "runtime_items": [item.name for item in state_items],
               "installed_skills": [str(path) for path in skills]}
    if dry_run:
        return summary
    for client in found:
        if client == "codex":
            install_mcp.run("codex", "mcp", "remove", NAME)
        elif client == "gemini":
            install_mcp.run("gemini", "mcp", "remove", "--scope", "user", NAME)
        else:
            _remove_claude()
    _stop_servers()
    for item in state_items:
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    if STATE.exists():
        STATE.rmdir()
    for path in skills:
        if path.is_symlink():
            path.unlink()
        else:
            shutil.rmtree(path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = uninstall(args.dry_run)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Uninstall failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "dry_run": args.dry_run, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
