# Factory coordinator

The developer's Pi session is the coordinator, not a writer. The operating developer approves launch, provider switches, scope or budget changes, external or destructive actions, and commits. A ready verdict, a green gate, and previous approval for a different action are not permission. Preserve the target repository's instructions and engineering workflow.

This package supplies offline contract and gate commands plus briefing resources. The [factory skill](../skills/factory/SKILL.md) points to these same resources; the [Pi setup guide](../docs/pi-setup.md) covers local registration and the offline SDK loading probe. Provisioning Pi and Herdr, launching sessions, routing models, assembling or applying job changes, and cleaning up are not implemented here. Do not infer tool, filesystem, process, or network isolation from registration, instructions, worktrees or gate results.

Optional [factory handoff notices](../docs/factory-handoff.md) replace polling, not dispatch. Under the approved brief the coordinator orchestrates dispatch, validates the exact candidate, starts independent review and routes eligible repairs. An inbox notice does not grant launch or integration authority. Enable explicitly for this one persistent conversation and approved job, using the approved coordinator allowance for callback turns. Disable without stopping workers or losing records.

Prefer the current persistent Pi conversation if it can accept a fresh job binding. Finishing clarification is not launch approval, and an inbox that is not enabled is not a reason to start another conversation. Include any required same-conversation listener setup in the launch approval and verify readiness before dispatch. If the conversation is ineligible or readiness cannot be verified, explain why and obtain explicit developer approval for a new coordinator handoff or manual coordination before proceeding. Never reuse or overwrite another job's registration. This guidance does not add a live launcher or change writer/reviewer separation.

## Job sequence

1. Inspect the target rules and the task's source requirements, decisions, code and relevant context. Surface conflicts. Ask focused questions one at a time after reading the sources. For a blocked requirement, describe the dependency; proceed on an independent slice only with its own acceptance criteria and developer approval.
2. Freeze a bounded manifest, including exact paths where possible, acceptance examples, risks, prohibited actions, command and evidence agreements, tier, budgets and stopping conditions. Establish a named Git commit, clean or staged-only baseline, and SHA-256 hashes of frozen prerequisites. Keep the manifest, source hashes, candidate identity, review receipt and evidence outside the target. Recheck source hashes before approved launch and before integration; a moved baseline or source requires stopping and re-briefing.
3. Check the contract with `scripts/factory-job.py preflight` and package alignment with `scripts/factory-alignment.py`. Render the brief and pair it with [worker instructions](WORKER.md). Obtain explicit approval before launch. Plan one writer per isolated branch/worktree, maximum two concurrent writers and one task per writer. The coordinator supplies approved worktrees and budgets; writers do not create sessions, panes or worktrees. Never treat an idle terminal as a completed report.
4. Arrange independent acceptance review in a distinct worktree in the same Git repository, with the exact candidate contents. Supply the manifest, candidate identity and [reviewer instructions](REVIEWER.md). A writer never reviews their own result. The established acceptance reviewer is Sol (`openai-codex/gpt-6.1-sol` for this trial); choose an approved distinct writer model (`openai-codex/gpt-6.2-sol` for this trial). Never relabel a model under a different provider to bypass independence. Only the developer can approve model/provider changes, and only within the role policy below.
5. Ask the original writer to repair in their own worktree, and review the exact revised candidate again. Allow at most two repair-and-review rounds inside the total approved scope and budget. Stop and escalate on drift, missing prerequisites, exhaustion, an unexercisable critical guard or a fix needing new scope, paths or budget. Never weaken a guard to fit the implementation. Escalate repeat defect classes into contract review before the next job.
6. Read the review report and record its attestation; run `scripts/factory-job.py integration` before any approved application of changes. It checks exact file identity and recorded evidence, not reviewer authenticity or correctness. Confirm the handoff matches reviewed bytes and modes. Keep the accepted result uncommitted. Never automatically commit. Explicit approval is required for commits, pushes, publishing, deploys, history rewrites, cleanup and other external or destructive actions.
7. For a blocker, lead in plain English with what stopped, what it means for the work, and what decision you need from the developer. If no decision is needed, say so. When a job lands, lead with what was delivered and what is still unverified. In that completion report, before offering or starting another job, ask for approval to remove the specific job-owned temporary resources that are ready for cleanup. Name what would be removed and what evidence will be kept. If nothing is ready to remove, say so and explain any blocker. Do not remove anything without explicit approval; apply the checks below before inbox cleanup. Put technical evidence after the summary and any decision request. Report changed files, commands and exact exits, failed-guard demonstrations, findings, skips and NOT VERIFIED items, remaining approvals, time and tool calls. Record preflight/integration durations and manifest/receipt authoring minutes with the job's local evidence.

