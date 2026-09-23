#!/usr/bin/env python3
"""Local stdio MCP tools for the user's Apple Mail.app."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
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
    name="macos-mail",
    title="macOS Mail",
    description="Read and manage the local Apple Mail.app across its configured accounts.",
    instructions=(
        "Default to All Inboxes when no account is specified. Read tools preserve unread state. "
        "Use returned message_ref values for changes. Check complete and per-message verification. "
        "Do not retry an uncertain send, permanently delete mail, or empty Trash."
    ),
    version="0.1.3",
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


def _plan_path(plan_id: str) -> str:
    if not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{12}", plan_id):
        raise service.MailCtlError("INVALID_PLAN_ID", "Use the plan_id returned by mail_prepare")
    return str(service.PLANS_DIR / f"{plan_id}.json")


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True), structured_output=True)
async def mail_recent(
    unread: bool = False,
    limit: int = Field(default=3, ge=1, le=200),
    body: Literal["none", "excerpt", "full"] = "excerpt",
    sender: str | None = None,
    subject: str | None = None,
    since: str | None = None,
    before: str | None = None,
) -> dict[str, Any]:
    """Newest messages across Mail.app's actual All Inboxes; report incomplete scans."""
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
    limit: int = Field(default=50, ge=1, le=200),
    include_headers: bool = False,
    include_source: bool = False,
) -> dict[str, Any]:
    """Find mail across All Inboxes or one mailbox. read_if_unique marks a unique result as read."""
    if scope == "all_inboxes":
        if not sender or account or mailbox_path or recipient or unread:
            return {"ok": False, "code": "INVALID_SCOPE", "error": "All Inboxes find requires sender and does not accept account, mailbox, recipient or unread"}
        args = argparse.Namespace(sender=sender, subject=subject, since=since, before=before,
                                  read_if_unique=read_if_unique, body=body, limit=limit,
                                  include_headers=include_headers, include_source=include_source, timeout=120)
        return await _call(service.cmd_locate, args)
    if not account or not mailbox_path or any(not item for item in mailbox_path):
        return {"ok": False, "code": "INVALID_SCOPE", "error": "Mailbox find requires account and mailbox_path"}
    args = argparse.Namespace(account=account, mailbox_json=json.dumps(mailbox_path, ensure_ascii=False),
                              mailbox=None, sender=sender, subject=subject, recipient=recipient,
                              since=since, before=before, unread=unread, read_if_unique=read_if_unique,
                              body=body, limit=limit, include_headers=include_headers,
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
    """Prepare and verify a bound Mail draft; return its preview and internal plan_id."""
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
    result = await _call(service.prepare_send, args, kind)
    if result.get("ok") and result.get("plan_file"):
        result["plan_id"] = Path(result.pop("plan_file")).stem
    return result


@server.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True), structured_output=True)
async def mail_send(plan_id: str) -> dict[str, Any]:
    """Send the prepared Mail outgoing object once; verify Sent and never auto-retry."""
    try:
        path = _plan_path(plan_id)
    except service.MailCtlError as exc:
        return {"ok": False, "code": exc.code, "error": exc.message}
    result = await _call(service.cmd_execute, argparse.Namespace(plan_file=path))
    result.pop("plan_file", None)
    return result


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False), structured_output=True)
async def mail_verify(plan_id: str) -> dict[str, Any]:
    """Inspect a send receipt or unresolved plan without resending; location is separate."""
    try:
        path = _plan_path(plan_id)
    except service.MailCtlError as exc:
        return {"ok": False, "code": exc.code, "error": exc.message}
    result = await _call(service.cmd_verify, argparse.Namespace(plan_file=path))
    result.pop("plan_file", None)
    return result


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
