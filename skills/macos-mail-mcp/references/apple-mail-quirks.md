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
- A stored draft is later observed as a generic message. Keep the `outgoing message` ID created during preparation and send that same object after checking the saved draft.
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
- Ordinary message references must match every supplied RFC and universal identifier, including when the local ID matches. Reject a mismatched or ambiguous reference before changing mail.
- IMAP draft synchronization can replace a draft's local Mail ID between AppleScript processes. Gmail can replace both its local and RFC IDs. Bind the draft's `X-Universally-Unique-Identifier` from `all headers`, restrict draft fallback to the selected account's exact Drafts mailbox, and check the outgoing ID and envelope before sending. If no universal ID exists, require an exact RFC match.
- Do not retain a Mail draft object reference across send verification delays. Save its exact reference during preparation, and use it only for read-only checks after sending.
- Serialize a verified Sent message to plain result data before further mailbox polling. Do not dereference a Sent Mail object after an IMAP synchronization delay.
- After moving or restoring a message, replace its mailbox path in the bound reference and re-resolve it in the destination. Do not read the object returned by `move` after a synchronization delay.
- Verify Trash source removal by the complete bound reference, not disappearance of the old local ID alone; IMAP rekeying is not deletion evidence.
- Retry only pre-send draft resolution and value snapshotting when Mail invalidates an object with `-1728`. Call `send` once on the prepared outgoing object after its values are checked; a failure after that boundary must never trigger another send.
- Hidden `reply` and `forward` objects may expose no generated quote. Capture the source message's official `content` before composition, append it explicitly after the user body, save, then verify both parts in the stored draft.
- Mail may re-key a saved draft while synchronizing it. Resolve and hash-check the approved draft in Python, then use its original outgoing object ID for the single native `send` call. Revalidate the outgoing envelope and body immediately before sending.
- Constructing a second outgoing object at send time leaves an extra Gmail server draft; deleting that draft moves it to Trash. Sending the saved object while hidden also left its draft in Gmail Drafts in a controlled test. Prepare one outgoing object, save it for review, make its composer visible immediately before sending, and send that same object. Mail then cleared Drafts without a Trash artifact in a controlled test. Do not clean up a successful send by deleting drafts.
- Showing a saved composer can clear inline attachments from its outgoing object even though the stored draft preview lists them. After making the composer visible, inspect the outgoing rich-text attachment count. If Mail cleared them, add the approved files back to that same outgoing object immediately before `send` and verify the count. Confirm the Sent and recipient copies contain the expected attachment.
- Mail can retain a hidden `outgoing message` backend object after a successful send. The live SDEF exposes `close` but no backend-deletion command, and closing it did not remove that backend in a controlled test. Do not claim hidden backend deletion; verify user-visible Drafts, Sent, and Trash by exact subject and message identifiers.

## Permissions

Mail control uses Apple Events and requires Automation consent for the actual host process running `osascript`. The script does not use UI scripting, so Accessibility is not a prerequisite. Do not request Full Disk Access or change security settings unless a distinct, reproduced denial proves it necessary.
