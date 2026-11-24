# Factory coordinator

The developer's Pi session is the coordinator, not a writer. The operating developer approves launch, provider switches, scope or budget changes, external or destructive actions, and commits. A ready verdict, a green gate, and previous approval for a different action are not permission. Preserve the target repository's instructions and engineering workflow.

This package supplies the offline contract and gate commands, briefing resources, an opt-in notification adapter and a bounded coordinator-invoked loop in [scripts/factory-run.py](../scripts/factory-run.py). It does not install Pi or Herdr, copy credentials, authenticate a provider, create a second writer, or provide a daemon, crash recovery or process isolation. The loop uses real local Git, Pi and Herdr; those tools remain local prerequisites.

## Role policy

- The shipped defaults are `deepseek/deepseek-flash` with model-default reasoning for the writer and `openai/gpt-6.1-sol` with high reasoning for the coordinator and reviewer. A developer can select other exact routes and reasoning for a new job via [workspace policy](../docs/customization.md#factory-policy-for-new-jobs).
- Bind and display the exact provider/model identities and reasoning before launch. The manifest writer model and worktree must match the selected writer. Verify the actual role routes; the runner records but does not configure the existing coordinator session. Same-model writer and reviewer are allowed, in independent sessions and worktrees. Missing or mismatched routes block; never relabel a provider or silently substitute a model.
- A later switch is writer-only and requires explicit operating-developer approval of a supported route named and approved in the plan. It preserves progress and uses a fresh writer attempt. It never changes the coordinator or reviewer route or the approved budgets.
- If implementation allowance, access or a route is unavailable or mismatched, pause, preserve a resumable record and wait for explicit developer approval before any switch. Exhausted coordinator or reviewer allowance pauses that stage. No automatic fallback. Provider safety refusals stop without rerouting or retrying.
- Planning and acceptance review retain their approved routes for the active job. The loop implements only the approved writer switch, not automatic fallback.

## Job sequence

1. Inspect the target rules and the task's source requirements, decisions, code and relevant context. Surface conflicts. Ask focused questions one at a time after reading the sources. For a blocked requirement, describe the dependency; proceed on an independent slice only with its own acceptance criteria and developer approval.
2. Freeze a bounded manifest, including exact paths where possible, acceptance examples, risks, prohibited actions, command and evidence agreements, tier, budgets and stopping conditions. Establish a named Git commit, clean or staged-only baseline, and SHA-256 hashes of frozen prerequisites. Keep the manifest, source hashes, candidate identity, review receipt and evidence outside the target. Recheck source hashes before approved launch and before integration; a moved baseline or source requires stopping and re-briefing.
3. Check the contract with `scripts/factory-job.py preflight` and package alignment with `scripts/factory-alignment.py`. Render the brief and pair it with [worker instructions](WORKER.md). Obtain explicit approval before launch. Plan one writer per isolated branch/worktree, maximum two concurrent writers and one task per writer. The coordinator supplies approved worktrees and budgets; writers do not create sessions, panes or worktrees. Never treat an idle terminal as a completed report.
4. Preview the loop plan with the fixed command and read the exact routes, listeners, worktrees and budgets it displays:

   ```sh
   python -B scripts/factory-run.py preview MANIFEST --registration INBOX/registration.json \
     --writer-worktree WRITER --reviewer-worktree REVIEWER --plan-out PLAN --brief BRIEF.md \
     [--workspace WORKSPACE] [--overall-limit CALLS:MINUTES] [--used-shared CALLS:MINUTES] \
     --herdr /path/to/herdr --pi /path/to/pi --session-dir SESSIONS --agent-dir AGENT
   ```

   Preview refuses a missing, expired, misbound or duplicate listener, a moved baseline, a pre-existing worktree, a missing tool, conflicting role-identity Pi arguments and a selected-writer/manifest mismatch. No aggregate ceiling is implied: omit `--overall-limit` for reporting-only cumulative use, or pass it explicitly to enforce one. It writes only the requested private plan. Obtain explicit approval for that unchanged plan, then launch once:

   ```sh
   python -B scripts/factory-run.py launch PLAN --state STATE --approve
   ```

   Launch records the fixed writer attempt before it creates the Herdr pane and submits exactly one prompt. Role dispatch starts the exact absolute `--pi` executable recorded in the plan inside a Herdr pane and waits for Herdr's own Pi detection; it never resolves `pi` from `PATH`. Before role creation it checks exact identities in that Pi's offline model inventory, using the declared agent directory and any expressly approved provider extension. A missing executable, model or reasoning capability stops before a prompt. The local inventory is not proof of authenticated availability, exact effort support or live success. The loop creates no profile or global configuration. `advance` reads only published inbox records; it never infers completion from idle state. It dispatches the independent reviewer, following [reviewer instructions](REVIEWER.md), in a separate worktree containing the exact candidate, routes eligible `changes_requested` repairs to the original writer, and never stages an initial or unapproved review.
5. Ask the original writer to repair in their own worktree, and review the exact revised candidate again. Allow only the frozen repair limit (two by default), inside the approved scope and budget. Stop and escalate on drift, missing prerequisites, exhaustion, an unexercisable critical guard or a fix needing new scope, paths or budget. Never weaken a guard to fit the implementation. Escalate repeat defect classes into contract review before the next job.
6. Read the review report and record its attestation; run `scripts/factory-job.py integration` before any approved application of changes. The loop's `handoff` runs that gate again, refuses without `--approve`, and stages only the accepted exact candidate against the unchanged baseline:

   ```sh
   python -B scripts/factory-run.py handoff STATE --approve
   ```

   It never commits or pushes. Confirm the handoff matches reviewed bytes and modes. Keep the accepted result uncommitted. Never automatically commit. Explicit approval is required for commits, pushes, publishing, deploys, history rewrites, cleanup and other external or destructive actions. Use `stop` to record a resumable blocked, exhausted or drift state; it launches nothing.
7. For a blocker, lead in plain English with what stopped, what it means for the work, and what decision you need from the developer. If no decision is needed, say so. When a job lands, lead with what was delivered and what is still unverified. In that completion report, before offering or starting another job, ask for approval to remove the specific job-owned temporary resources that are ready for cleanup. Name what would be removed and what evidence will be kept. If nothing is ready to remove, say so and explain any blocker. Do not remove anything without explicit approval; apply the checks below before inbox cleanup. Put technical evidence after the summary and any decision request. Report changed files, commands and exact exits, failed-guard demonstrations, findings, skips and NOT VERIFIED items, remaining approvals, time and tool calls. Record preflight/integration durations and manifest/receipt authoring minutes with the job's local evidence.

## Inbox closeout checklist

Follow the [factory handoff](../docs/factory-handoff.md) [inbox cleanup policy](../docs/factory-handoff.md#inbox-cleanup-at-verified-job-closeout) only with explicit operating-developer approval for the exact removal scope. Job launch, notice delivery, expiry or disabling notifications is not cleanup approval. This is a manual closeout procedure, not automated cleanup.

- Verify the job is closed, its notice producers have finished and no notices are pending. Leave active or unclear inboxes alone.
- Verify that the result, receipts, audit and supporting evidence are retained separately from the selected transport files. Inbox report/evidence payloads are not disposable notices; obtain approval and verify retained bytes before removing any source copy.
- With those checks satisfied, no grace period is required. Remove only the explicitly identified and approved transport files, never the whole inbox or other jobs' files.
- Record the removal and verify that the retained job records and evidence are unchanged. Stop without deleting if any check is uncertain. Do not change adapters, bindings or storage paths; meeting/Fathom inboxes are excluded.

## Coordinator budget policy

Default firm declared allowances are **per attempt**: initial writer 60 calls/25 active minutes, initial reviewer 60/25, eligible repair writer 30/15 and independent re-review 40/20. The developer may choose other limits in the workspace policy before approval. Per-job CLI overrides can only narrow those selected limits. These are declared local accounting rules, not authenticated provider quotas or a process watchdog.

- Plan approval records the effective routes, per-attempt allowances, repair limit and a policy digest. Keep the exact plan file with the state. Editing the workspace affects only future previews. Same-attempt resume keeps its allocation and spending; a new eligible repair or re-review receives only its own bounded allocation while full cumulative history remains visible.
- Cumulative role, coordinator and job use is recorded and reported. It is **not** a mandatory job cap and does not silently block an otherwise eligible bounded attempt.
- An overall ceiling is optional and must be explicitly selected at plan approval with `--overall-limit CALLS:MINUTES`. It is never inherited or implied. When selected, initial shared use is derived from role/coordinator deltas or must be consistent with them; inconsistent aggregates are rejected and exhausted capacity refuses before any role side effect.
- Attempt or selected-overall exhaustion pauses with a resumable state. It never resets an attempt, reissues another ID, retries a safety refusal or enlarges an allowance. A writer switch consumes one of the selected repair slots.
- Old-format or mismatched state is refused as `stale-state`. Preserve the records and seek explicit approval for a new job; preview is not a migration or permission to reset any spending.

## Testing contract

Run full acceptance once per required role through `python -B scripts/verify-suite.py` in that role's own shell. It checks the role environment's prerequisites in the same interpreter and environment before discovery, reports every missing or invalid prerequisite together and exits nonzero without importing a test, then runs the packaged suite once and passes the suite status through. `--check` reports prerequisites only and never discovers tests. A prerequisite check is not test behaviour.

- **A1 Requirements first.** Before implementation, name the source requirement, input or user action, independently expected outcome and observation method for each critical criterion. Read source for wiring and diagnosis, not to obtain expected values.
- **A2 Observable outcomes.** Assert the returned, stored or rendered result. Names, counts, status attributes and source-text matches are not behavioural proof on their own. Keep job integrity checks separate from functional evidence.
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

The structured manifest is the source of truth. Use `example`, fill and approve the job contract, capture the live baseline with `snapshot`, check with `preflight`, and generate the writer brief with `render`. The generated brief is authoritative; do not hand-write or reuse a superseded brief. Read [the contract](../references/factory-contract.md) for commands, path semantics and review receipt shape.

## Evidence boundary

The loop uses the fixed inbox records for attempts and completions, real Git worktrees and named Herdr sessions. Its automated QA uses deterministic synthetic providers, so a green result verifies plumbing, record ordering, route selection and exact staging, not authenticated provider operation, model quality, cost, fresh macOS acceptance or Windows. Live provider/account operation through this loop is NOT VERIFIED. A live rehearsal requires separate approval and synthetic prompts only.
