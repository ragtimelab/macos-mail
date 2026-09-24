#!/usr/bin/env python3
"""Local stdio MCP tools for the user's Apple Mail.app."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
import tempfile
import uuid
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from mailctl import service


class MessageRef(BaseModel):
    """Exact Mail account, mailbox and message identity returned by read tools."""

    model_config = ConfigDict(extra="forbid")

    account: str = Field(min_length=1)
    mailbox_path: list[str] = Field(min_length=1)
    local_id: StrictInt = Field(gt=0)
    rfc_message_id: str = ""
    universal_id: str = ""

    @field_validator("mailbox_path")
    @classmethod
    def nonempty_path(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("Mailbox path segments must be nonempty")
        return value


server = MCPServer(
    name="macos-mail-mcp",
    title="macOS Mail MCP",
    description="Read and manage the local Apple Mail.app across its configured accounts.",
    instructions=(
        "Default to All Inboxes when no account is specified. Read tools preserve unread state. "
        "Use returned message_ref values for changes. Check complete and per-message verification. "
        "Do not retry an uncertain send, permanently delete mail, or empty Trash."
    ),
    version="0.4.0",
)


async def _call(function: Any, *args: Any) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(function, *args)
    except service.MailCtlError as exc:
        return {"ok": False, "code": exc.code, "error": exc.message, "details": exc.details}
    except Exception as exc:
        return {"ok": False, "code": "INTERNAL_ERROR", "error": type(exc).__name__}


def _target(ref: MessageRef) -> dict[str, Any]:
    return ref.model_dump()


def _target_args(ref: MessageRef) -> dict[str, Any]:
    return {
        "account": ref.account,
        "mailbox_json": json.dumps(ref.mailbox_path, ensure_ascii=False),
        "mailbox": None,
        "id": ref.local_id,
        "rfc_message_id": ref.rfc_message_id,
        "universal_id": ref.universal_id,
    }


class SendSession:
    """Keep send attempts in one MCP process; signed tokens allow later read-only checks."""

    def __init__(self) -> None:
        self.session_id = uuid.uuid4().hex
        self._guard = threading.Lock()
        self._records: dict[str, dict[str, Any]] = {}
        self._key: bytes | None = None

    def _signing_key(self) -> bytes:
        if self._key is not None:
            return self._key
        root = service.STATE_ROOT
        if root.is_symlink():
            raise service.MailCtlError("INVALID_STATE", "Runtime state cannot be a symlink")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        path = root / "send-token.key"
        if path.is_symlink():
            raise service.MailCtlError("INVALID_STATE", "Send token key cannot be a symlink")
        if not path.exists():
            fd, temporary = tempfile.mkstemp(prefix=".send-key-", dir=root)
            try:
                with os.fdopen(fd, "wb") as handle:
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write(secrets.token_bytes(32))
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(temporary, path, follow_symlinks=False)
                except FileExistsError:
                    pass
            finally:
                os.unlink(temporary)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as exc:
            raise service.MailCtlError("INVALID_STATE", "Cannot open send token key") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise service.MailCtlError("INVALID_STATE", "Send token key is not a private regular file")
            key = os.read(fd, 33)
        finally:
            os.close(fd)
        if len(key) != 32:
            raise service.MailCtlError("INVALID_STATE", "Send token key has an invalid length")
        self._key = key
        return key

    def issue(self, plan: dict[str, Any]) -> str:
        nonce = secrets.token_hex(16)
        payload = {"v": 1, "session": self.session_id, "nonce": nonce,
                   "created_at": plan["created_at"], "draft_ref": plan["draft_ref"],
                   "sender": plan["sender"], "to": plan["to"], "subject": plan["subject"],
                   "sent_before": plan["sent_before"], "body_sha256": plan["body_sha256"]}
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signed = raw + hmac.digest(self._signing_key(), raw, "sha256")
        token = base64.urlsafe_b64encode(signed).rstrip(b"=").decode("ascii")
        with self._guard:
            self._records[nonce] = {"status": "prepared", "plan": plan, "result": None}
        return token

    def decode(self, token: str) -> dict[str, Any]:
        if len(token) > 8192 or not token or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in token):
            raise service.MailCtlError("INVALID_PLAN_TOKEN", "Use the token returned by mail_prepare")
        try:
            signed = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            raw, signature = signed[:-32], signed[-32:]
            if len(signature) != 32 or not hmac.compare_digest(signature, hmac.digest(self._signing_key(), raw, "sha256")):
                raise ValueError("signature")
            payload = json.loads(raw)
            if (not isinstance(payload, dict) or payload.get("v") != 1
                    or not isinstance(payload.get("session"), str)
                    or not isinstance(payload.get("nonce"), str)
                    or not isinstance(payload.get("created_at"), str)
                    or not isinstance(payload.get("draft_ref"), dict)
                    or not isinstance(payload.get("sender"), str)
                    or not isinstance(payload.get("to"), list)
                    or not all(isinstance(address, str) for address in payload["to"])
                    or not isinstance(payload.get("subject"), str)
                    or type(payload.get("sent_before")) is not int
                    or not isinstance(payload.get("body_sha256"), str)):
                raise ValueError("payload")
            return payload
        except (ValueError, TypeError, KeyError) as exc:
            raise service.MailCtlError("INVALID_PLAN_TOKEN", "Invalid send token") from exc

    def consume(self, token: str) -> dict[str, Any]:
        payload = self.decode(token)
        if payload.get("session") != self.session_id:
            raise service.MailCtlError("SESSION_EXPIRED", "This send token belongs to an earlier MCP session; verify Mail before preparing again")
        with self._guard:
            record = self._records.get(payload["nonce"])
            if record is None or record["status"] != "prepared":
                raise service.MailCtlError("PLAN_NOT_PREPARED", "This send token has already been used or is unavailable")
            record["status"] = "attempted"
            return record["plan"]

    def finish(self, token: str) -> None:
        payload = self.decode(token)
        with self._guard:
            self._records.pop(payload["nonce"], None)


_send_session = SendSession()


def _execute_bound_send(token: str) -> dict[str, Any]:
    with service.locked_send():
        plan = _send_session.consume(token)
        try:
            return service.execute_send(plan)
        finally:
            _send_session.finish(token)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True), structured_output=True)
async def mail_recent(
    unread: bool = False,
    limit: int = Field(default=3, ge=1, le=200),
    body: Literal["auto", "none", "excerpt", "full"] = "auto",
    sender: str | None = None,
    subject: str | None = None,
    since: str | None = None,
    before: str | None = None,
) -> dict[str, Any]:
    """Newest messages across All Inboxes. Auto reads up to 3 excerpts; subject filters or larger lists return metadata. Use mail_read for selected bodies."""
    args = argparse.Namespace(unread=unread, limit=limit, body=body, sender=sender, subject=subject,
                              since=since, before=before, timeout=120)
    return await _call(service.cmd_recent, args)


@server.tool(annotations=ToolAnnotations(openWorldHint=True), structured_output=True)
async def mail_find(
    scope: Literal["all_inboxes", "mailbox"],
    sender: str | None = None,
    account: str | None = None,
    mailbox_path: list[str] | None = None,
    subject: str | None = None,
    recipient: str | None = None,
    since: str | None = None,
    before: str | None = None,
    unread: bool = False,
    read_if_unique: bool = False,
    body: Literal["none", "excerpt", "full"] = "excerpt",
    limit: int | None = Field(default=None, ge=1, le=200),
    page_token: str | None = None,
    include_total: bool = False,
    include_headers: bool = False,
    include_source: bool = False,
) -> dict[str, Any]:
    """Find sender or subject across All Inboxes with 20-result pages, or inspect one mailbox. No implicit date cutoff. Follow next_page_token; include_total is slower. read_if_unique fetches one unique body without changing read status."""
    if scope == "all_inboxes":
        if account or mailbox_path or recipient or not ((sender or "").strip() or (subject or "").strip()):
            return {"ok": False, "code": "INVALID_SCOPE", "error": "All Inboxes find requires sender or subject and does not accept account, mailbox or recipient"}
        args = argparse.Namespace(sender=sender, subject=subject, since=since, before=before,
                                  unread=unread, read_if_unique=read_if_unique, body=body, limit=20 if limit is None else limit,
                                  page_token=page_token, include_total=include_total,
                                  include_headers=include_headers, include_source=include_source, timeout=120)
        return await _call(service.cmd_locate, args)
    if page_token or include_total:
        return {"ok": False, "code": "INVALID_SCOPE", "error": "Pagination and total count apply only to All Inboxes find"}
    if not account or not mailbox_path or any(not item for item in mailbox_path):
        return {"ok": False, "code": "INVALID_SCOPE", "error": "Mailbox find requires account and mailbox_path"}
    args = argparse.Namespace(account=account, mailbox_json=json.dumps(mailbox_path, ensure_ascii=False),
                              mailbox=None, sender=sender, subject=subject, recipient=recipient,
                              since=since, before=before, unread=unread, read_if_unique=read_if_unique,
                              body=body, limit=service.POLICY["search_limit_default"] if limit is None else limit,
                              include_headers=include_headers,
                              include_source=include_source, timeout=120)
    return await _call(service.cmd_inspect, args)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True), structured_output=True)
async def mail_read(
    message_ref: MessageRef,
    body: Literal["none", "excerpt", "full"] = "full",
    include_headers: bool = False,
    include_source: bool = False,
) -> dict[str, Any]:
    """Read one exact message without intentionally changing its read status."""
    args = argparse.Namespace(**_target_args(message_ref), body=body,
                              include_headers=include_headers, include_source=include_source)
    return await _call(service.cmd_read, args)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False), structured_output=True)
async def mail_catalog(kind: Literal["accounts", "mailboxes"], account: str | None = None) -> dict[str, Any]:
    """List configured Mail accounts or the mailboxes of one account."""
    if kind == "mailboxes" and not account:
        return {"ok": False, "code": "ACCOUNT_REQUIRED", "error": "Account is required for mailboxes"}
    function = service.cmd_accounts if kind == "accounts" else service.cmd_mailboxes
    return await _call(function, argparse.Namespace(account=account))


@server.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True), structured_output=True)
async def mail_change(
    refs: list[MessageRef],
    actions: list[Literal["mark-read", "mark-unread", "flag", "unflag", "move", "trash"]],
    destination_mailbox_path: list[str] | None = None,
) -> dict[str, Any]:
    """Change exact refs; batch read/Trash. Mail providers may also affect related conversation copies."""
    if actions in (["mark-read"], ["trash"], ["mark-read", "trash"]):
        if destination_mailbox_path is not None:
            return {"ok": False, "code": "INVALID_DESTINATION", "error": "Destination applies only to move"}
        return await _call(service.act_messages, [_target(ref) for ref in refs], actions)
    if len(refs) != 1 or len(actions) != 1 or actions[0] not in ("mark-unread", "flag", "unflag", "move"):
        return {"ok": False, "code": "INVALID_ACTIONS", "error": "Use one target for mark-unread, flag, unflag or move"}
    if actions[0] == "move" and (not destination_mailbox_path or any(not item for item in destination_mailbox_path)):
        return {"ok": False, "code": "DESTINATION_REQUIRED", "error": "Move requires destination_mailbox_path"}
    if actions[0] != "move" and destination_mailbox_path is not None:
        return {"ok": False, "code": "INVALID_DESTINATION", "error": "Destination applies only to move"}
    args = argparse.Namespace(**_target_args(refs[0]), operation=actions[0],
                              destination_mailbox=None,
                              destination_mailbox_json=json.dumps(destination_mailbox_path, ensure_ascii=False) if destination_mailbox_path else None)
    return await _call(service.cmd_action, args)


@server.tool(annotations=ToolAnnotations(destructiveHint=False, openWorldHint=True), structured_output=True)
async def mail_attachments(
    message_ref: MessageRef,
    operation: Literal["list", "save"] = "list",
    attachment_id: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """List received attachments or save one exact attachment without overwriting."""
    if operation == "save" and (not attachment_id or not output_dir):
        return {"ok": False, "code": "ATTACHMENT_ARGUMENTS_REQUIRED", "error": "Save requires attachment_id and output_dir"}
    args = argparse.Namespace(**_target_args(message_ref), attachment_id=attachment_id, output_dir=output_dir)
    return await _call(service.cmd_attachment_list if operation == "list" else service.cmd_attachment_save, args)


@server.tool(annotations=ToolAnnotations(destructiveHint=False, openWorldHint=True), structured_output=True)
async def mail_prepare(
    kind: Literal["new", "reply", "forward"],
    body: str,
    account: str | None = None,
    from_address: str | None = None,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    subject: str | None = None,
    source_ref: MessageRef | None = None,
    reply_all: bool = False,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    """Prepare a bound Mail draft; return its preview and a session-bound send token."""
    if kind == "new" and (not account or not from_address or not to or not subject or source_ref):
        return {"ok": False, "code": "INVALID_PREPARE_ARGS", "error": "New mail needs account, from_address, to and subject"}
    if kind != "new" and source_ref is None:
        return {"ok": False, "code": "SOURCE_REQUIRED", "error": "Reply and forward need source_ref"}
    if kind == "forward" and not to:
        return {"ok": False, "code": "RECIPIENT_REQUIRED", "error": "Forward needs to"}
    values = _target_args(source_ref) if source_ref else {}
    values.update(account=source_ref.account if source_ref else account,
                  from_address=from_address, to=to or [], cc=cc or [], bcc=bcc or [],
                  subject=subject, body_text=body, attach=attachments or [], reply_all=reply_all)
    args = argparse.Namespace(**values)
    try:
        _send_session._signing_key()
    except service.MailCtlError as exc:
        return {"ok": False, "code": exc.code, "error": exc.message}
    result = await _call(service.prepare_send, args, kind)
    if result.get("ok") and result.get("session_plan"):
        result["plan_token"] = _send_session.issue(result.pop("session_plan"))
    return result


@server.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True), structured_output=True)
async def mail_send(plan_token: str) -> dict[str, Any]:
    """Send the prepared Mail outgoing object once; verify Sent and never auto-retry."""
    return await _call(_execute_bound_send, plan_token)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False), structured_output=True)
async def mail_verify(plan_token: str) -> dict[str, Any]:
    """Inspect current session results or Mail evidence without resending."""
    try:
        payload = _send_session.decode(plan_token)
    except service.MailCtlError as exc:
        return {"ok": False, "code": exc.code, "error": exc.message}
    return await _call(service.verify_send_evidence, payload)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False), structured_output=True)
async def mail_diagnose(
    kind: Literal["environment", "outgoing"],
    account: str | None = None,
    subject_contains: str | None = None,
) -> dict[str, Any]:
    """Inspect Mail automation or one account's outgoing windows when diagnosing a failure."""
    if kind == "outgoing" and not account:
        return {"ok": False, "code": "ACCOUNT_REQUIRED", "error": "Outgoing diagnosis requires account"}
    function = service.cmd_doctor if kind == "environment" else service.cmd_outgoing_windows
    return await _call(function, argparse.Namespace(account=account, subject_contains=subject_contains))


if __name__ == "__main__":
    server.run(transport="stdio")
