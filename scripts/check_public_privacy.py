#!/usr/bin/env python3
"""Reject private contact data or credentials in a public release candidate."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMAIL = re.compile(rb"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
HOME_PATH = re.compile(rb"/Users/[A-Za-z0-9._-]+")
PRIVATE_KEY = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")
TOKEN = re.compile(rb"(?:ghp_|github_pat_|sk-)[A-Za-z0-9_-]{16,}")
ALLOWED_EMAIL_DOMAINS = {"example.test", "users.noreply.github.com", "github.com"}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="", help="Previous commit or PR base SHA")
    args = parser.parse_args()
    failures: list[str] = []

    for name in git("ls-files", "-z").split("\0"):
        if not name:
            continue
        path = ROOT / name
        data = path.read_bytes()
        if b"\0" in data:
            continue
        for line_number, line in enumerate(data.splitlines(), 1):
            for found in EMAIL.finditer(line):
                domain = found.group().decode("ascii", errors="ignore").rsplit("@", 1)[-1].lower()
                if domain not in ALLOWED_EMAIL_DOMAINS:
                    failures.append(f"{name}:{line_number}: non-example email")
            if HOME_PATH.search(line):
                failures.append(f"{name}:{line_number}: absolute user home path")
            if PRIVATE_KEY.search(line) or TOKEN.search(line):
                failures.append(f"{name}:{line_number}: credential pattern")

    base = args.base.lower()
    if base and not re.fullmatch(r"[0-9a-f]{40}", base):
        parser.error("--base must be a 40-character commit SHA")
    commits = git("rev-list", f"{base}..HEAD" if base and int(base, 16) else "HEAD").splitlines()
    for sha in commits:
        for email in git("show", "-s", "--format=%ae%n%ce", sha).splitlines():
            if email.rsplit("@", 1)[-1].lower() not in ALLOWED_EMAIL_DOMAINS:
                failures.append(f"{sha[:12]}: public commit email")

    for item in failures:
        print(item)
    if failures:
        print(f"Public privacy check failed: {len(failures)} finding(s)")
        return 1
    print(f"Public privacy check passed: {len(commits)} new commit(s), tracked files scanned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
