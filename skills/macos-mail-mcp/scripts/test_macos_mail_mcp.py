from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
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
    def _find_message(self, local_id: int = 17) -> dict:
        return {"message_ref": ref(local_id), "account_id": "account-1", "sender": "Sender",
                "subject": "PR update", "read": False, "date_received_iso": "2026-09-20T10:00:00+09:00"}

    def test_cli_exposes_read_and_change_but_no_multistep_send(self) -> None:
        parser = mail.build_parser()
        self.assertIs(parser.parse_args(["recent", "--unread", "--limit", "3", "--body", "full"]).func, mail.cmd_recent)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["recent", "--scope", "all-inboxes"])
        self.assertIs(parser.parse_args(["act", "--refs-file", "/tmp/refs.json", "--actions", "mark-read,trash"]).func, mail.cmd_act)
        for command in ("execute", "verify", "prepare-new", "prepare-reply", "prepare-forward", "compat", "compat-test"):
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

    def test_recent_auto_uses_metadata_for_large_or_subject_lists(self) -> None:
        for options in (["--limit", "20"], ["--subject", "PR"]):
            args = mail.build_parser().parse_args(["recent", *options])
            with patch.object(mail, "call_mail", return_value={"ok": True, "complete": True,
                    "messages": [self._find_message()]}) as called:
                result = mail.cmd_recent(args)
            self.assertEqual(called.call_args.args[1]["body_mode"], "none")
            self.assertEqual(result["body_mode_effective"], "none")
            self.assertEqual(set(result["messages"][0]), {"message_ref", "sender", "subject", "read", "date_received_iso"})
        args = mail.build_parser().parse_args(["recent", "--limit", "20", "--body", "full"])
        with patch.object(mail, "call_mail") as called, self.assertRaises(mail.MailCtlError) as raised:
            mail.cmd_recent(args)
        self.assertEqual(raised.exception.code, "BODY_LIMIT")
        called.assert_not_called()

    def test_subject_find_pages_without_implicit_date_limit(self) -> None:
        args = mail.build_parser().parse_args(["locate", "--subject", "PR", "--limit", "1", "--body", "none"])
        response = {"ok": True, "complete": True, "match_total": 2, "messages": [self._find_message(17), self._find_message(18)]}
        with patch.object(mail, "call_mail", return_value=response) as called:
            result = mail.cmd_locate(args)
        self.assertEqual(called.call_count, 1)
        self.assertIsNotNone(called.call_args.args[1]["since_epoch_seconds"])
        self.assertEqual(result["count"], 1)
        self.assertTrue(result["has_more"])
        self.assertNotIn("match_total", result)
        self.assertNotIn("account_id", result["messages"][0])
        args.page_token = result["next_page_token"]
        with patch.object(mail, "call_mail", return_value={"ok": True, "complete": True, "match_total": 0, "messages": []}) as next_page:
            mail.cmd_locate(args)
        self.assertEqual(next_page.call_args.args[1]["cursor_local_id"], 17)
        args.subject = "different"
        with patch.object(mail, "call_mail") as never_called, self.assertRaises(mail.MailCtlError) as raised:
            mail.cmd_locate(args)
        self.assertEqual(raised.exception.code, "INVALID_PAGE_TOKEN")
        never_called.assert_not_called()

    def test_find_underfilled_window_rechecks_full_history(self) -> None:
        args = mail.build_parser().parse_args(["locate", "--sender", "news@example.test", "--limit", "20", "--body", "none"])
        first = {"ok": True, "complete": True, "match_total": 0, "messages": []}
        second = {"ok": True, "complete": True, "match_total": 1, "messages": [self._find_message()]}
        with patch.object(mail, "call_mail", side_effect=[first, second]) as called:
            result = mail.cmd_locate(args)
        self.assertEqual(called.call_count, 2)
        self.assertIsNone(called.call_args.args[1]["since_epoch_seconds"])
        self.assertEqual(result["match_total"], 1)
        self.assertTrue(result["history_exhausted"])
        self.assertFalse(result["has_more"])

    def test_specific_subject_scans_full_history_once(self) -> None:
        args = mail.build_parser().parse_args(["locate", "--subject", "Supabase", "--body", "none"])
        with patch.object(mail, "call_mail", return_value={"ok": True, "complete": True,
                "match_total": 1, "messages": [self._find_message()]}) as called:
            result = mail.cmd_locate(args)
        called.assert_called_once()
        self.assertIsNone(called.call_args.args[1]["since_epoch_seconds"])
        self.assertEqual(result["count"], 1)

    def test_find_exact_total_and_partial_coverage(self) -> None:
        args = mail.build_parser().parse_args(["locate", "--subject", "PR", "--include-total", "--body", "none"])
        complete = {"ok": True, "complete": True, "match_total": 21, "messages": [self._find_message()]}
        with patch.object(mail, "call_mail", return_value=complete) as called:
            result = mail.cmd_locate(args)
        self.assertIsNone(called.call_args.args[1]["since_epoch_seconds"])
        self.assertEqual(result["match_total"], 21)
        args.include_total = False
        partial = {"ok": False, "complete": False, "match_verified_count": 1, "messages": [self._find_message()],
                   "failures": [{"account": "Other"}]}
        with patch.object(mail, "call_mail", return_value=partial):
            result = mail.cmd_locate(args)
        self.assertIsNone(result["has_more"])
        self.assertIsNone(result["next_page_token"])
        self.assertNotIn("match_total", result)

    def test_find_timeout_reports_incomplete_without_retrying(self) -> None:
        args = mail.build_parser().parse_args(["locate", "--subject", "PR", "--body", "none"])
        with patch.object(mail, "call_mail", side_effect=mail.MailCtlError("TIMEOUT", "Mail was slow")) as called:
            result = mail.cmd_locate(args)
        called.assert_called_once()
        self.assertFalse(result["complete"])
        self.assertIsNone(result["has_more"])
        self.assertEqual(result["code"], "TIMEOUT")

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

    def test_changed_send_environment_stops_before_send(self) -> None:
        manifest = {"environment_fingerprint": "old"}
        with patch.object(mail, "mail_environment", return_value={"fingerprint": "new"}), patch.object(mail, "call_mail") as called:
            with self.assertRaises(mail.MailCtlError) as stale:
                mail.execute_send(manifest)
            self.assertEqual(stale.exception.code, "STALE_PLAN")
        called.assert_not_called()

    def test_ambiguous_send_cannot_be_replayed(self) -> None:
        draft = {
            "message_ref": ref(), "account_id": "account-id", "sender": "a@example.test",
            "to": ["b@example.test"], "cc": [], "bcc": [], "subject": "Subject", "body": "Body",
        }
        canonical = mail.send_canonical("new", draft, None, False, 0, [], 19)
        digest = mail.bound_plan_hash(canonical, "same")
        manifest = {
            "plan_hash": digest,
            "operation": "new", "draft_ref": ref(), "source_ref": None,
            "reply_all": False, "sent_before": 0, "draft_outgoing_id": 19,
            "attachments": [], "environment_fingerprint": "same",
        }
        def fake_call(command, *_args, **_kwargs):
            if command == "read_role_message":
                return {"message": draft}
            raise mail.MailCtlError("TIMEOUT", "Send result unknown")
        with tempfile.TemporaryDirectory() as directory, patch.object(mail, "STATE_ROOT", Path(directory)), \
             patch.object(mail, "mail_environment", return_value={"fingerprint": "same"}), \
             patch.object(mail, "attachment_inputs", return_value=[]), patch.object(mail, "call_mail", side_effect=fake_call):
            with self.assertRaises(mail.MailCtlError):
                mail.execute_send(manifest)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_prepared_send_uses_bound_outgoing_without_cleanup(self) -> None:
        draft = {
            "message_ref": ref(), "account_id": "account-id", "sender": "a@example.test",
            "to": ["b@example.test"], "cc": [], "bcc": [], "subject": "Subject", "body": "Body",
        }
        canonical = mail.send_canonical("new", draft, None, False, 0, [], 19)
        digest = mail.bound_plan_hash(canonical, "same")
        manifest = {
            "plan_hash": digest,
            "operation": "new", "draft_ref": ref(), "source_ref": None,
            "reply_all": False, "sent_before": 0, "draft_outgoing_id": 19,
            "attachments": [], "environment_fingerprint": "same",
        }
        def fake_call(command, payload, **_kwargs):
            if command == "read_role_message":
                return {"message": draft}
            self.assertEqual(command, "send_plan")
            self.assertEqual(payload["outgoing_id"], 19)
            self.assertEqual(payload["draft_ref"], ref())
            return {"sent_verified": True, "sent": {"message_ref": ref(20)}, "draft_remaining": False}
        with tempfile.TemporaryDirectory() as directory, patch.object(mail, "STATE_ROOT", Path(directory)), \
             patch.object(mail, "mail_environment", return_value={"fingerprint": "same"}), \
             patch.object(mail, "attachment_inputs", return_value=[]), patch.object(mail, "call_mail", side_effect=fake_call) as called:
            result = mail.execute_send(manifest)
            self.assertTrue(result["sent_verified"])
            self.assertEqual([call.args[0] for call in called.call_args_list], ["read_role_message", "send_plan"])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_verify_requires_unique_matching_sent_evidence(self) -> None:
        plan = {"draft_ref": ref(), "sender": "a@example.test", "to": ["b@example.test"],
                "subject": "Subject", "sent_before": 0, "created_at": "2026-09-24T04:23:26+0900",
                "body_sha256": mail.sha256_text("Body")}
        sent = {"count": 1, "candidates": [{"local_id": 20, "body": "Body"}]}
        def fake_call(command, *_args, **_kwargs):
            if command == "read_role_message":
                raise mail.MailCtlError("NOT_FOUND", "No draft")
            return sent
        with patch.object(mail, "call_mail", side_effect=fake_call):
            self.assertEqual(mail.verify_send_evidence(plan)["status"], "confirmed_sent")
            sent["candidates"].append({"local_id": 21, "body": "Body"})
            self.assertEqual(mail.verify_send_evidence(plan)["status"], "unknown")

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

    def test_attachment_save_is_private_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            os.chmod(output_dir, 0o755)
            args = argparse.Namespace(account="Example", mailbox_json='["INBOX"]', mailbox=None,
                                      id=17, rfc_message_id="<17@example.test>", universal_id="",
                                      attachment_id="attachment-1", output_dir=directory)
            message = {"message_ref": ref(), "attachments": [{"id": "attachment-1", "name": "report.txt"}]}

            def save(_command, payload, **_kwargs):
                staged = Path(payload["output_path"])
                staged.write_bytes(b"private attachment")
                os.chmod(staged, 0o644)
                return {"ok": True, "output_path": str(staged)}

            with patch.object(mail, "read_message", return_value=message), patch.object(mail, "call_mail", side_effect=save):
                result = mail.cmd_attachment_save(args)
            output = output_dir / "report.txt"
            self.assertEqual(Path(result["output_path"]), output.resolve())
            self.assertEqual(output.read_bytes(), b"private attachment")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(list(output_dir.glob(".macos-mail-mcp-*")), [])
            with patch.object(mail, "read_message", return_value=message), patch.object(mail, "call_mail") as called:
                with self.assertRaises(mail.MailCtlError) as existing:
                    mail.cmd_attachment_save(args)
            self.assertEqual(existing.exception.code, "NO_OVERWRITE")
            called.assert_not_called()

    def test_broken_symlink_and_hidden_attachment_names_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(account="Example", mailbox_json='["INBOX"]', mailbox=None,
                                      id=17, rfc_message_id="<17@example.test>", universal_id="",
                                      attachment_id="attachment-1", output_dir=directory)
            message = {"message_ref": ref(), "attachments": [{"id": "attachment-1", "name": "report.txt"}]}
            (Path(directory) / "report.txt").symlink_to(Path(directory) / "missing")
            with patch.object(mail, "read_message", return_value=message), patch.object(mail, "call_mail") as called:
                with self.assertRaises(mail.MailCtlError) as existing:
                    mail.cmd_attachment_save(args)
            self.assertEqual(existing.exception.code, "NO_OVERWRITE")
            called.assert_not_called()
            message["attachments"][0]["name"] = ".zshenv"
            with patch.object(mail, "read_message", return_value=message):
                with self.assertRaises(mail.MailCtlError) as unsafe:
                    mail.cmd_attachment_save(args)
            self.assertEqual(unsafe.exception.code, "UNSAFE_ATTACHMENT_NAME")

    def test_one_send_lock_rejects_a_concurrent_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            def contend():
                with self.assertRaises(mail.MailCtlError) as busy:
                    with mail.locked_send():
                        pass
                return busy.exception.code

            with patch.object(mail, "STATE_ROOT", Path(directory)), patch.object(mail, "SEND_LOCK", Path(directory) / "send.lock"):
                with mail.locked_send(), ThreadPoolExecutor(max_workers=1) as pool:
                    self.assertEqual(pool.submit(contend).result(), "PLAN_BUSY")
                self.assertEqual(stat.S_IMODE((Path(directory) / "send.lock").stat().st_mode), 0o600)

    def test_mail_output_and_prepare_inputs_are_bounded(self) -> None:
        with patch.object(mail, "MAX_MAIL_RESPONSE_BYTES", 16):
            with self.assertRaises(mail.MailCtlError) as oversized:
                mail.run_command([sys.executable, "-c", "print('x' * 32)"])
        self.assertEqual(oversized.exception.code, "RESPONSE_TOO_LARGE")
        with patch.object(mail, "MAX_BODY_BYTES", 4):
            with self.assertRaises(mail.MailCtlError) as body:
                mail.normalize_body_text("12345")
        self.assertEqual(body.exception.code, "BODY_TOO_LARGE")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.bin"
            path.write_bytes(b"12345")
            with patch.object(mail, "MAX_ATTACHMENT_TOTAL_BYTES", 4):
                with self.assertRaises(mail.MailCtlError) as attachment:
                    mail.attachment_inputs([str(path)])
            self.assertEqual(attachment.exception.code, "ATTACHMENTS_TOO_LARGE")


if __name__ == "__main__":
    unittest.main()
