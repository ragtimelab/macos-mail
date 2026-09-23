#!/usr/bin/env python3
"""Move the previous installation's local state and client registrations once."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import install_mcp


OLD_NAME = "macos-mail"
OLD_STATE = Path.home() / "Library" / "Application Support" / OLD_NAME
NEW_STATE = install_mcp.VENV.parent
BACKUP_PARENT = Path.home() / "Library" / "Application Support"
CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
GEMINI_CONFIG = Path.home() / ".gemini" / "settings.json"
CLAUDE_CONFIG = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def legacy_entry_matches(entry: dict) -> bool:
    """Only replace the old server's own registration, not a name collision."""
    command = entry.get("command")
    args = entry.get("args")
    return (
        command == str(OLD_STATE / "mcp-venv" / "bin" / "python")
        and isinstance(args, list)
        and len(args) == 1
        and isinstance(args[0], str)
        and args[0].endswith("/skills/macos-mail/scripts/mcp_server.py")
        and entry.get("env") in (None, {})
        and entry.get("env_vars") in (None, [])
        and entry.get("cwd") is None
    )


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _state_files(root: Path) -> dict[Path, str]:
    results: dict[Path, str] = {}
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if current_path != root or name != "mcp-venv"]
        for name in dirs + files:
            path = current_path / name
            relative = path.relative_to(root)
            if path.is_symlink():
                raise RuntimeError(f"Refusing a symbolic link in runtime state: {relative}")
            if path.is_file():
                results[relative] = _file_hash(path)
    return results


def copy_state(source: Path, destination: Path) -> int:
    files = _state_files(source)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination, 0o700)
    for relative, expected_hash in files.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(target.parent, 0o700)
        if os.path.lexists(target):
            if target.is_symlink() or not target.is_file() or _file_hash(target) != expected_hash:
                raise RuntimeError(f"Conflicting destination state: {relative}")
        else:
            shutil.copyfile(source / relative, target)
        os.chmod(target, 0o600)
        if _file_hash(target) != expected_hash:
            raise RuntimeError(f"State verification failed: {relative}")
    return len(files)


def _read_servers(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})


def _codex_legacy() -> bool:
    result = subprocess.run(["codex", "mcp", "get", OLD_NAME, "--json"], text=True, capture_output=True)
    if result.returncode:
        return False
    entry = json.loads(result.stdout).get("transport", {})
    if entry.get("type") != "stdio" or not legacy_entry_matches(entry):
        raise RuntimeError("The existing Codex legacy registration does not match this installation")
    return True


def _json_legacy(path: Path) -> bool:
    entry = _read_servers(path).get(OLD_NAME)
    if entry is None:
        return False
    if not legacy_entry_matches(entry):
        raise RuntimeError(f"The legacy registration in {path} does not match this installation")
    return True


def _backup_config(path: Path, backup: Path) -> None:
    if path.exists():
        target = backup / path.name
        shutil.copyfile(path, target)
        os.chmod(target, 0o600)


def migrate() -> Path:
    if not OLD_STATE.is_dir():
        raise RuntimeError(f"Legacy runtime state was not found: {OLD_STATE}")
    if OLD_STATE.is_symlink() or NEW_STATE.is_symlink():
        raise RuntimeError("Runtime state directory must not be a symbolic link")
    processes = subprocess.check_output(["ps", "-axo", "command="], text=True)
    if "/skills/macos-mail/scripts/mcp_server.py" in processes:
        raise RuntimeError("An old MCP server is still running; close its client and retry")

    clients = {
        "codex": _codex_legacy(),
        "gemini": _json_legacy(GEMINI_CONFIG),
        "claude": _json_legacy(CLAUDE_CONFIG),
    }
    stamp = subprocess.check_output(["date", "+%Y%m%d-%H%M%S"], text=True).strip()
    backup = BACKUP_PARENT / f".macos-mail-mcp-rename-backup-{stamp}-{os.getpid()}"
    backup.mkdir(mode=0o700)
    os.chmod(backup, 0o700)
    try:
        count = copy_state(OLD_STATE, backup / "state")
        for config in (CODEX_CONFIG, GEMINI_CONFIG, CLAUDE_CONFIG):
            _backup_config(config, backup)
        copied = copy_state(OLD_STATE, NEW_STATE)
        if copied != count:
            raise RuntimeError("The runtime state copy is incomplete")

        install_mcp.ensure_runtime()
        for client, found in clients.items():
            if found:
                {"codex": install_mcp.register_codex,
                 "gemini": install_mcp.register_gemini,
                 "claude": install_mcp.register_claude}[client]()

        if clients["codex"]:
            install_mcp.run("codex", "mcp", "remove", OLD_NAME)
        if clients["gemini"]:
            install_mcp.run("gemini", "mcp", "remove", "--scope", "user", OLD_NAME)
        if clients["claude"]:
            value = json.loads(CLAUDE_CONFIG.read_text(encoding="utf-8"))
            if not legacy_entry_matches(value.get("mcpServers", {}).get(OLD_NAME, {})):
                raise RuntimeError("Claude Desktop legacy registration changed during migration")
            value["mcpServers"].pop(OLD_NAME)
            temporary = CLAUDE_CONFIG.with_name(CLAUDE_CONFIG.name + ".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, CLAUDE_CONFIG)
        print(f"Migrated {count} runtime files and {sum(clients.values())} client registrations")
        print(f"Private rollback backup: {backup}")
        return backup
    except BaseException:
        print(f"Migration stopped; retain the private rollback backup at {backup}", file=sys.stderr)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        migrate()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
