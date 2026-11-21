# Opt-in factory completion notices

The inbox only notifies. The coordinator still dispatches the writer, checks the exact candidate, starts independent review, routes eligible in-scope repairs and runs the existing gates. The operating developer retains approval for launch, changed scope or budget, provider switches, external or destructive actions and commits. A writer report is not independent acceptance; a matching reviewer verdict is not integration approval. Keep the handoff uncommitted.

## Start from an approved job and a persistent conversation

Use Pi 1.4.0, Python 3.10+ standard library on POSIX, and the existing [factory contract](../references/factory-contract.md). Use physical absolute paths without symlinks. Start Pi with a private umask so its new session transcript is private, and make an initial ordinary turn to establish the conversation. Use `/session` to find the exact transcript file. Load the extension explicitly for this Pi process; **do not** install it or add it to settings.

```sh
(umask 077; pi -e "$KIT/extensions/factory-inbox.ts")
```

Prepare a new directory of mode `0700` outside the kit, workspace, targets and writer tree. Keep the transcript, approved manifest, candidate identity, reports and evidence private. Use a short expiry in Unix epoch **milliseconds** and the exact session file from `/session`. Use `--approve` only for writes within the developer-approved job. It is an explicit operator assertion, not authentication.

```sh
python -B "$KIT/scripts/factory-inbox.py" register job "$INBOX" \
  --manifest "$MANIFEST" --session "$SESSION_FILE" --expires-ms "$EXPIRY_MS" --approve
python -B "$KIT/scripts/factory-inbox.py" inspect "$INBOX/registration.json"
```

Then in that Pi conversation, enter `/dcc-handoff enable <absolute-registration>` with the absolute path to `registration.json` as the rest of the line (do not add quotes). The extension does not watch before this opt-in. `/dcc-handoff status` observes the current state; `/dcc-handoff disable` stops notifications, leaves the running worker and every record alone, and persists the disabled state. Explicitly enable the **same** registration to resume notifications. A different job/registration needs a separate conversation. Wrong-session, expired, unsafe and ephemeral input is refused. For clean resume of the original conversation, load the extension again with `-e` and resume its exact transcript. Leaving out `-e` is the manual path; read the records and coordinate stages directly.

## Register attempts and publish completions

Register the writer attempt before dispatch. Supply the reporting role with the fixed registration and attempt, not a command received from an inbox record. A separate producer publishes only when complete, with the approved role and attempt. A writer must name the outcome explicitly. For an implementation stop without a candidate use `blocked`, not `reported`.

```sh
python -B "$KIT/scripts/factory-inbox.py" register attempt "$INBOX/registration.json" writer a1 --approve
python -B "$KIT/scripts/factory-inbox.py" publish "$INBOX/registration.json" writer a1 reported \
  --report "$WRITER_REPORT" --evidence "$WRITER_EVIDENCE" --approve
```

After the coordinator independently checks the candidate, save the existing `factory-job.py candidate` JSON as a private file. Register the reviewer attempt against it before independent review. Publish the actual reviewer receipt as the report and its corresponding evidence. The publisher derives the outcome from the receipt's `verdict` (`approved`, `changes_requested` or `blocked`). The receipt must be version 1 and carry the registered manifest and candidate digests. The transport checks these bindings, **not** the integration receipt requirements, reviewer independence, model identity or correctness.

```sh
python -B "$KIT/scripts/factory-job.py" candidate "$MANIFEST" --candidate "$CANDIDATE" > "$CANDIDATE_ID"
python -B "$KIT/scripts/factory-inbox.py" register attempt "$INBOX/registration.json" reviewer a1 \
  --candidate "$CANDIDATE_ID" --approve
python -B "$KIT/scripts/factory-inbox.py" publish "$INBOX/registration.json" reviewer a1 \
  --report "$REVIEW_RECEIPT" --evidence "$REVIEW_EVIDENCE" --approve
python -B "$KIT/scripts/factory-inbox.py" inspect "$INBOX/registration.json" reviewer a1
```

An existing reviewer call with an explicit outcome still works when it matches the receipt. An unsupported reviewer outcome or receipt verdict returns `invalid-outcome`; two supported but different verdicts return `outcome-conflict`. A malformed or misbound receipt returns `receipt-mismatch`, and an unregistered or invalid attempt returns `invalid-attempt`. These refusals do not reserve or publish the attempt; correct the input and use the properly registered attempt. A repeat of a successful publication is refused as `record-exists` without replacing its records.

