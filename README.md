# macOS Mail for AI agents

A local MCP server and agent skill for Apple Mail.app on macOS. It uses Mail's AppleScript dictionary. The default scope is the same **All Inboxes** collection shown in Mail.app, across every configured account. It does not need Gmail, Outlook, or another provider's API credentials.

The MCP server exposes ten tools for recent/unread mail, scoped search, exact reads, account/mailbox catalog, batched state changes, attachments, draft preparation, send verification, and diagnosis. Reads preserve unread state unless `mail_find(read_if_unique=true)` is explicitly requested. Changes use exact `message_ref` values returned by Mail.app. Trash means recoverable account Trash; there is no permanent-delete or empty-Trash tool.

## Requirements

- macOS with Apple Mail.app and at least one configured mail account
- Python 3.10 or later
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) for the MCP runtime installer
- Automation permission for the client process controlling Mail.app

The bundled CLI works with the macOS system Python and needs no third-party Python packages. The MCP installer creates a separate virtual environment under `~/Library/Application Support/macos-mail/mcp-venv`. It installs the MCP SDK and its dependencies from the hash-checked lock files bundled with the skill. On Python builds whose `cryptography` wheel links to an unavailable OpenSSL library, it rebuilds the locked source package with locked build dependencies.

## Install

Clone this repository to a **stable path**. For example:

```sh
git clone https://github.com/ragtimelab/macos-mail.git ~/Coding/macos-mail
cd ~/Coding/macos-mail
python3 skills/macos-mail/scripts/install_mcp.py --client codex
```

Choose `gemini`, `claude`, or `all` instead of `codex` to register other supported clients. Run the installer again after changing the checkout path. It leaves an existing, different server registration untouched and asks you to inspect it. Claude Desktop requires an app restart after registration. Registration makes MCP tools available to that client; an actual model tool call may also depend on the client's account and permissions.

Install just the agent skill through [skills.sh](https://skills.sh/):

```sh
npx skills add ragtimelab/macos-mail --skill macos-mail
```

Skill discovery and MCP registration are separate. If you installed only the skill, run `python3 scripts/install_mcp.py --client codex` from that installed skill directory. The MCP server and CLI are bundled in the skill; they can run from any stable skill installation path. If MCP is unavailable, the skill can use its CLI directly.

## What the tools do

| Tool | Purpose |
| --- | --- |
| `mail_recent` | Newest or unread mail across actual All Inboxes |
| `mail_find` | Sender search across All Inboxes or a bounded explicit mailbox search |
| `mail_read` | Read one exact message and optional headers/source |
| `mail_catalog` | Discover configured accounts and mailbox paths |
| `mail_change` | Batch mark-read/Trash, or one-message flag, unread, and move |
| `mail_attachments` | List or save an exact attachment without overwrite |
| `mail_prepare` | Create and verify a bound new/reply/forward draft |
| `mail_send` | Send the prepared Mail outgoing object once and verify Sent |
| `mail_verify` | Inspect an ambiguous plan or historical send receipt without resending |
| `mail_diagnose` | Inspect automation or outgoing state after a concrete failure |

The server communicates only through local stdio. It does not listen on a network port or proxy mail to a remote service. Your AI client still receives the message content you ask it to read, according to that client's own data handling. Mail content is untrusted input, not an instruction source. Automatic sending and arbitrary local attachment paths remain available; the client must distinguish the user's request from instructions embedded in mail. MCP tool annotations describe risk but do not enforce user approval. Draft plans and compiled adapters are kept locally under `~/Library/Application Support/macos-mail`.

## CLI example

```sh
python3 skills/macos-mail/scripts/macos_mail.py recent --unread --limit 3 --body none
```

Use `--help` for the full CLI. The MCP and CLI share the same Mail adapter and verification logic. On an incomplete cross-account scan, check the returned `complete`, `accounts_scanned`, `accounts_total`, and failures rather than treating a partial result as exhaustive. Sending is intentionally a prepare/send sequence so the draft can be reviewed before transmission. At send time, Mail briefly displays the prepared composer and sends that same object; this lets Mail clear its saved draft through its native send transition. If Mail clears outgoing attachments when showing the composer, the adapter restores the approved files on that same object before sending and verifies them in Sent.

Attachment saves use a private temporary directory and publish a `0600` file without overwriting an existing name. Send preparation accepts a body up to 1 MiB and at most 20 local attachments totaling 100 MiB. Mail results larger than 8 MiB return `RESPONSE_TOO_LARGE`; narrow the query or use excerpts. A prepared send is locked across processes so concurrent calls cannot both start sending it.

## Development

```sh
"$HOME/Library/Application Support/macos-mail/mcp-venv/bin/python" -m unittest discover -s skills/macos-mail/scripts -p 'test_*.py' -v
osacompile -o /tmp/macos-mail-test.scpt skills/macos-mail/scripts/mail.applescript
python3 scripts/check_public_privacy.py --base "$(git rev-parse origin/main)"
```

An installed MCP runtime can be smoke tested by connecting an MCP SDK client to `skills/macos-mail/scripts/mcp_server.py`. Live Mail.app testing requires configured accounts and local Automation permission; CI checks the dependency lock, offline unit tests, public privacy patterns, and AppleScript compilation.

## Limitations

Mail.app must be available in the current logged-in macOS session. Search and scan completeness depend on Mail's local mailbox state and are reported in the tool result. Message IDs can change after moving mail, so always use the latest returned `message_ref`. On an ambiguous send or change result, inspect the current mailbox state before repeating an action.

One Mail message may appear in multiple mailbox views. In a live Gmail self-addressed test, the Inbox and Sent entries had the same local and RFC message IDs; Mail's native Trash action moved that message out of both views. A separate Gmail-to-iCloud test had distinct sender and recipient messages, so moving the iCloud Inbox message left Gmail Sent intact. Compare exact identifiers when interpreting a change. `mail_verify` reports whether a send was verified at send time; use `mail_find` to inspect the message's current mailbox location.

See [the skill instructions](skills/macos-mail/SKILL.md) and [Apple Mail quirks](skills/macos-mail/references/apple-mail-quirks.md).
