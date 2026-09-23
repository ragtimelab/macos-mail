from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from migrate_legacy import copy_state, legacy_entry_matches


class MigrationTests(unittest.TestCase):
    def test_legacy_registration_must_match_the_previous_server(self) -> None:
        entry = {
            "command": str(Path.home() / "Library/Application Support/macos-mail/mcp-venv/bin/python"),
            "args": ["/tmp/example/skills/macos-mail/scripts/mcp_server.py"],
        }
        self.assertTrue(legacy_entry_matches(entry))
        self.assertFalse(legacy_entry_matches({**entry, "args": ["/tmp/other/mcp_server.py"]}))

    def test_copy_preserves_plan_bytes_and_excludes_nonportable_venv(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "old"
            target = root / "new"
            (source / "plans").mkdir(parents=True)
            (source / "plans" / "record.json").write_bytes(b'{"status":"sending"}\n')
            (source / "mcp-venv").mkdir()
            (source / "mcp-venv" / "pyvenv.cfg").write_text("old path")
            self.assertEqual(copy_state(source, target), 1)
            self.assertEqual((target / "plans" / "record.json").read_bytes(), b'{"status":"sending"}\n')
            self.assertFalse((target / "mcp-venv").exists())
            self.assertEqual((target / "plans" / "record.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(copy_state(source, target), 1)

    def test_copy_refuses_a_conflicting_plan_or_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "old"
            target = root / "new"
            source.mkdir()
            target.mkdir()
            (source / "record.json").write_text("original")
            (target / "record.json").write_text("changed")
            with self.assertRaises(RuntimeError):
                copy_state(source, target)
            (target / "record.json").unlink()
            os.symlink(source / "record.json", target / "record.json")
            with self.assertRaises(RuntimeError):
                copy_state(source, target)


if __name__ == "__main__":
    unittest.main()
