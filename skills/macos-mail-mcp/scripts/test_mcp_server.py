from __future__ import annotations

import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import mcp_server
from mcp_server import MessageRef, mail_change, mail_prepare, mail_recent, mail_send, mail_verify
from mailctl import service


def ref(local_id: int) -> MessageRef:
    return MessageRef(account="Example", mailbox_path=["INBOX"], local_id=local_id)


class MCPBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_key_is_one_private_fixed_file_across_sessions(self) -> None:
        with TemporaryDirectory() as temporary, patch.object(service, "STATE_ROOT", Path(temporary)):
            first = mcp_server.SendSession()._signing_key()
            second = mcp_server.SendSession()._signing_key()
            self.assertEqual(first, second)
            self.assertEqual(len(first), 32)
            self.assertEqual([path.name for path in Path(temporary).iterdir()], ["send-token.key"])
            self.assertEqual((Path(temporary) / "send-token.key").stat().st_mode & 0o077, 0)

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
        plan = {"created_at": "2026-09-24T10:00:00+0900", "draft_ref": ref(17).model_dump(),
                "sender": "a@example.test", "to": ["b@example.test"], "subject": "Subject",
                "sent_before": 0, "body_sha256": "digest"}
        session = mcp_server.SendSession()
        with patch.object(mcp_server, "_send_session", session), \
             patch.object(session, "_signing_key", return_value=b"k" * 32), \
             patch.object(service, "prepare_send", return_value={"ok": True, "session_plan": plan}) as called:
            result = await mail_prepare(kind="new", body="Hello", account="Example", from_address="a@example.test",
                                        to=["b@example.test"], subject="Subject")
            self.assertEqual(session.decode(result["plan_token"])["subject"], "Subject")
            self.assertNotIn("session_plan", result)
        self.assertEqual(called.call_args.args[0].body_text, "Hello")

    async def test_send_token_is_one_use_and_restarted_session_cannot_send(self) -> None:
        plan = {"created_at": "2026-09-24T10:00:00+0900", "draft_ref": ref(17).model_dump(),
                "sender": "a@example.test", "to": ["b@example.test"], "subject": "Subject",
                "sent_before": 0, "body_sha256": "digest"}
        session = mcp_server.SendSession()
        with patch.object(mcp_server, "_send_session", session), \
             patch.object(session, "_signing_key", return_value=b"k" * 32), \
             patch.object(service, "verify_send_evidence", return_value={"ok": True, "status": "confirmed_sent"}) as verified, \
             patch.object(service, "locked_send", return_value=nullcontext()), \
             patch.object(service, "execute_send", return_value={"ok": True, "sent_verified": True,
                    "sent": {"message_ref": ref(20).model_dump()}}) as sent:
            token = session.issue(plan)
            self.assertTrue((await mail_send(token))["sent_verified"])
            self.assertEqual((await mail_send(token))["code"], "PLAN_NOT_PREPARED")
            self.assertEqual((await mail_verify(token))["status"], "confirmed_sent")
            self.assertEqual(session._records, {})
            sent.assert_called_once()
            verified.assert_called_once()
        restarted = mcp_server.SendSession()
        with patch.object(mcp_server, "_send_session", restarted), \
             patch.object(restarted, "_signing_key", return_value=b"k" * 32), \
             patch.object(service, "verify_send_evidence", return_value={"ok": True, "status": "unknown"}):
            self.assertEqual((await mail_send(token))["code"], "SESSION_EXPIRED")
            self.assertEqual((await mail_verify(token))["status"], "unknown")

    async def test_busy_lock_preserves_token_but_failed_attempt_consumes_it(self) -> None:
        plan = {"created_at": "2026-09-24T10:00:00+0900", "draft_ref": ref(17).model_dump(),
                "sender": "a@example.test", "to": ["b@example.test"], "subject": "Subject",
                "sent_before": 0, "body_sha256": "digest"}
        session = mcp_server.SendSession()
        with patch.object(mcp_server, "_send_session", session), \
             patch.object(session, "_signing_key", return_value=b"k" * 32):
            token = session.issue(plan)
            self.assertEqual((await mail_send(token[:-1] + ("A" if token[-1] != "A" else "B")))["code"], "INVALID_PLAN_TOKEN")
            with patch.object(service, "locked_send", side_effect=service.MailCtlError("PLAN_BUSY", "Busy")):
                self.assertEqual((await mail_send(token))["code"], "PLAN_BUSY")
            with patch.object(service, "locked_send", return_value=nullcontext()), \
                 patch.object(service, "execute_send", side_effect=service.MailCtlError("TIMEOUT", "Unknown")) as sent:
                self.assertEqual((await mail_send(token))["code"], "TIMEOUT")
                self.assertEqual((await mail_send(token))["code"], "PLAN_NOT_PREPARED")
                sent.assert_called_once()


if __name__ == "__main__":
    unittest.main()
