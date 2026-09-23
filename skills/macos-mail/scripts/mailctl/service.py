#!/usr/bin/env python3
"""Exact, verified Apple Mail automation CLI for one or many local accounts."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import time
import uuid
from email.utils import parseaddr
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[2]
APPLESCRIPT = SKILL_ROOT / "scripts" / "mail.applescript"
MAIL_APP: Path | None = None
MAIL_SDEF: Path | None = None
STATE_ROOT = Path(os.environ.get("MACOS_MAIL_STATE_DIR", Path.home() / "Library" / "Application Support" / "macos-mail")).expanduser().resolve()
PLANS_DIR = STATE_ROOT / "plans"
POLICY = json.loads((SKILL_ROOT / "references" / "policy.json").read_text(encoding="utf-8"))
if POLICY.get("schema_version") != 1:
    raise RuntimeError("Unsupported policy schema")
for policy_key in (
    "command_timeout_seconds",
    "send_timeout_seconds",
    "search_limit_default",
    "search_limit_max",
    "send_verification_attempts",
    "draft_verification_attempts",
    "poll_interval_seconds",
):
    if not isinstance(POLICY.get(policy_key), int) or POLICY[policy_key] < 1:
        raise RuntimeError(f"Invalid positive integer policy: {policy_key}")
DEFAULT_TIMEOUT = int(POLICY["command_timeout_seconds"])
SEND_TIMEOUT = int(POLICY["send_timeout_seconds"])
MINIMUM_SEND_TIMEOUT = (
    int(POLICY["send_verification_attempts"]) * int(POLICY["poll_interval_seconds"])
) + 5
if SEND_TIMEOUT < MINIMUM_SEND_TIMEOUT:
    raise RuntimeError("send_timeout_seconds is smaller than the configured preflight and verification budget")

LOCATE_DEFAULT_WINDOW_SECONDS = 14 * 24 * 60 * 60


class MailCtlError(RuntimeError):
    def __init__(self, code: str, message: str, details: Any | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def date_now() -> str:
    """Load write-only timestamp support only when a write path needs it."""
    from mailctl.core import date_now as core_date_now

    return core_date_now()


def date_stamp() -> str:
    """Load write-only timestamp support only when a write path needs it."""
    from mailctl.core import date_stamp as core_date_stamp

    return core_date_stamp()


def mail_paths() -> tuple[Path, Path]:
    """Resolve the system Mail bundle without an Apple Event on the common path."""
    global MAIL_APP, MAIL_SDEF
    if MAIL_APP is None or MAIL_SDEF is None:
        candidate = Path("/System/Applications/Mail.app")
        info_path = candidate / "Contents" / "Info.plist"
        try:
            with info_path.open("rb") as handle:
                info = plistlib.load(handle)
            is_system_mail = info.get("CFBundleIdentifier") == "com.apple.mail"
        except (OSError, plistlib.InvalidFileException):
            is_system_mail = False
        if is_system_mail:
            MAIL_APP = candidate
        else:
            raise MailCtlError("MAIL_NOT_FOUND", "System Mail.app could not be verified at /System/Applications/Mail.app")
        MAIL_SDEF = MAIL_APP / "Contents" / "Resources" / "Mail.sdef"
    return MAIL_APP, MAIL_SDEF


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))


def canonical_hash(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def atomic_json(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp.open("w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write("\n")
    os.chmod(temp, mode)
    os.replace(temp, path)


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        value = json.load(fh)
    if not isinstance(value, dict):
        raise MailCtlError("INVALID_STATE", f"Expected a JSON object in {path}")
    return value


def run_command(argv: list[str], timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise MailCtlError("TIMEOUT", f"Command timed out after {timeout} seconds", {"argv": argv[:2]}) from exc


def call_mail(command: str, payload: dict[str, Any] | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    request = {
        "command": command,
        "poll_interval_seconds": POLICY["poll_interval_seconds"],
        "draft_verification_attempts": POLICY["draft_verification_attempts"],
        "send_verification_attempts": POLICY["send_verification_attempts"],
        **(payload or {}),
    }
    with tempfile.TemporaryDirectory(prefix="macos-mail-") as temp_dir:
        temp_path = Path(temp_dir)
        os.chmod(temp_path, 0o700)
        request_path = temp_path / "request.json"
        atomic_json(request_path, request)
        try:
            from mailctl.adapter import compiled_adapter

            _, mail_sdef = mail_paths()
            adapter = compiled_adapter(APPLESCRIPT, mail_sdef, STATE_ROOT, timeout)
        except RuntimeError as exc:
            raise MailCtlError("APPLESCRIPT_COMPILE_FAILED", str(exc)) from exc
        result = run_command(["/usr/bin/osascript", str(adapter), str(request_path)], timeout=timeout)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "-1743" in stderr or "Not authorized" in stderr:
            raise MailCtlError(
                "AUTOMATION_DENIED",
                "The current host is not allowed to automate Mail. Allow it in System Settings > Privacy & Security > Automation.",
                stderr,
            )
        raise MailCtlError("OSASCRIPT_FAILED", stderr or result.stdout.strip() or "osascript failed")
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MailCtlError("INVALID_APPLESCRIPT_RESPONSE", "Mail AppleScript returned invalid JSON", result.stdout[:1000]) from exc
    if not response.get("ok"):
        raise MailCtlError(str(response.get("code", "MAIL_ERROR")), str(response.get("error", "Mail operation failed")), response)
    return response


def mail_environment() -> dict[str, str]:
    """Bind a prepared send to the Mail dictionary and adapter actually used."""
    _, sdef = mail_paths()
    return {
        "fingerprint": canonical_hash(
            {"sdef": sha256_bytes(sdef.read_bytes()), "adapter": sha256_bytes(APPLESCRIPT.read_bytes())}
        )
    }


def valid_address(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise MailCtlError("INVALID_ADDRESS", "Email addresses must not contain line breaks")
    _, address = parseaddr(value)
    if not address or "@" not in address or address != value.strip():
        raise MailCtlError("INVALID_ADDRESS", f"Use a plain email address, not a display-name form: {value!r}")
    return address


def valid_subject(value: str) -> str:
    if not value.strip() or "\r" in value or "\n" in value:
        raise MailCtlError("INVALID_SUBJECT", "Subject must be nonempty and contain no line breaks")
    return value


def load_body(path_text: str) -> str:
    path = Path(path_text).expanduser().resolve()
    if not path.is_file():
        raise MailCtlError("BODY_FILE_NOT_FOUND", f"Body file not found: {path}")
    raw = path.read_bytes()
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MailCtlError("BODY_NOT_UTF8", f"Body file must be UTF-8: {path}") from exc
    return normalize_body_text(body)


def normalize_body_text(body: str) -> str:
    if not isinstance(body, str) or not body.strip():
        raise MailCtlError("EMPTY_BODY", "Message body must not be empty")
    return body.replace("\r\n", "\n").replace("\r", "\n")


def mailbox_path(args: argparse.Namespace, field: str = "mailbox") -> list[str]:
    json_value = getattr(args, f"{field}_json", None)
    text_value = getattr(args, field, None)
    if json_value:
        try:
            value = json.loads(json_value)
        except json.JSONDecodeError as exc:
            raise MailCtlError("INVALID_MAILBOX_PATH", f"Invalid {field} JSON") from exc
        if not isinstance(value, list) or not value or not all(isinstance(x, str) and x for x in value):
            raise MailCtlError("INVALID_MAILBOX_PATH", f"{field} JSON must be a nonempty string array")
        return value
    if not text_value:
        raise MailCtlError("MAILBOX_REQUIRED", f"--{field.replace('_', '-')} is required")
    return [text_value]


def message_ref(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "account": args.account,
        "mailbox_path": mailbox_path(args),
        "local_id": int(args.id),
        "rfc_message_id": getattr(args, "rfc_message_id", None) or "",
        "universal_id": getattr(args, "universal_id", None) or "",
    }


def public_record(record: dict[str, Any], include_body: bool = True) -> dict[str, Any]:
    result = dict(record)
    if not include_body:
        result.pop("body", None)
    return result


def attachment_inputs(path_values: list[str]) -> list[dict[str, Any]]:
    results = []
    seen: set[str] = set()
    for value in path_values:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise MailCtlError("ATTACHMENT_FILE_NOT_FOUND", f"Attachment file not found: {path}")
        if str(path) in seen:
            raise MailCtlError("DUPLICATE_ATTACHMENT", f"Attachment path was repeated: {path}")
        seen.add(str(path))
        results.append({"path": str(path), "name": path.name, "size": path.stat().st_size, "sha256": sha256_bytes(path.read_bytes())})
    return results


def send_canonical(
    operation: str,
    draft: dict[str, Any],
    source_ref: dict[str, Any] | None,
    reply_all: bool,
    sent_before: int,
    attachments: list[dict[str, Any]] | None = None,
    draft_outgoing_id: int = -1,
) -> dict[str, Any]:
    draft_ref = draft["message_ref"]
    identity_key = next((key for key in ("universal_id", "rfc_message_id", "local_id") if draft_ref.get(key)), None)
    if identity_key is None:
        raise MailCtlError("INVALID_DRAFT", "Draft has no stable Mail identifier")
    return {
        "operation": operation,
        "account_id": draft["account_id"],
        "draft_identity": {
            "account": draft_ref["account"], "mailbox_path": draft_ref["mailbox_path"],
            identity_key: draft_ref[identity_key],
        },
        "source_ref": source_ref,
        "reply_all": reply_all,
        "from": draft["sender"],
        "to": draft.get("to", []),
        "cc": draft.get("cc", []),
        "bcc": draft.get("bcc", []),
        "subject": draft["subject"],
        "body_sha256": sha256_text(draft.get("body", "")),
        "attachments": attachments or [],
        "sent_before": sent_before,
        "draft_outgoing_id": int(draft_outgoing_id),
    }


def send_prepared_payload(
    draft: dict[str, Any],
    operation: str,
    source_ref: dict[str, Any] | None,
    reply_all: bool,
    sent_before: int,
    attachment_paths: list[str],
    outgoing_id: int,
) -> dict[str, Any]:
    """Bind the approved draft to its original Mail outgoing object."""
    draft_ref = draft.get("message_ref")
    if not isinstance(draft_ref, dict) or not isinstance(draft_ref.get("account"), str):
        raise MailCtlError("INVALID_DRAFT", "Draft is missing its bound account reference")
    if outgoing_id < 1:
        raise MailCtlError("OUTGOING_NOT_BOUND", "Prepared draft has no bound Mail outgoing object")
    if not draft.get("to"):
        raise MailCtlError("RECIPIENT_REQUIRED", "Prepared Mail draft has no To recipient")
    return {
        "operation": operation,
        "account": draft_ref["account"],
        "from": str(draft.get("sender", "")),
        "to": list(draft.get("to", [])),
        "cc": list(draft.get("cc", [])),
        "bcc": list(draft.get("bcc", [])),
        "subject": str(draft.get("subject", "")),
        "body": str(draft.get("body", "")),
        "source_ref": source_ref,
        "reply_all": reply_all,
        "sent_before": sent_before,
        "attachments": attachment_paths,
        "outgoing_id": outgoing_id,
        "draft_ref": draft_ref,
    }


def bound_plan_hash(canonical: dict[str, Any], environment_fingerprint: str) -> str:
    return canonical_hash(
        {
            "operation": canonical,
            "environment_fingerprint": environment_fingerprint,
        }
    )


def save_plan(kind: str, canonical: dict[str, Any], extra: dict[str, Any]) -> tuple[Path, str]:
    plan_hash = bound_plan_hash(canonical, extra["environment_fingerprint"])
    now = date_now()
    plan_path = PLANS_DIR / f"{date_stamp()}-{uuid.uuid4().hex[:12]}.json"
    manifest = {
        "schema_version": 4,
        "kind": kind,
        "status": "prepared",
        "created_at": now,
        "plan_hash": plan_hash,
        **extra,
    }
    atomic_json(plan_path, manifest)
    return plan_path, plan_hash


def read_message(ref: dict[str, Any], body: str = "full", include_headers: bool = False, include_source: bool = False) -> dict[str, Any]:
    return call_mail(
        "read",
        {
            "message_ref": ref,
            "body_mode": body,
            "include_headers": include_headers,
            "include_source": include_source,
        },
    )["message"]


def parse_iso_age(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise MailCtlError("INVALID_DATE", f"Use ISO-8601 date or datetime: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return int(time.time() - parsed.timestamp())


def parse_iso_epoch(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise MailCtlError("INVALID_DATE", f"Use ISO-8601 date or datetime: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return int(parsed.timestamp())


def cmd_doctor(_: argparse.Namespace) -> dict[str, Any]:
    env = mail_environment()
    return {"ok": True, "operation": "doctor", **env}


def cmd_outgoing_windows(args: argparse.Namespace) -> dict[str, Any]:
    return call_mail(
        "outgoing_status",
        {"account": args.account, "subject_contains": args.subject_contains or ""},
        timeout=DEFAULT_TIMEOUT,
    )


def cmd_accounts(_: argparse.Namespace) -> dict[str, Any]:
    return call_mail("accounts")


def cmd_recent(args: argparse.Namespace) -> dict[str, Any]:
    try:
        return call_mail(
            "recent",
            {
                "limit": args.limit,
                "body_mode": args.body,
                "unread": bool(args.unread),
                "sender": args.sender or "",
                "subject": args.subject or "",
                "since_epoch_seconds": parse_iso_epoch(args.since),
                "before_epoch_seconds": parse_iso_epoch(args.before),
            },
            timeout=args.timeout,
        )
    except MailCtlError as exc:
        if isinstance(exc.details, dict) and exc.details.get("operation") == "recent" and exc.details.get("complete") is False:
            return exc.details
        return {"ok": False, "operation": "recent", "scope": "all-inboxes", "complete": False, "code": exc.code, "error": exc.message, "details": exc.details}


def load_action_refs(path_text: str) -> list[dict[str, Any]]:
    path = Path(path_text).expanduser().resolve()
    try:
        refs = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MailCtlError("INVALID_REFS_FILE", f"Cannot read message refs from {path}: {exc}") from exc
    return validate_action_refs(refs)


def validate_action_refs(refs: Any) -> list[dict[str, Any]]:
    if not isinstance(refs, list) or not 1 <= len(refs) <= POLICY["search_limit_max"]:
        raise MailCtlError("INVALID_REFS", "Refs file must contain a JSON array of 1 to 200 message refs")
    seen: set[tuple[str, tuple[str, ...], int]] = set()
    for index, ref in enumerate(refs):
        if not isinstance(ref, dict):
            raise MailCtlError("INVALID_REFS", f"Ref {index} must be an object")
        if not isinstance(ref.get("account"), str) or not ref["account"].strip():
            raise MailCtlError("INVALID_REFS", f"Ref {index} needs an account")
        path_items = ref.get("mailbox_path")
        if not isinstance(path_items, list) or not path_items or any(not isinstance(x, str) or not x for x in path_items):
            raise MailCtlError("INVALID_REFS", f"Ref {index} needs a nonempty mailbox_path array")
        if type(ref.get("local_id")) is not int or ref["local_id"] < 1:
            raise MailCtlError("INVALID_REFS", f"Ref {index} needs a positive local_id")
        for key in ("rfc_message_id", "universal_id"):
            if key in ref and not isinstance(ref[key], str):
                raise MailCtlError("INVALID_REFS", f"Ref {index} has an invalid {key}")
        key = (ref["account"].casefold(), tuple(path_items), ref["local_id"])
        if key in seen:
            raise MailCtlError("DUPLICATE_TARGET", f"Ref {index} repeats an earlier message")
        seen.add(key)
    return refs


def cmd_act(args: argparse.Namespace) -> dict[str, Any]:
    return act_messages(load_action_refs(args.refs_file), args.actions.split(","))


def act_messages(refs: list[dict[str, Any]], actions: list[str]) -> dict[str, Any]:
    refs = validate_action_refs(refs)
    if actions not in (["mark-read"], ["trash"], ["mark-read", "trash"]):
        raise MailCtlError("INVALID_ACTIONS", "Use mark-read, trash, or mark-read,trash")
    response = call_mail(
        "act",
        {"refs": refs, "actions": actions, "action_verification_attempts": 6},
        timeout=max(DEFAULT_TIMEOUT, 10 + 6 * len(refs)),
    )
    results = response.get("results", [])
    complete = bool(response.get("complete")) and len(results) == len(refs)
    for item in results:
        if not isinstance(item, dict) or not item.get("ok"):
            complete = False
            continue
        if "mark-read" in actions and not item.get("mark_read_verified"):
            complete = False
        if "mark-read" in actions and item.get("message", {}).get("read") is not True:
            complete = False
        if "trash" in actions and not (item.get("trash_verified") and item.get("removed_from_source") and item.get("trash_present")):
            complete = False
    response["complete"] = complete
    response["ok"] = complete
    return response


def cmd_mailboxes(args: argparse.Namespace) -> dict[str, Any]:
    return call_mail("mailboxes", {"account": args.account})


def cmd_search(args: argparse.Namespace) -> dict[str, Any]:
    if not any([args.subject, args.sender, args.recipient, args.since, args.before, args.unread]):
        raise MailCtlError("UNBOUNDED_SEARCH", "Provide a sender, recipient, subject, date window, or --unread")
    return call_mail(
        "search",
        {
            "account": args.account,
            "mailbox_path": mailbox_path(args),
            "subject": args.subject or "",
            "sender": args.sender or "",
            "recipient": args.recipient or "",
            "since_age_seconds": parse_iso_age(args.since),
            "before_age_seconds": parse_iso_age(args.before),
            "unread": bool(args.unread),
            "limit": args.limit,
            "body_mode": args.body,
        },
        timeout=args.timeout,
    )


def locator_identity(value: str) -> str:
    """Accept an exact sender address or a sufficiently specific display name."""
    compact = value.strip()
    if not compact:
        raise MailCtlError("LOCATOR_IDENTITY_REQUIRED", "Provide an exact sender address or at least two sender-name tokens")
    _, address = parseaddr(compact)
    if address and address == compact:
        try:
            return valid_address(compact)
        except MailCtlError:
            pass
    tokens = re.findall(r"[^\W_]+", compact, flags=re.UNICODE)
    if len(tokens) < 2:
        raise MailCtlError(
            "LOCATOR_IDENTITY_TOO_BROAD",
            "Use an exact sender address or at least two sender-name tokens for cross-account INBOX lookup",
        )
    return compact


def cmd_locate(args: argparse.Namespace) -> dict[str, Any]:
    """Find a recent sender across account INBOX folders in one read-only Mail call."""
    sender_identity = locator_identity(args.sender)
    since_epoch = parse_iso_epoch(args.since) if args.since else int(time.time()) - LOCATE_DEFAULT_WINDOW_SECONDS
    before_epoch = parse_iso_epoch(args.before)
    try:
        return call_mail(
            "locate",
            {
                "sender_identity": sender_identity,
                "subject": args.subject or "",
                "since_epoch_seconds": since_epoch,
                "before_epoch_seconds": before_epoch,
                "limit": args.limit,
                "read_if_unique": bool(args.read_if_unique),
                "body_mode": args.body,
                "include_headers": bool(args.include_headers),
                "include_source": bool(args.include_source),
            },
            timeout=args.timeout,
        )
    except MailCtlError as exc:
        if isinstance(exc.details, dict) and exc.details.get("operation") == "locate" and exc.details.get("complete") is False:
            return exc.details
        raise


def cmd_inspect(args: argparse.Namespace) -> dict[str, Any]:
    """Validate one explicit account/mailbox and search/read it in one Mail call."""
    if not any([args.subject, args.sender, args.recipient, args.since, args.before, args.unread]):
        raise MailCtlError("UNBOUNDED_SEARCH", "Provide a sender, recipient, subject, date window, or --unread")
    return call_mail(
        "inspect",
        {
            "account": args.account,
            "mailbox_path": mailbox_path(args),
            "subject": args.subject or "",
            "sender_identity": args.sender or "",
            "recipient": args.recipient or "",
            "since_age_seconds": parse_iso_age(args.since),
            "before_age_seconds": parse_iso_age(args.before),
            "unread": bool(args.unread),
            "limit": args.limit,
            "read_if_unique": bool(args.read_if_unique),
            "body_mode": args.body,
            "include_headers": bool(args.include_headers),
            "include_source": bool(args.include_source),
        },
        timeout=args.timeout,
    )


def cmd_read(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": "read",
        "message": read_message(message_ref(args), args.body, args.include_headers, args.include_source),
    }


def cmd_attachment_list(args: argparse.Namespace) -> dict[str, Any]:
    msg = read_message(message_ref(args), "none")
    return {"ok": True, "operation": "attachment-list", "message_ref": msg["message_ref"], "attachments": msg.get("attachments", [])}


def prepare_send(args: argparse.Namespace, operation: str) -> dict[str, Any]:
    attachments = attachment_inputs(getattr(args, "attach", []))
    environment = mail_environment()
    body = normalize_body_text(args.body_text) if hasattr(args, "body_text") else load_body(args.body_file)
    if operation == "new":
        payload = {
            "account": args.account,
            "from": valid_address(args.from_address),
            "to": [valid_address(x) for x in args.to],
            "cc": [valid_address(x) for x in args.cc],
            "bcc": [valid_address(x) for x in args.bcc],
            "subject": valid_subject(args.subject),
            "body": body,
            "attachments": [item["path"] for item in attachments],
        }
        result = call_mail("draft_new", payload, timeout=SEND_TIMEOUT)
        source_ref = None
        reply_all = False
    else:
        source_ref = message_ref(args)
        payload = {"message_ref": source_ref, "body": body, "attachments": [item["path"] for item in attachments]}
        if operation == "reply":
            payload["reply_all"] = bool(args.reply_all)
            result = call_mail("draft_reply", payload, timeout=SEND_TIMEOUT)
            reply_all = bool(args.reply_all)
        else:
            payload["to"] = [valid_address(x) for x in args.to]
            payload["cc"] = [valid_address(x) for x in args.cc]
            payload["bcc"] = [valid_address(x) for x in args.bcc]
            result = call_mail("draft_forward", payload, timeout=SEND_TIMEOUT)
            reply_all = False
    draft = result["draft"]
    sent_before = int(result["sent_before"])
    draft_outgoing_id = int(result.get("draft_outgoing_id", -1))
    if draft_outgoing_id < 1:
        raise MailCtlError("OUTGOING_NOT_BOUND", "Mail did not return a bound outgoing object for the prepared draft")
    canonical = send_canonical(operation, draft, source_ref, reply_all, sent_before, attachments, draft_outgoing_id)
    plan_path, _ = save_plan(
        "send",
        canonical,
        {
            "operation": operation,
            "draft_ref": draft["message_ref"],
            "source_ref": source_ref,
            "reply_all": reply_all,
            "sent_before": sent_before,
            "sender": draft["sender"],
            "to": draft.get("to", []),
            "subject": draft["subject"],
            "draft_outgoing_id": draft_outgoing_id,
            "attachments": attachments,
            "environment_fingerprint": environment["fingerprint"],
        },
    )
    return {
        "ok": True,
        "operation": f"prepare-{operation}",
        "plan_file": str(plan_path),
        "preview": {
            "sender": draft["sender"],
            "to": draft.get("to", []),
            "cc": draft.get("cc", []),
            "bcc": draft.get("bcc", []),
            "subject": draft["subject"],
            "body": draft.get("body", ""),
            "attachments": draft.get("attachments", []),
        },
        "verification": {
            "draft_count_delta": 1,
            "sent_before": sent_before,
        },
    }


def cmd_prepare_new(args: argparse.Namespace) -> dict[str, Any]:
    return prepare_send(args, "new")


def cmd_prepare_reply(args: argparse.Namespace) -> dict[str, Any]:
    return prepare_send(args, "reply")


def cmd_prepare_forward(args: argparse.Namespace) -> dict[str, Any]:
    return prepare_send(args, "forward")


def cmd_action(args: argparse.Namespace) -> dict[str, Any]:
    ref = message_ref(args)
    operation = args.operation
    destination = mailbox_path(args, "destination_mailbox") if operation == "move" else None
    result = call_mail(
        "apply_action",
        {"operation": operation, "message_ref": ref, "destination": destination},
        timeout=SEND_TIMEOUT,
    )
    if operation == "trash" and not result.get("trash_verified"):
        result["ok"] = False
    state_field = {"mark-read": ("read", True), "mark-unread": ("read", False), "flag": ("flagged", True), "unflag": ("flagged", False)}.get(operation)
    if state_field and result.get("message", {}).get(state_field[0]) is not state_field[1]:
        result["ok"] = False
        result["code"] = "STATE_VERIFICATION_FAILED"
    if operation == "move" and not result.get("message", {}).get("message_ref"):
        result["ok"] = False
        result["code"] = "MOVE_VERIFICATION_FAILED"
    return result


def cmd_attachment_save(args: argparse.Namespace) -> dict[str, Any]:
    ref = message_ref(args)
    record = read_message(ref, "none")
    matches = [item for item in record.get("attachments", []) if item["id"] == args.attachment_id]
    if len(matches) != 1:
        raise MailCtlError("ATTACHMENT_NOT_FOUND", f"Expected one attachment with id {args.attachment_id}; found {len(matches)}")
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not output_dir.is_dir():
        raise MailCtlError("OUTPUT_DIR_NOT_FOUND", f"Output directory not found: {output_dir}")
    safe_name = Path(matches[0]["name"]).name
    if not safe_name or safe_name in {".", ".."}:
        raise MailCtlError("UNSAFE_ATTACHMENT_NAME", "Attachment name is unsafe")
    output = output_dir / safe_name
    if output.exists():
        raise MailCtlError("NO_OVERWRITE", f"Refusing to overwrite: {output}")
    result = call_mail(
        "apply_action",
        {"operation": "save-attachment", "message_ref": record["message_ref"], "attachment_id": args.attachment_id, "output_path": str(output)},
        timeout=SEND_TIMEOUT,
    )
    if not output.is_file():
        raise MailCtlError("SAVE_VERIFICATION_FAILED", f"Attachment was not created: {output}")
    result["saved_sha256"] = sha256_bytes(output.read_bytes())
    result["saved_size"] = output.stat().st_size
    return result


def load_plan(path_text: str) -> tuple[Path, dict[str, Any]]:
    path = Path(path_text).expanduser().resolve()
    try:
        path.relative_to(PLANS_DIR.resolve())
    except ValueError as exc:
        raise MailCtlError("INVALID_PLAN_PATH", f"Plan must be under {PLANS_DIR}") from exc
    manifest = read_json(path)
    if manifest.get("schema_version") not in (3, 4) or manifest.get("kind") != "send":
        raise MailCtlError("INVALID_SEND_PLAN", "Only a current prepared send can be used")
    return path, manifest


def execute_send(path: Path, manifest: dict[str, Any], approved_hash: str) -> dict[str, Any]:
    draft = call_mail("read_role_message", {"role": "drafts", "message_ref": manifest["draft_ref"], "body_mode": "full"})["message"]
    attachments = attachment_inputs([item["path"] for item in manifest.get("attachments", [])])
    if attachments != manifest.get("attachments", []):
        raise MailCtlError("STALE_PLAN", "One or more attachment files changed after approval")
    canonical = send_canonical(
        manifest["operation"],
        draft,
        manifest.get("source_ref"),
        bool(manifest.get("reply_all")),
        int(manifest["sent_before"]),
        attachments,
        int(manifest.get("draft_outgoing_id", -1)),
    )
    current_hash = bound_plan_hash(canonical, manifest["environment_fingerprint"])
    if current_hash != approved_hash or current_hash != manifest["plan_hash"]:
        raise MailCtlError(
            "STALE_PLAN",
            "The Mail draft or its live context changed after approval.",
            {"approved_hash": approved_hash, "current_hash": current_hash, "preview": public_record(draft)},
        )
    payload = send_prepared_payload(
        draft, manifest["operation"], manifest.get("source_ref"),
        bool(manifest.get("reply_all")), int(manifest["sent_before"]),
        [item["path"] for item in attachments], int(manifest.get("draft_outgoing_id", -1)),
    )
    manifest.update({"status": "sending", "send_attempted_at": date_now()})
    atomic_json(path, manifest)
    result = call_mail(
        "send_plan",
        payload,
        timeout=SEND_TIMEOUT,
    )
    manifest.update(
        {
            "status": "sent" if result.get("sent_verified") else "ambiguous",
            "executed_at": date_now(),
            "sent_ref": result.get("sent", {}).get("message_ref"),
            "sent_verified_at_send": bool(result.get("sent_verified")),
            "draft_remaining": result.get("draft_remaining"),
        }
    )
    atomic_json(path, manifest)
    return {
        "ok": True,
        "operation": "execute-send",
        "plan_file": str(path),
        **result,
    }


def cmd_execute(args: argparse.Namespace) -> dict[str, Any]:
    path, manifest = load_plan(args.plan_file)
    if manifest.get("kind") != "send":
        raise MailCtlError("INVALID_PLAN_KIND", "Execute accepts prepared sends only")
    if manifest.get("schema_version") != 4:
        raise MailCtlError("STALE_PLAN", "Older prepared drafts cannot be sent with this version; prepare a new send")
    environment = mail_environment()
    if manifest.get("environment_fingerprint") and manifest["environment_fingerprint"] != environment["fingerprint"]:
        raise MailCtlError("STALE_PLAN", "The environment fingerprint changed after preparation")
    if manifest.get("status") != "prepared":
        raise MailCtlError("PLAN_NOT_PREPARED", f"Plan status is {manifest.get('status')!r}; refusing to execute again")
    return execute_send(path, manifest, manifest["plan_hash"])


def cmd_verify(args: argparse.Namespace) -> dict[str, Any]:
    path, manifest = load_plan(args.plan_file)
    if manifest.get("status") == "sent" and manifest.get("sent_ref"):
        return {
            "ok": True, "operation": "verify", "plan_file": str(path), "status": "sent",
            "sent_verified_at_send": manifest.get("sent_verified_at_send", True),
            "sent_ref": manifest["sent_ref"], "current_location": "not_checked",
            "draft_remaining_at_send": manifest.get("draft_remaining"),
        }
    if manifest.get("kind") == "send" and manifest.get("draft_ref"):
        try:
            draft = call_mail("read_role_message", {"role": "drafts", "message_ref": manifest["draft_ref"], "body_mode": "none"})["message"]
        except MailCtlError:
            draft = None
        sender = draft["sender"] if draft else manifest.get("sender", "")
        subject = draft["subject"] if draft else manifest.get("subject", "")
        recipients = draft.get("to", []) if draft else manifest.get("to", [])
        if not sender or not subject or not recipients:
            raise MailCtlError("VERIFY_CONTEXT_MISSING", "Cannot verify an ambiguous send without its bound envelope")
        count = call_mail(
            "count_sent",
            {"sender": sender, "subject": subject, "to": recipients},
        )["count"]
        return {
            "ok": True,
            "operation": "verify",
            "plan_file": str(path),
            "status": manifest["status"],
            "sent_before": manifest["sent_before"],
            "sent_now": count,
            "draft_present": draft is not None,
        }
    return {"ok": True, "operation": "verify", "plan_file": str(path), "status": manifest.get("status")}


def add_message_target(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", required=True)
    parser.add_argument("--mailbox")
    parser.add_argument("--mailbox-json")
    parser.add_argument("--id", required=True, type=int)
    parser.add_argument("--rfc-message-id")
    parser.add_argument("--universal-id")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("accounts").set_defaults(func=cmd_accounts)

    recent = sub.add_parser("recent", help="Newest received messages across every configured Inbox")
    recent.add_argument("--unread", action="store_true")
    recent.add_argument("--sender")
    recent.add_argument("--subject")
    recent.add_argument("--since", help="ISO-8601 inclusive start")
    recent.add_argument("--before", help="ISO-8601 exclusive end")
    recent.add_argument("--limit", type=int, default=3, choices=range(1, POLICY["search_limit_max"] + 1))
    recent.add_argument("--body", choices=["none", "excerpt", "full"], default="excerpt")
    recent.add_argument("--timeout", type=int, default=120)
    recent.set_defaults(func=cmd_recent)

    act = sub.add_parser("act", help="Apply one or two state changes to exact message refs in one Mail call")
    act.add_argument("--refs-file", required=True)
    act.add_argument("--actions", required=True)
    act.set_defaults(func=cmd_act)

    outgoing_windows = sub.add_parser("outgoing-windows")
    outgoing_windows.add_argument("--account", required=True)
    outgoing_windows.add_argument("--subject-contains")
    outgoing_windows.set_defaults(func=cmd_outgoing_windows)

    mailboxes = sub.add_parser("mailboxes")
    mailboxes.add_argument("--account", required=True)
    mailboxes.set_defaults(func=cmd_mailboxes)

    search = sub.add_parser("search")
    search.add_argument("--account", required=True)
    search.add_argument("--mailbox")
    search.add_argument("--mailbox-json")
    search.add_argument("--subject")
    search.add_argument("--sender")
    search.add_argument("--recipient")
    search.add_argument("--since")
    search.add_argument("--before")
    search.add_argument("--unread", action="store_true")
    search.add_argument(
        "--limit",
        type=int,
        default=POLICY["search_limit_default"],
        choices=range(1, POLICY["search_limit_max"] + 1),
        metavar=f"1..{POLICY['search_limit_max']}",
    )
    search.add_argument("--timeout", type=int, default=POLICY["command_timeout_seconds"])
    search.add_argument("--body", choices=["none", "excerpt", "full"], default="excerpt")
    search.set_defaults(func=cmd_search)

    locate = sub.add_parser("locate", help="Fast, read-only recent-INBOX lookup across local Mail accounts")
    locate.add_argument("--sender", required=True, help="Exact sender address or at least two display-name tokens")
    locate.add_argument("--subject")
    locate.add_argument("--since", help="ISO-8601 start; defaults to the last 14 days")
    locate.add_argument("--before", help="ISO-8601 exclusive end")
    locate.add_argument(
        "--limit",
        type=int,
        default=POLICY["search_limit_default"],
        choices=range(1, POLICY["search_limit_max"] + 1),
        metavar=f"1..{POLICY['search_limit_max']}",
    )
    locate.add_argument("--read-if-unique", action="store_true", help="Read only when exactly one candidate is found")
    locate.add_argument("--body", choices=["none", "excerpt", "full"], default="excerpt")
    locate.add_argument("--include-headers", action="store_true")
    locate.add_argument("--include-source", action="store_true")
    locate.add_argument("--timeout", type=int, default=POLICY["command_timeout_seconds"])
    locate.set_defaults(func=cmd_locate)

    inspect = sub.add_parser("inspect", help="Fast, read-only validated lookup within one explicit account mailbox")
    inspect.add_argument("--account", required=True)
    inspect.add_argument("--mailbox")
    inspect.add_argument("--mailbox-json")
    inspect.add_argument("--subject")
    inspect.add_argument("--sender")
    inspect.add_argument("--recipient")
    inspect.add_argument("--since")
    inspect.add_argument("--before")
    inspect.add_argument("--unread", action="store_true")
    inspect.add_argument(
        "--limit",
        type=int,
        default=POLICY["search_limit_default"],
        choices=range(1, POLICY["search_limit_max"] + 1),
        metavar=f"1..{POLICY['search_limit_max']}",
    )
    inspect.add_argument("--read-if-unique", action="store_true", help="Read only when exactly one candidate is found")
    inspect.add_argument("--body", choices=["none", "excerpt", "full"], default="excerpt")
    inspect.add_argument("--include-headers", action="store_true")
    inspect.add_argument("--include-source", action="store_true")
    inspect.add_argument("--timeout", type=int, default=POLICY["command_timeout_seconds"])
    inspect.set_defaults(func=cmd_inspect)

    read = sub.add_parser("read")
    add_message_target(read)
    read.add_argument("--body", choices=["none", "excerpt", "full"], default="excerpt")
    read.add_argument("--include-headers", action="store_true")
    read.add_argument("--include-source", action="store_true")
    read.set_defaults(func=cmd_read)

    attachment_list = sub.add_parser("attachment-list")
    add_message_target(attachment_list)
    attachment_list.set_defaults(func=cmd_attachment_list)

    new = sub.add_parser("prepare-new")
    new.add_argument("--account", required=True)
    new.add_argument("--from", dest="from_address", required=True)
    new.add_argument("--to", action="append", required=True)
    new.add_argument("--cc", action="append", default=[])
    new.add_argument("--bcc", action="append", default=[])
    new.add_argument("--subject", required=True)
    new.add_argument("--body-file", required=True)
    new.add_argument("--attach", action="append", default=[])
    new.set_defaults(func=cmd_prepare_new)

    reply = sub.add_parser("prepare-reply")
    add_message_target(reply)
    reply.add_argument("--body-file", required=True)
    reply.add_argument("--reply-all", action="store_true")
    reply.add_argument("--attach", action="append", default=[])
    reply.set_defaults(func=cmd_prepare_reply)

    forward = sub.add_parser("prepare-forward")
    add_message_target(forward)
    forward.add_argument("--to", action="append", required=True)
    forward.add_argument("--cc", action="append", default=[])
    forward.add_argument("--bcc", action="append", default=[])
    forward.add_argument("--body-file", required=True)
    forward.add_argument("--attach", action="append", default=[])
    forward.set_defaults(func=cmd_prepare_forward)

    action = sub.add_parser("action")
    action.add_argument("--operation", required=True, choices=["mark-read", "mark-unread", "flag", "unflag", "move", "trash"])
    add_message_target(action)
    action.add_argument("--destination-mailbox")
    action.add_argument("--destination-mailbox-json")
    action.set_defaults(func=cmd_action)

    attachment_save = sub.add_parser("attachment-save")
    add_message_target(attachment_save)
    attachment_save.add_argument("--attachment-id", required=True)
    attachment_save.add_argument("--output-dir", required=True)
    attachment_save.set_defaults(func=cmd_attachment_save)

    execute = sub.add_parser("execute")
    execute.add_argument("--plan-file", required=True)
    execute.set_defaults(func=cmd_execute)

    verify = sub.add_parser("verify")
    verify.add_argument("--plan-file", required=True)
    verify.set_defaults(func=cmd_verify)
    return parser


def main() -> int:
    parser = build_parser()
    try:
        args = parser.parse_args()
        result = args.func(args)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0 if result.get("ok") else 3
    except MailCtlError as exc:
        print(
            json.dumps(
                {"ok": False, "code": exc.code, "error": exc.message, "details": exc.details},
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
