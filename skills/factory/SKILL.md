---
name: factory
description: 'Prepare or coordinate a bounded implementation job. Use for factory briefs, approved writer and reviewer dispatch, review, or uncommitted handoff. Manual coordination is the default for new jobs.'
---

# Factory

You can invoke this skill with `/skill:factory`. Resolve all links relative to this skill directory. Read the repo-owned [coordinator](../../factory/COORDINATOR.md), [worker](../../factory/WORKER.md), [reviewer](../../factory/REVIEWER.md), and [factory contract](../../references/factory-contract.md). Use the shipped [factory job CLI](../../scripts/factory-job.py) and [alignment CLI](../../scripts/factory-alignment.py) for offline preparation and checks. No private or global factory installation is required.

Follow A1–A8 in the coordinator instructions, including requirement-derived observable outcomes, adversarial boundary checks, decision traceability, and honest limits on evidence. Preserve target repository rules and its engineering workflow. Record the named baseline, allowed paths, exact checks, approved budgets and stops. Keep one isolated writer per worktree and independent acceptance review in a distinct worktree. Keep the accepted handoff uncommitted.

The operating developer approves launch, provider switches, scope or budget changes, external or destructive actions, and commits. A ready verdict or green preflight is not launch approval. Do not launch agents or worktrees, switch providers, install dependencies, commit, push, publish or clean up from this skill without the developer's explicit approval for that exact action. Pause for the developer at the boundary; planning and review keep their established models. The declared writer-only switch policy and a deterministic-provider fixture are not proof of live routing.

## Default for new jobs: coordinate directly

Keep the conversation that clarified the job as coordinator. Follow the coordinator guide for the brief, role policy, budgets, review and handoff gates. Use the sequence below in place of its runner-specific preview, launch and advance commands. Do not load or enable the inbox, create an inbox registration or run `factory-run.py` on this path. Do not switch the mode of an existing job.

1. **Prepare and approve.** Snapshot the named baseline, run preflight and render the brief. Before launch, verify that this Pi session is in the existing Herdr workspace for the target repo and that the required tools and approved role routes are available. Show the developer the exact brief, layout, report and receipt paths outside the target and role worktrees, and a finite wait for each role within its approved allowance. Explain that this conversation stays busy during each wait. Stop for explicit launch approval.
2. **Run and wait for the writer.** In that workspace, create a full-size writer tab with its own Git worktree. No new workspace or split pane. Launch a separate Pi session on the approved writer route, verify its identity and working directory, and submit the brief. Wait only on that agent with an explicit timeout. Read the writer's final message, report and evidence at the agreed paths. An idle or done tab is only a cue to inspect the report. If the role times out, blocks or leaves no valid report and candidate, stop and report the blocker; do not retry or dispatch review on that signal alone.
3. **Run and wait for independent review.** Record the exact candidate identity and verify the copied bytes and Git modes in a separate review worktree. Launch the independent reviewer in another full-size tab of the same workspace on the approved reviewer route. Wait with the same bounded procedure and read the actual receipt and evidence. Advance between approved stages without a routine developer check-in. For in-scope repairs and re-review, use the existing repair limits, retain prior evidence and bind the new review to the revised candidate.
4. **Gate the handoff.** Recheck the unchanged target baseline and run `factory-job.py integration` with the exact candidate and approved receipt. Stop if the candidate or evidence is mismatched, missing or unapproved. Ask before staging; on approval stage only the accepted files, verify bytes and modes, and stop uncommitted. Ask separately before cleanup.

The developer can open another conversation for unrelated work without moving this job. The manual same-workspace flow on macOS is NOT VERIFIED until rehearsed end to end.

## Optional: use the runner

The coordinator-invoked loop is available locally through [factory-run.py](../../scripts/factory-run.py). Use it only if the developer explicitly chooses and approves the runner path for a new job. Follow the runner sequence in the coordinator guide, including [inbox setup](../../docs/factory-handoff.md). The runner still requires inbox records; it is not an inbox-free command. The adapter only notifies; it does not grant approval.

Record exact observations, exits, and skips. These instructions, offline gates and synthetic loop tests do not establish model obedience, process isolation, authenticated provider operation or fresh-platform success.
