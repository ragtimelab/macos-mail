#!/usr/bin/env python3
"""Install the local MCP runtime and register it with supported desktop clients."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts" / "mcp_server.py"
RUNTIME_LOCK = ROOT / "requirements-mcp.lock"
BUILD_LOCK = ROOT / "requirements-build.lock"
VENV = Path.home() / "Library" / "Application Support" / "macos-mail" / "mcp-venv"
NAME = "macos-mail"


def run(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, check=True, text=True, capture_output=True)


def python() -> str:
    return str(VENV / "bin" / "python")


def ensure_runtime() -> None:
    if sys.platform != "darwin" or sys.version_info < (3, 10):
        raise RuntimeError("macOS and Python 3.10 or newer are required")
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required to install the MCP runtime; see https://docs.astral.sh/uv/getting-started/installation/")
    if not RUNTIME_LOCK.is_file() or not BUILD_LOCK.is_file():
        raise RuntimeError("The bundled MCP dependency locks are missing")
    if not (VENV / "pyvenv.cfg").exists():
        VENV.parent.mkdir(parents=True, exist_ok=True)
        run(uv, "venv", str(VENV), "--python", sys.executable)
    run(uv, "pip", "sync", "--python", python(), "--require-hashes", "--strict", str(RUNTIME_LOCK))
    try:
        run(python(), "-c", "from mcp.server.mcpserver import MCPServer")
    except subprocess.CalledProcessError as exc:
        if "cryptography" not in exc.stderr and "libssl" not in exc.stderr:
            raise RuntimeError(exc.stderr) from exc
        # Some Python distributors ship a cryptography wheel linked to a
        # different OpenSSL prefix. Rebuild only the locked sdist, with locked
        # build dependencies, against this host's toolchain.
        run(uv, "pip", "sync", "--python", python(), "--require-hashes", "--strict",
            "--reinstall-package", "cryptography", "--no-binary", "cryptography",
            "--no-cache", "--build-constraints", str(BUILD_LOCK), str(RUNTIME_LOCK))
        run(python(), "-c", "from mcp.server.mcpserver import MCPServer")
    print(f"MCP runtime ready: {python()}")


def register_codex() -> None:
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("codex CLI is not installed")
    existing = subprocess.run([codex, "mcp", "get", NAME, "--json"], capture_output=True, text=True)
    if existing.returncode == 0:
        config = json.loads(existing.stdout).get("transport", {})
        if config.get("type") == "stdio" and config.get("command") == python() and config.get("args") == [str(SERVER)]:
            print("Codex registration already matches")
            return
        raise RuntimeError("Codex already has a different macos-mail server; inspect `codex mcp get macos-mail --json`")
    run(codex, "mcp", "add", NAME, "--", python(), str(SERVER))
    print("Codex registered")


def register_gemini() -> None:
    gemini = shutil.which("gemini")
    if not gemini:
        raise RuntimeError("gemini CLI is not installed")
    settings = Path.home() / ".gemini" / "settings.json"
    value = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    existing = value.get("mcpServers", {}).get(NAME)
    if existing:
        if existing.get("command") == python() and existing.get("args") == [str(SERVER)]:
            print("Gemini registration already matches")
            return
        raise RuntimeError("Gemini already has a different macos-mail server; inspect ~/.gemini/settings.json")
    run(gemini, "mcp", "add", "--scope", "user", NAME, python(), str(SERVER))
    print("Gemini registered")


def register_claude() -> None:
    path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    existing = value.get("mcpServers", {}).get(NAME)
    entry = {"command": python(), "args": [str(SERVER)]}
    if existing == entry:
        print("Claude Desktop registration already matches")
        return
    if existing is not None:
        raise RuntimeError(f"Claude Desktop already has a different {NAME} server; inspect {path}")
    value.setdefault("mcpServers", {})[NAME] = entry
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    print("Claude Desktop registered; restart Claude Desktop to load the server")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=("none", "codex", "gemini", "claude", "all"), default="none")
    args = parser.parse_args()
    if not SERVER.is_file():
        parser.error(f"Missing MCP server: {SERVER}")
    try:
        ensure_runtime()
        selected = ("codex", "gemini", "claude") if args.client == "all" else (args.client,)
        for client in selected:
            if client != "none":
                {"codex": register_codex, "gemini": register_gemini, "claude": register_claude}[client]()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
        print(f"Installation failed: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
