# Apple Mail scripting compatibility notes

## Source hierarchy

1. Live `/System/Applications/Mail.app/Contents/Resources/Mail.sdef`
2. Current Mail application version and macOS version
3. Apple Mac Automation Scripting Guide and AppleScript Language Guide
4. Verified local integration tests

Apple scripting terminology can change across OS or app versions. The adapter cache is keyed to the live `Mail.sdef`; compile and diagnose the affected operation when it changes.

## Validated environments

Do not copy observed OS, Mail, or SDEF values into this reference. Inspect the live system immediately before a version-dependent diagnosis.

## Current dictionary semantics

- `send` accepts an `outgoing message`, not a stored generic `message`.
- `reply` and `forward` create and return an `outgoing message`.
- `outgoing message` exposes sender, subject, content, visibility, recipients, save, and send.
- A stored draft is later observed as a generic message. Recreate an outgoing object from the approved draft before sending.
- Received `message` exposes content, headers, source, read/flag status, Message-ID, and received attachments.
- Received `mail attachment` supports metadata and save.
- The Text Suite separately exposes writable `attachment.file name` inside rich text. Use that surface for outgoing files, then verify the stored draft and Sent/received copies; do not confuse it with received `mail attachment`.
- Aggregate Drafts, Sent, Inbox, and Trash are exposed by the Mail application dictionary; account mailboxes remain localized. Enumerate them rather than using literal Korean or English names.

## Verified failure patterns

- A reply object can be accepted by `send` while the delivered body is effectively empty. Validate the composed body before send and the Sent copy afterward.
- Deleting or moving a message is asynchronous. Poll the source and destination; do not infer failure after a fixed one-second delay.
- A send timeout is ambiguous. Never resend automatically; search aggregate Sent and verify the exact envelope first.
- Broad scans can be slow. For global recent mail, query only each account Inbox and compare typed received dates before returning the top N.
- Unicode mailbox names may be stored in decomposed form. Compare canonical Unicode forms while preserving the exact live name in message references.
- Resolve an outgoing attachment's POSIX path to an existing AppleScript `alias` before entering Mail's `tell application` scope. Otherwise Mail can interpret `POSIX file` as application terminology and fail with `-1728` before sending.
- Treat received-attachment metadata properties as independently fallible. Mail can enumerate an attachment and expose its name while one optional property raises; do not discard the entire attachment array because one metadata read failed.
- IMAP draft synchronization can replace a draft's local Mail ID between AppleScript processes. Resolve the bound local ID first; only when it disappears, fall back to exactly one RFC Message-ID match inside the already-bound account mailbox. Never accept an RFC mismatch or multiple matches.
- Gmail draft synchronization can replace both the local Mail ID and RFC Message-ID. Bind Mail's `X-Universally-Unique-Identifier` from the official `all headers` property, restrict draft fallback to the selected account's exact Drafts mailbox, and accept only one matching universal identifier.
- Do not retain a Mail draft object reference across send verification delays. After Sent is verified, re-resolve the approved 3-part draft reference, delete that current draft object, and verify that no bound draft remains.
- Serialize a verified Sent message to plain result data before draft-cleanup polling. Do not dereference a Sent Mail object after an IMAP synchronization delay.
- After moving or restoring a message, replace its mailbox path in the bound reference and re-resolve it in the destination. Do not read the object returned by `move` after a synchronization delay.
- Verify Trash source removal by the complete bound reference, not disappearance of the old local ID alone; IMAP rekeying is not deletion evidence.
- Retry only pre-send draft resolution and value snapshotting when Mail invalidates an object with `-1728`. Call `send` once only after the snapshot is complete; a failure after that boundary must never trigger another send.
- Hidden `reply` and `forward` objects may expose no generated quote. Capture the source message's official `content` before composition, append it explicitly after the user body, save, then verify both parts in the stored draft.
- Mail may re-key a saved draft while synchronizing it. Resolve and hash-check the approved draft in Python, materialize its envelope/body as JSON values, and pass those values across the send boundary.
- Outgoing-message construction is non-retryable because even `close ... saving no` can leave a Gmail server draft. Construct exactly one outgoing object and invoke the sole `send` call once; inspect an error at either boundary before any new send attempt.
- After a verified send, Gmail may temporarily retain both the approved source draft and an outgoing-derived server draft with different local/RFC identifiers. Cleanup must bind the original draft reference and verified Sent reference, restrict matches by the exact account and envelope, remove only those bound Drafts entries, and verify their absence within `cleanup_timeout_seconds`.
- Mail can retain hidden `outgoing message` backend objects after successful send and after a supported `close`; the live SDEF exposes `close` but no backend-deletion command. Capture each official integer `id`; after Sent verification, revalidate its account sender and exact envelope, close only bound objects whose official `visible` property is true, and verify every bound object is absent or `visible:false`. Do not claim hidden backend deletion. Run server-draft cleanup afterward because closing can trigger synchronization side effects.

## Permissions

Mail control uses Apple Events and requires Automation consent for the actual host process running `osascript`. The script does not use UI scripting, so Accessibility is not a prerequisite. Do not request Full Disk Access or change security settings unless a distinct, reproduced denial proves it necessary.
