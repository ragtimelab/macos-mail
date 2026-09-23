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
STATE = Path(os.environ.get("MACOS_MAIL_MCP_STATE_DIR", Path.home() / "Library" / "Application Support" / "macos-mail-mcp")).expanduser().absolute()
VENV = STATE / "mcp-venv"
NAME = "macos-mail-mcp"


def run(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, check=True, text=True, capture_output=True)


def python() -> str:
    return str(VENV / "bin" / "python")


def runtime_version() -> tuple[int, int] | None:
    if not (VENV / "pyvenv.cfg").exists():
        return None
    try:
        result = run(python(), "-c", "import sys; print(sys.version_info.major, sys.version_info.minor)")
        major, minor = result.stdout.strip().split()
        return int(major), int(minor)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return (0, 0)


def sync_runtime(uv: str) -> None:
    run(uv, "pip", "sync", "--python", python(), "--require-hashes", "--strict", str(RUNTIME_LOCK))
    try:
        run(python(), "-c", "from mcp.server.mcpserver import MCPServer")
    except subprocess.CalledProcessError as exc:
        if "cryptography" not in exc.stderr and "libssl" not in exc.stderr:
            raise RuntimeError(exc.stderr) from exc
        run(uv, "pip", "sync", "--python", python(), "--require-hashes", "--strict",
            "--reinstall-package", "cryptography", "--no-binary", "cryptography",
            "--no-cache", "--build-constraints", str(BUILD_LOCK), str(RUNTIME_LOCK))
        run(python(), "-c", "from mcp.server.mcpserver import MCPServer")


def ensure_runtime() -> None:
    if sys.platform != "darwin" or sys.version_info < (3, 14):
        raise RuntimeError("macOS and Python 3.14 or newer are required; start this installer with uv run --python 3.14")
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required to install the MCP runtime; see https://docs.astral.sh/uv/getting-started/installation/")
    if not RUNTIME_LOCK.is_file() or not BUILD_LOCK.is_file():
        raise RuntimeError("The bundled MCP dependency locks are missing")
    if STATE.is_symlink() or VENV.is_symlink():
        raise RuntimeError("Runtime state and virtual environment cannot be symbolic links")
    VENV.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(VENV.parent, 0o700)
    existing_version = runtime_version()
    if existing_version is not None and existing_version >= (3, 14):
        sync_runtime(uv)
        print(f"MCP runtime ready: {python()}")
        return
    old = VENV.with_name(VENV.name + ".upgrade-old")
    if os.path.lexists(old):
        raise RuntimeError(f"Previous runtime upgrade is incomplete; inspect {old}")
    if VENV.exists():
        VENV.rename(old)
    try:
        run(uv, "venv", str(VENV), "--python", "3.14")
        sync_runtime(uv)
    except BaseException:
        if VENV.exists():
            shutil.rmtree(VENV)
        if old.exists():
            old.rename(VENV)
        raise
    if old.exists():
        shutil.rmtree(old)
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
        raise RuntimeError("Codex already has a different macos-mail-mcp server; inspect `codex mcp get macos-mail-mcp --json`")
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
        raise RuntimeError("Gemini already has a different macos-mail-mcp server; inspect ~/.gemini/settings.json")
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
