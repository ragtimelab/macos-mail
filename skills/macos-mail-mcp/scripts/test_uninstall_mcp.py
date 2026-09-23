from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import uninstall_mcp


class UninstallTests(unittest.TestCase):
    def test_dry_run_and_exact_owned_state_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            state.mkdir()
            (state / "send-token.key").write_bytes(b"k" * 32)
            (state / "adapter-cache").mkdir()
            (state / "adapter-cache" / "compiled.scpt").write_bytes(b"compiled")
            skill = Path(temporary) / "skill-link"
            skill.symlink_to(uninstall_mcp.ROOT)
            with patch.object(uninstall_mcp, "STATE", state), \
                 patch.object(uninstall_mcp, "registrations", return_value=[]), \
                 patch.object(uninstall_mcp, "installed_skill_paths", return_value=[skill]), \
                 patch.object(uninstall_mcp, "_stop_servers"):
                report = uninstall_mcp.uninstall(dry_run=True)
                self.assertEqual(sorted(report["runtime_items"]), ["adapter-cache", "send-token.key"])
                self.assertTrue(state.exists())
                uninstall_mcp.uninstall()
                self.assertFalse(state.exists())
                self.assertFalse(skill.is_symlink())
                self.assertTrue(uninstall_mcp.ROOT.exists())

    def test_unknown_state_item_stops_uninstall_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            state.mkdir()
            (state / "personal-file").write_text("keep")
            with patch.object(uninstall_mcp, "STATE", state), \
                 patch.object(uninstall_mcp, "registrations", return_value=[]), \
                 patch.object(uninstall_mcp, "_stop_servers") as stop:
                with self.assertRaises(RuntimeError):
                    uninstall_mcp.uninstall()
                stop.assert_not_called()
                self.assertTrue((state / "personal-file").exists())


if __name__ == "__main__":
    unittest.main()