Create private source files from the start, for example with `umask 077` before redirection. Version 1 uses one `registration.json`, one `attempt.json` per `writer.ID` or `reviewer.ID` directory, then `records/report` and `records/evidence` and finally `event.json`. The attempt binds role, job, conversation, manifest and (for review) canonical candidate. The event pins the exact report and evidence bytes. Publication never replaces a record. Register a fresh attempt ID for another completion or for a failed partial publication; do not edit published records. An attempt ID starts with a lowercase letter or digit and has at most 32 lowercase letters, digits, underscores or hyphens. Job and session IDs use at most 96 ASCII letters, digits, dots, underscores or hyphens and start alphanumeric. Manifest and candidate identity are limited to 2 MiB each, the session header and protocol records to 4 KiB, and each payload to 128 KiB. The watcher scans at most 256 root entries. Use `inspect` to read metadata without copying report prose into the conversation. A refusal exits 1; malformed CLI usage exits 2. Neither success nor any status grants authority.

A fixed custom message requests one coordinator model turn after settlement, using the approved coordinator allowance. Only code-owned text goes into the callback; role, job, attempt and identity bindings are in its transcript metadata. The adapter itself does not change models, run tools or launch workers, review, repair, integration or cleanup. It does not enforce model obedience. Read reports separately and verify the candidate, evidence and core gate as usual.

## Inbox cleanup at verified job closeout

Transient transport notices have no grace period once the operating developer explicitly approves closeout cleanup and the coordinator verifies the checks below. Delivery, expiry, disabling notifications, a reviewer verdict or launch approval alone does not authorize deletion. This is a manual policy, not an automatic sweeper or a new cleanup command.

Before removing anything:

1. Verify that the job is closed, all of its notice producers have finished and no notices are pending. Leave active or unclear inboxes alone.
2. Verify that the result, receipts, audit and supporting evidence are retained separately from the transport files selected for removal. The kit inbox contains `records/report` and `records/evidence` payloads as well as notices: its contents are not all disposable. If evidence must be copied out first, obtain approval and verify the retained bytes before deleting any source copy.
3. Identify the exact transport files and obtain the operating developer's explicit approval for that removal scope. Remove only those files. Do not recursively delete the inbox or include reports, evidence, other jobs, fixtures or unrelated files.
4. Record what was removed and verify that the retained job records and evidence are unchanged. If any check is uncertain, stop without deleting.

The developer accepts losing the original transport notices for later debugging once the durable job record is complete. This policy does not change adapters, bindings or storage paths and does not apply to a meeting/Fathom inbox. Notifications still never launch cleanup.

## Evidence boundary

The publisher uses Python 3.10+ standard library and POSIX filesystem semantics. The following are requirements of the **Linux QA fixtures**, not publisher runtime dependencies or an isolation guarantee for normal Pi use:

- Set `DCC_PI_EXECUTABLE` to the absolute native Pi 1.4.0 CLI path for the PTY tests. Set `DCC_PI_SDK_MODULE` to the absolute Pi 1.4.0 SDK `dist/index.js` path for the full suite, with Node as specified in the [setup guide](pi-setup.md). QA uses an offline deterministic provider, isolated HOME and agent directories, no tools or MCP, and separate local producer processes.
- Use a Linux host permitting `unshare -Urn` (user and network namespaces), with inotify and Landlock enabled. The archive fixture uses Landlock syscalls 444/445/446 with the pinned Linux ABI layout, `no_new_privs` and `O_PATH`. The real publisher permission-denial test runs as a non-root owner; a privileged run does not substitute for it.

Relocation tests actively check denial of the original source and of an otherwise usable executable outside the allowed paths. The Landlock policy permits reads of fixture, relocated and declared runtime paths and `/usr`, `/etc`, `/proc`, `/dev` and `/sys`; it is not a general sandbox. Separate inotify windows observe successful opens and accesses in existing inbox directories during each producer call and from Pi enable through shutdown. The audit does not attribute events to a PID or recurse into newly created directories, and cannot account for activity outside those paths/windows or all ways to evaluate code (such as bytes already in memory). Evaluation evidence uses the named JavaScript and Python helper markers, not an arbitrary code-origin or secret detector.

The protocol assumes a trusted local user and filesystem. Clean same-branch resume is the supported restart case; no crash, power-loss, branch rewind/fork or concurrent-coordinator guarantee. Live-reviewer busy-turn validation, live Herdr orchestration, provider fallback, authenticated integrations, fresh macOS V9 and full V10, and Windows follow-up remain NOT VERIFIED. No global resource or workspace mapping migration is needed.
