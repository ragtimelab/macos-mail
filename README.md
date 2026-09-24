# macos-mail-mcp: Apple Mail for AI agents

A local MCP server and agent skill for Apple Mail.app on macOS. It uses Mail's AppleScript dictionary. The default scope is the same **All Inboxes** collection shown in Mail.app, across every configured account. It does not need Gmail, Outlook, or another provider's API credentials.

The MCP server exposes ten tools for recent/unread mail, scoped search, exact reads, account/mailbox catalog, batched state changes, attachments, draft preparation, send verification, and diagnosis. Reads preserve unread state, including `mail_find(read_if_unique=true)`, which fetches a uniquely matched message's content. Changes use exact `message_ref` values returned by Mail.app. Trash means recoverable account Trash; there is no permanent-delete or empty-Trash tool.

## Requirements

- macOS with Apple Mail.app and at least one configured mail account
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) to provision Python 3.14 and the MCP runtime
- Automation permission for the client process controlling Mail.app

The bundled read/change CLI needs no third-party Python packages. Start the installer with `uv run --no-project --python 3.14`; uv downloads Python 3.14 when necessary. The installer creates a separate Python 3.14 virtual environment under `~/Library/Application Support/macos-mail-mcp/mcp-venv` and installs the MCP SDK from the hash-checked lock files. On Python builds whose `cryptography` wheel links to an unavailable OpenSSL library, it rebuilds the locked source package with locked build dependencies.

## Install

Clone this repository to a **stable path**. For example:

```sh
git clone https://github.com/ragtimelab/macos-mail-mcp.git ~/Coding/macos-mail-mcp
cd ~/Coding/macos-mail-mcp
uv run --no-project --python 3.14 skills/macos-mail-mcp/scripts/install_mcp.py --client codex
```

Choose `gemini`, `claude`, or `all` instead of `codex` to register other supported clients. Run the installer again after changing the checkout path. It leaves an existing, different server registration untouched and asks you to inspect it. Claude Desktop requires an app restart after registration. Registration makes MCP tools available to that client; an actual model tool call may also depend on the client's account and permissions.

