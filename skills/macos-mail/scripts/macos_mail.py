#!/usr/bin/env python3
"""Command-line entry point for the shared Apple Mail service."""

from mailctl.service import main


if __name__ == "__main__":
    raise SystemExit(main())
