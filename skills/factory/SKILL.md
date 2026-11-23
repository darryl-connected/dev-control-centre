---
name: factory
description: 'Prepare or review a bounded implementation job using the kit contract and offline gates. Use for factory briefs, preflight, review, or uncommitted handoff.'
---

# Factory preparation

You can invoke this skill with `/skill:factory`. Resolve all links relative to this skill directory. Read the repo-owned [coordinator](../../factory/COORDINATOR.md), [worker](../../factory/WORKER.md), [reviewer](../../factory/REVIEWER.md), and [factory contract](../../references/factory-contract.md). Use the shipped [factory job CLI](../../scripts/factory-job.py) and [alignment CLI](../../scripts/factory-alignment.py) for offline preparation and checks. No private or global factory installation is required.

Follow A1–A8 in the coordinator instructions, including requirement-derived observable outcomes, adversarial boundary checks, decision traceability, and honest limits on evidence. Preserve target repository rules and its engineering workflow. Record the named baseline, allowed paths, exact checks, approved budgets and stops. Keep one isolated writer per worktree and independent acceptance review in a distinct worktree. Keep the accepted handoff uncommitted.

The operating developer approves launch, provider switches, scope or budget changes, external or destructive actions, and commits. A ready verdict or green preflight is not launch approval. The coordinator-invoked loop is available locally through [factory-run.py](../../scripts/factory-run.py): preview, one approved launch, record-driven review/repair, exact approved handoff and resumable stop. Do not launch agents or worktrees, switch providers, install dependencies, commit, push, publish or clean up from this skill without the developer's explicit approval for that exact action. Pause for the developer at the boundary; planning and review keep their established models. The declared writer-only switch policy and a deterministic-provider fixture are not proof of live routing.

For a separately approved job, the coordinator may opt into [local handoff notices](../../docs/factory-handoff.md). The adapter only notifies; it does not dispatch work or grant approval. Manual coordination remains available.

Record exact observations, exits, and skips. These instructions, offline gates and synthetic loop tests do not establish model obedience, process isolation, authenticated provider operation or fresh-platform success.
