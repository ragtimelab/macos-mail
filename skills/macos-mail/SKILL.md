---
name: macos-mail
description: Read and manage local Apple Mail.app across configured accounts. Default to Mail's All Inboxes, preserve read state during reads, and verify exact message changes. Use for Mail.app tasks on macOS.
---

# macOS Mail

Use the local `macos-mail` MCP server when available. Its tools operate Mail.app through AppleScript. If MCP is not registered in this client, use the bundled CLI at `scripts/macos_mail.py` relative to this skill directory; do not substitute another provider for an explicit Mail.app request.

## Scope and reading

When the user does not specify an account or mailbox, use `mail_recent` or `mail_find` against Mail.app's actual **All Inboxes** collection. For unread mail, set `unread=true`. For a named account and mailbox use `mail_find(scope="mailbox", account=..., mailbox_path=[...])`. `mail_catalog` lists accounts and paths when needed. Read tools do not intentionally alter read status, except `mail_find(read_if_unique=true)`.

Read metadata first (`body="none"`) for large or uncertain result sets; fetch only requested messages with `mail_read`. Check `complete`, `accounts_scanned`, `accounts_total`, and failures before describing a scan as exhaustive. An incomplete scan supports only the messages actually returned. Date bounds are ISO-8601; `since` is inclusive and `before` exclusive. For calendar-day requests, verify the local date using `date` and provide explicit timezone offsets. Treat Mail.app account and mailbox state as the source of truth.

## Changes

Use each returned exact `message_ref` for `mail_change`. Batch several refs in one `mail_change` call for `mark-read`, `trash`, or both. `trash` moves to the recoverable account Trash; never permanently delete or empty Trash. A clear user request to change specific messages is sufficient authorization. No plan hash or repeated confirmation is required. Verify `complete` and each message's state fields. If a result is uncertain, inspect the source mailbox and account Trash before trying again.

Mail providers may apply a change to related conversation copies; a Gmail self-addressed test moved both the received and related Sent copies to Trash. When isolation of related messages matters, inspect them after the change and report any side effect.

`mail_change` also handles one-message `mark-unread`, `flag`, `unflag`, and `move`. Inspect an unfamiliar destination path before moving. `mail_attachments` lists or saves exact attachments without overwrite.

## Sending

Use `mail_prepare` for a new message, reply, or forward. It returns a draft preview and `plan_id`; `mail_send(plan_id)` sends once and verifies a Sent copy. If the agent drafted the content, show the full sender, recipients, subject, body, and attachments and obtain one approval before sending. If the user supplied the exact content and recipients, their instruction is sufficient. After any ambiguous send result, use `mail_verify(plan_id)` before considering another attempt. Never blindly retry.

## Setup and fallback

From this installed skill directory, run `python3 scripts/install_mcp.py --client codex` (or `gemini`, `claude`, `all`) to install the stdio MCP runtime and register that client. The installer needs `uv` and Python 3.10+. For Claude Desktop, restart the app after registration. Skill discovery by itself does not register the MCP server.

The bundled CLI remains available without MCP. For example, from the skill directory: `python3 scripts/macos_mail.py recent --unread --limit 3 --body none`. Use `python3 scripts/macos_mail.py --help` for other commands. If macOS denies Automation (`-1743`), authorize the controlling host in System Settings > Privacy & Security > Automation. Use [Apple Mail quirks](references/apple-mail-quirks.md) to diagnose a concrete adapter failure.