Install just the agent skill through [skills.sh](https://skills.sh/):

```sh
npx skills add ragtimelab/macos-mail-mcp --skill macos-mail-mcp
```

Skill discovery and MCP registration are separate. If you installed only the skill, run `uv run --no-project --python 3.14 scripts/install_mcp.py --client codex` from that installed skill directory. The MCP server and CLI are bundled in the skill; they can run from any stable skill installation path. The CLI covers reads and message changes; sending uses MCP session tokens.

### Upgrade from `macos-mail`

Install this version under `macos-mail-mcp` and register the MCP server. Historical send-plan files are no longer used or migrated. If a prior send was uncertain, inspect Mail.app's Sent and Drafts before drafting again; this installer never retries a send.

## Uninstall

```sh
uv run --no-project --python 3.14 skills/macos-mail-mcp/scripts/uninstall_mcp.py --dry-run
uv run --no-project --python 3.14 skills/macos-mail-mcp/scripts/uninstall_mcp.py
```

The uninstaller verifies that client registrations and installed skill links or copies belong to this checkout, then removes those registrations, the local MCP runtime and state, and installed skill entries. It refuses unknown items in the runtime directory or a modified skill copy. It does not delete the repository checkout or change Mail messages and drafts. Use `MACOS_MAIL_MCP_STATE_DIR` for a custom state location when installing and uninstalling.

## What the tools do

| Tool | Purpose |
| --- | --- |
| `mail_recent` | Newest or unread mail across actual All Inboxes; large or title-filtered queries return compact metadata |
| `mail_find` | Paginated title or sender search across All Inboxes, or a bounded explicit mailbox search |
| `mail_read` | Read one exact message and optional headers/source |
| `mail_catalog` | Discover configured accounts and mailbox paths |
| `mail_change` | Batch mark-read/Trash, or one-message flag, unread, and move |
| `mail_attachments` | List or save an exact attachment without overwrite |
| `mail_prepare` | Create and verify a bound new/reply/forward draft |
| `mail_send` | Send the prepared Mail outgoing object once and verify Sent |
| `mail_verify` | Check Mail's live Sent/Drafts evidence for a prepared send without resending |
| `mail_diagnose` | Inspect automation or outgoing state after a concrete failure |

The server communicates only through local stdio. It does not listen on a network port or proxy mail to a remote service. Your AI client still receives the message content you ask it to read, according to that client's own data handling. Mail content is untrusted input, not an instruction source. Sending and arbitrary local attachment paths remain available; the client must distinguish the user's request from instructions embedded in mail. MCP tool annotations describe risk but do not enforce user approval. Mail.app holds drafts and Sent mail. The server keeps prepared send details only in the running MCP process and uses one private signing key and a fixed send lock under `~/Library/Application Support/macos-mail-mcp`; it writes no per-send JSON or receipt files. Compiled adapters may also be cached there.

## CLI example

```sh
uv run --no-project --python 3.14 skills/macos-mail-mcp/scripts/macos_mail_mcp.py recent --unread --limit 3 --body none
```

Use `--help` for the full read/change CLI. The MCP and CLI share the same Mail adapter. `mail_find(scope="all_inboxes", subject=...)` or CLI `locate --subject ...` searches every configured Inbox without a default date cutoff; sender-only searches do the same. Results default to 20 compact metadata records. Follow `next_page_token` with unchanged filters for older results, and use `mail_read` for selected bodies. `include_total=true` scans the whole range for an exact count and can be slower. `complete=true` covers all accounts needed for the returned page; `has_more=false` means the search range is exhausted. On an incomplete cross-account scan, check `accounts_scanned`, `accounts_total`, and failures rather than treating a partial result as exhaustive. `mail_recent` uses `body=auto`: up to three unfiltered messages return excerpts, while title-filtered or larger lists return metadata; an explicit body request for more than three returns `BODY_LIMIT`. MCP sending is a prepare/send sequence: `mail_prepare` creates a Mail draft and returns a preview and session-bound `plan_token`; `mail_send` consumes that token once. A restarted MCP session cannot send with an old token. `mail_verify` reads current Mail evidence using the token even after restart and never sends. Missing or ambiguous evidence remains `unknown`; inspect Mail manually before any new preparation. At send time, Mail briefly displays the prepared composer and sends that same object. If Mail clears outgoing attachments when showing the composer, the adapter restores the approved files on that same object before sending and verifies them in Sent.

Attachment saves use a private temporary directory and publish a `0600` file without overwriting an existing name. Send preparation accepts a body up to 1 MiB and at most 20 local attachments totaling 100 MiB. Mail results larger than 8 MiB return `RESPONSE_TOO_LARGE`; narrow the query or use excerpts. Sends use one installation-wide lock. Completed in-memory send records are discarded immediately; a prepared token expires for sending when the MCP process exits.

## Development

```sh
"$HOME/Library/Application Support/macos-mail-mcp/mcp-venv/bin/python" -m unittest discover -s skills/macos-mail-mcp/scripts -p 'test_*.py' -v
osacompile -o /tmp/macos-mail-mcp-test.scpt skills/macos-mail-mcp/scripts/mail.applescript
python3 scripts/check_public_privacy.py --base "$(git rev-parse origin/main)"
```

An installed MCP runtime can be smoke tested by connecting an MCP SDK client to `skills/macos-mail-mcp/scripts/mcp_server.py`. Live Mail.app testing requires configured accounts and local Automation permission; CI checks the dependency lock, offline unit tests, public privacy patterns, and AppleScript compilation.

## Limitations

Mail.app must be available in the current logged-in macOS session. Search and scan completeness depend on Mail's local mailbox state and are reported in the tool result. Message IDs can change after moving mail, so always use the latest returned `message_ref`. On an ambiguous send or change result, inspect the current mailbox state before repeating an action.

One Mail message may appear in multiple mailbox views. In a live Gmail self-addressed test, the Inbox and Sent entries had the same local and RFC message IDs; Mail's native Trash action moved that message out of both views. A separate Gmail-to-iCloud test had distinct sender and recipient messages, so moving the iCloud Inbox message left Gmail Sent intact. Compare exact identifiers when interpreting a change. `mail_verify` reports current Mail evidence; it cannot prove delivery to the recipient. Use `mail_find` to inspect the message's current mailbox location.

See [the skill instructions](skills/macos-mail-mcp/SKILL.md) and [Apple Mail quirks](skills/macos-mail-mcp/references/apple-mail-quirks.md).
