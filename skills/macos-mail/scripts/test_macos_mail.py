from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


from mailctl import service as mail


def ref(local_id: int = 17) -> dict:
    return {
        "account": "Example",
        "mailbox_path": ["INBOX"],
        "local_id": local_id,
        "rfc_message_id": f"<{local_id}@example.test>",
        "universal_id": "",
    }


class MailCliTests(unittest.TestCase):
    def test_fast_paths_and_send_without_user_hash_are_exposed(self) -> None:
        parser = mail.build_parser()
        self.assertIs(parser.parse_args(["recent", "--unread", "--limit", "3", "--body", "full"]).func, mail.cmd_recent)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["recent", "--scope", "all-inboxes"])
        self.assertIs(parser.parse_args(["act", "--refs-file", "/tmp/refs.json", "--actions", "mark-read,trash"]).func, mail.cmd_act)
        self.assertIs(parser.parse_args(["execute", "--plan-file", "/tmp/send.json"]).func, mail.cmd_execute)
        for command in ("compat", "compat-test", "prepare-action"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args([command])

    def test_recent_failure_is_never_presented_as_complete(self) -> None:
        args = mail.build_parser().parse_args(["recent", "--limit", "3", "--body", "full", "--timeout", "30"])
        with patch.object(mail, "call_mail", side_effect=mail.MailCtlError("TIMEOUT", "Mail was slow")):
            result = mail.cmd_recent(args)
        self.assertEqual(result["code"], "TIMEOUT")
        self.assertFalse(result["ok"])
        self.assertFalse(result["complete"])

    def test_recent_uses_one_mail_call(self) -> None:
        args = mail.build_parser().parse_args(["recent", "--limit", "3", "--body", "full", "--timeout", "30"])
        with patch.object(mail, "call_mail", return_value={"ok": True, "complete": True, "messages": []}) as called:
            mail.cmd_recent(args)
        called.assert_called_once_with("recent", {"limit": 3, "body_mode": "full", "unread": False, "sender": "", "subject": "", "since_epoch_seconds": None, "before_epoch_seconds": None}, timeout=30)

    def test_recent_filtered_bounds_and_partial_result(self) -> None:
        args = mail.build_parser().parse_args([
            "recent", "--unread", "--sender", "Example", "--subject", "Notice",
            "--since", "2026-09-24T00:00:00+09:00", "--before", "2026-09-25T00:00:00+09:00",
        ])
        partial = {"ok": False, "operation": "recent", "complete": False, "messages": [{"message_ref": ref()}], "failures": [{"account": "Other"}]}
        with patch.object(mail, "call_mail", side_effect=mail.MailCtlError("MAIL_ERROR", "Partial", partial)) as called:
            result = mail.cmd_recent(args)
        self.assertEqual(result, partial)
        payload = called.call_args.args[1]
        self.assertTrue(payload["unread"])
        self.assertEqual(payload["sender"], "Example")
        self.assertEqual(payload["subject"], "Notice")
        self.assertEqual(payload["since_epoch_seconds"], 1790175600)
        self.assertEqual(payload["before_epoch_seconds"], 1790262000)

    def test_future_date_stays_a_bound(self) -> None:
        args = mail.build_parser().parse_args(["recent", "--since", "2099-01-01T00:00:00+09:00"])
        with patch.object(mail, "call_mail", return_value={"ok": True, "complete": True, "messages": []}) as called:
            mail.cmd_recent(args)
        self.assertGreater(called.call_args.args[1]["since_epoch_seconds"], 0)

    def test_refs_file_rejects_duplicate_and_invalid_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "refs.json"
            path.write_text(json.dumps([ref(), ref()]), encoding="utf-8")
            with self.assertRaises(mail.MailCtlError) as duplicate:
                mail.load_action_refs(str(path))
            self.assertEqual(duplicate.exception.code, "DUPLICATE_TARGET")
            path.write_text(json.dumps([{**ref(), "local_id": True}]), encoding="utf-8")
            with self.assertRaises(mail.MailCtlError) as invalid:
                mail.load_action_refs(str(path))
            self.assertEqual(invalid.exception.code, "INVALID_REFS")

    def test_batch_actions_pass_all_refs_in_one_call_and_report_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "refs.json"
            path.write_text(json.dumps([ref(17), ref(18)]), encoding="utf-8")
            args = argparse.Namespace(refs_file=str(path), actions="mark-read,trash")
            with patch.object(mail, "call_mail", return_value={"ok": True, "complete": False, "results": [{"ok": True}, {"ok": False}]}) as called:
                result = mail.cmd_act(args)
            self.assertFalse(result["ok"])
            self.assertEqual(called.call_count, 1)
            self.assertEqual(called.call_args.args[0], "act")
            self.assertEqual(called.call_args.args[1]["actions"], ["mark-read", "trash"])
            self.assertEqual(len(called.call_args.args[1]["refs"]), 2)

    def test_invalid_batch_actions_never_reach_mail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "refs.json"
            path.write_text(json.dumps([ref()]), encoding="utf-8")
            with patch.object(mail, "call_mail") as called:
                with self.assertRaises(mail.MailCtlError):
                    mail.cmd_act(argparse.Namespace(refs_file=str(path), actions="trash,mark-read"))
            called.assert_not_called()

    def test_batch_rejects_a_false_success_from_mail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "refs.json"
            path.write_text(json.dumps([ref()]), encoding="utf-8")
            response = {"ok": True, "complete": True, "results": [{"ok": True, "mark_read_verified": True, "trash_verified": True, "removed_from_source": True, "trash_present": False, "message": {"read": True}}]}
            with patch.object(mail, "call_mail", return_value=response):
                result = mail.cmd_act(argparse.Namespace(refs_file=str(path), actions="mark-read,trash"))
        self.assertFalse(result["ok"])
        self.assertFalse(result["complete"])

    def test_prepared_send_stays_bound_without_user_supplied_hash(self) -> None:
        manifest = {"schema_version": 4, "kind": "send", "status": "prepared", "plan_hash": "internal", "environment_fingerprint": "same"}
        with patch.object(mail, "load_plan", return_value=(Path("/tmp/plan"), manifest)), patch.object(mail, "mail_environment", return_value={"fingerprint": "same"}), patch.object(mail, "execute_send", return_value={"ok": True}) as execute:
            mail.cmd_execute(argparse.Namespace(plan_file="/tmp/plan"))
        self.assertEqual(execute.call_args.args[2], "internal")

    def test_changed_send_environment_stops_before_send(self) -> None:
        manifest = {"schema_version": 4, "kind": "send", "status": "prepared", "plan_hash": "internal", "environment_fingerprint": "old"}
        with patch.object(mail, "load_plan", return_value=(Path("/tmp/plan"), manifest)), patch.object(mail, "mail_environment", return_value={"fingerprint": "new"}), patch.object(mail, "execute_send") as execute:
            with self.assertRaises(mail.MailCtlError) as stale:
                mail.cmd_execute(argparse.Namespace(plan_file="/tmp/plan"))
        self.assertEqual(stale.exception.code, "STALE_PLAN")
        execute.assert_not_called()

    def test_ambiguous_send_cannot_be_replayed(self) -> None:
        draft = {
            "message_ref": ref(), "account_id": "account-id", "sender": "a@example.test",
            "to": ["b@example.test"], "cc": [], "bcc": [], "subject": "Subject", "body": "Body",
        }
        canonical = mail.send_canonical("new", draft, None, False, 0, [], 19)
        digest = mail.bound_plan_hash(canonical, "same")
        manifest = {
            "kind": "send", "status": "prepared", "plan_hash": digest,
            "operation": "new", "draft_ref": ref(), "source_ref": None,
            "reply_all": False, "sent_before": 0, "draft_outgoing_id": 19,
            "attachments": [], "environment_fingerprint": "same",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            def fake_call(command, *_args, **_kwargs):
                if command == "read_role_message":
                    return {"message": draft}
                raise mail.MailCtlError("TIMEOUT", "Send result unknown")
            with patch.object(mail, "call_mail", side_effect=fake_call):
                with self.assertRaises(mail.MailCtlError):
                    mail.execute_send(path, manifest, digest)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "sending")

    def test_prepared_send_uses_bound_outgoing_without_cleanup(self) -> None:
        draft = {
            "message_ref": ref(), "account_id": "account-id", "sender": "a@example.test",
            "to": ["b@example.test"], "cc": [], "bcc": [], "subject": "Subject", "body": "Body",
        }
        canonical = mail.send_canonical("new", draft, None, False, 0, [], 19)
        digest = mail.bound_plan_hash(canonical, "same")
        manifest = {
            "schema_version": 4, "kind": "send", "status": "prepared", "plan_hash": digest,
            "operation": "new", "draft_ref": ref(), "source_ref": None,
            "reply_all": False, "sent_before": 0, "draft_outgoing_id": 19,
            "attachments": [], "environment_fingerprint": "same",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            def fake_call(command, payload, **_kwargs):
                if command == "read_role_message":
                    return {"message": draft}
                self.assertEqual(command, "send_plan")
                self.assertEqual(payload["outgoing_id"], 19)
                self.assertEqual(payload["draft_ref"], ref())
                return {"sent_verified": True, "sent": {"message_ref": ref(20)}, "draft_remaining": False}
            with patch.object(mail, "call_mail", side_effect=fake_call) as called:
                result = mail.execute_send(path, manifest, digest)
            self.assertTrue(result["sent_verified"])
            self.assertEqual([call.args[0] for call in called.call_args_list], ["read_role_message", "send_plan"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "sent")

    def test_old_prepared_plan_rejected_but_old_sent_receipt_verifies(self) -> None:
        old = {"schema_version": 3, "kind": "send", "status": "prepared", "plan_hash": "old"}
        with patch.object(mail, "load_plan", return_value=(Path("/tmp/old"), old)), patch.object(mail, "call_mail") as called:
            with self.assertRaises(mail.MailCtlError) as stale:
                mail.cmd_execute(argparse.Namespace(plan_file="/tmp/old"))
            self.assertEqual(stale.exception.code, "STALE_PLAN")
            old.update(status="sent", sent_ref=ref())
            verified = mail.cmd_verify(argparse.Namespace(plan_file="/tmp/old"))
            self.assertTrue(verified["sent_verified_at_send"])
            self.assertEqual(verified["current_location"], "not_checked")
            called.assert_not_called()

    def test_draft_rekey_keeps_plan_identity_but_missing_recipient_stops_send(self) -> None:
        draft = {
            "message_ref": {**ref(), "universal_id": "stable-uuid"},
            "account_id": "account-id", "sender": "a@example.test",
            "to": ["b@example.test"], "cc": [], "bcc": [], "subject": "Subject", "body": "Body",
        }
        first = mail.send_canonical("new", draft, None, False, 0, [], 19)
        draft["message_ref"] = {**draft["message_ref"], "local_id": 29, "rfc_message_id": "<new@example.test>"}
        self.assertEqual(first, mail.send_canonical("new", draft, None, False, 0, [], 19))
        draft["to"] = []
        with self.assertRaises(mail.MailCtlError) as missing:
            mail.send_prepared_payload(draft, "new", None, False, 0, [], 19)
        self.assertEqual(missing.exception.code, "RECIPIENT_REQUIRED")


if __name__ == "__main__":
    unittest.main()