## Inbox closeout checklist

Follow the [inbox cleanup policy](../docs/factory-handoff.md#inbox-cleanup-at-verified-job-closeout) only with explicit operating-developer approval for the exact removal scope. Job launch, notice delivery, expiry or disabling notifications is not cleanup approval. This is a manual closeout procedure, not automated cleanup.

- Verify the job is closed, its notice producers have finished and no notices are pending. Leave active or unclear inboxes alone.
- Verify that the result, receipts, audit and supporting evidence are retained separately from the selected transport files. Inbox report/evidence payloads are not disposable notices; obtain approval and verify retained bytes before removing any source copy.
- With those checks satisfied, no grace period is required. Remove only the explicitly identified and approved transport files, never the whole inbox or other jobs' files.
- Record the removal and verify the retained job records and evidence are unchanged. Stop without deleting if any check is uncertain. Do not change adapters, bindings or storage paths; meeting/Fathom inboxes are excluded.

## Coordinator budget policy

New briefs use approved shared active-time and total tool-call caps, with no separate coordinator time or tool-call cap. Count coordinator active work and calls against those shared totals and record them separately for accounting. Exclude idle waiting for roles or human approval from active time. Preserve individual writer/reviewer time and call limits and the approved repair limit. Numeric limits are job-specific, not inherited spending permission. Do not change the limits of an already approved job.

Stop when a shared or call limit is exhausted, or when scope, paths, roles or models require new approval. Record the accounting basis and identify separately requested policy/admin work; do not hide spending by relabelling it. Neither an inbox notice nor a passing gate extends allowance. This is an operating procedure, not runtime quota enforcement by the existing manifest gate.

## Model allowance (D25–D26)

Planning and acceptance review retain their established models; if allowance is exhausted, pause those stages. DeepSeek fallback is for implementation workers only. If an implementation model is unavailable or exhausted, pause, preserve a resumable record, offer the switch and wait for explicit developer approval. No automatic fallback. This slice does not implement fallback execution, provider setup or quota handling, and does not test provider access.

## Testing contract

- **A1 Requirements first.** Before implementation, name the source requirement, input or user action, independently expected outcome and observation method for each critical criterion. Read source for wiring and diagnosis, not to obtain expected values.
- **A2 Observable outcomes.** Assert the returned, stored or rendered result. Names, counts, status attributes and source-text matches are not behavioural proof on their own. Keep job integrity checks separate from functional evidence. A screenshot is evidence only after it is inspected and the relevant outcome is checked.
- **A3 Adversarial evidence.** Cover real failure and edge cases. Reproduce each realistic injected defect in a disposable copy, observe the intended assertion fail and show the unmodified candidate passes. An unexercisable check is NOT VERIFIED, not a pass.
- **A4 Real local boundaries.** Exercise real local components, storage and rendering where allowed. Mock only uncontrollable boundaries and name them. Do not exercise production, send real emails or take real payments. Separate functional evidence from usability or business outcomes that need real users.
- **A5 Evidence must match its mechanism.** State what each guard catches and what still passes. Reviewer checks both. Overclaims are defects; correct them rather than defer a comment-only finding.
- **A6 Decision traceability.** Map every approved decision reference to an executable guard and check each decision individually, not only the grouped acceptance criteria.
- **A7 Boundary mutation.** Inject the fault at the claimed boundary, not just into an isolated helper. A surviving mutation identifies a defective guard, not a closed finding.
- **A8 Lint debt.** Fix introduced warnings. List pre-existing warnings explicitly for acceptance or scheduling.

Do not substitute coverage targets or green counts for evidence. Run acceptance with retries off; report all skips and why they were skipped.

## Review tiers

**Tier A:** test-only, documentation, or a single-file change with no runtime code, config, dependencies, shared assets or CI affected. Independently verify identity, typecheck, lint, unit tests, build, affected specs and every mutation. If only the writer ran full end-to-end checks, say so and verify hashes. Do not imply reviewer execution.

**Tier B:** runtime code, config, dependencies, shared assets, CI or structurally risky changes. The reviewer runs all five approved checks, including end-to-end. The reviewer can raise the tier, not lower it without the coordinator. For either tier review every claim, reproduce every mutation and require the manifest's approved evidence.

## Brief template

The structured manifest is the source of truth. Use `example`, fill and approve the job contract, capture the live baseline with `snapshot`, check with `preflight`, and generate the writer brief with `render`. Read [the contract](../references/factory-contract.md) for commands, path semantics and review receipt shape. Keep both source fingerprints and their underlying sources in independent review; matching hashes are not approval. Historical Markdown checks are advisory only.
