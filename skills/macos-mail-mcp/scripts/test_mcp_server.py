from __future__ import annotations

import unittest
from unittest.mock import patch

from mcp_server import MessageRef, mail_change, mail_prepare, mail_recent
from mailctl import service


def ref(local_id: int) -> MessageRef:
    return MessageRef(account="Example", mailbox_path=["INBOX"], local_id=local_id)


class MCPBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recent_defaults_to_all_inboxes_and_does_not_mutate(self) -> None:
        with patch.object(service, "cmd_recent", return_value={"ok": True, "scope": "all-inboxes"}) as called:
            result = await mail_recent(unread=True, limit=3, body="none", sender=None, subject=None, since=None, before=None)
        self.assertEqual(result["scope"], "all-inboxes")
        self.assertTrue(called.call_args.args[0].unread)

    async def test_batch_change_passes_exact_refs_once(self) -> None:
        with patch.object(service, "act_messages", return_value={"ok": True, "complete": True}) as called:
            result = await mail_change([ref(17), ref(18)], ["mark-read", "trash"])
        self.assertTrue(result["complete"])
        called.assert_called_once()
        self.assertEqual([item["local_id"] for item in called.call_args.args[0]], [17, 18])

    async def test_invalid_change_stops_before_mail(self) -> None:
        with patch.object(service, "act_messages") as called:
            result = await mail_change([ref(17)], ["trash", "mark-read"])
        self.assertEqual(result["code"], "INVALID_ACTIONS")
        called.assert_not_called()

    async def test_prepare_passes_body_text_directly(self) -> None:
        with patch.object(service, "prepare_send", return_value={"ok": True, "plan_file": "/tmp/20260924-100000-012345abcdef.json"}) as called:
            result = await mail_prepare(kind="new", body="Hello", account="Example", from_address="a@example.test",
                                        to=["b@example.test"], subject="Subject")
        self.assertEqual(result["plan_id"], "20260924-100000-012345abcdef")
        self.assertEqual(called.call_args.args[0].body_text, "Hello")


if __name__ == "__main__":
    unittest.main()
