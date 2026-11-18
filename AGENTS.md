# Developer control centre repository rules

## Scope and authority

- Read `README.md` and `docs/scope.md` before proposing or implementing work.
- This repository builds a ConnectED developer control centre, not a general personal AI operating system.
- Current route: Pi + Herdr. Validate macOS first. Windows follows. Codex and CC Switch are deferred.
- The scope snapshot defines product intent, not proof of implemented capabilities or a frozen factory brief.
- Surface conflicting requirements and missing owner decisions. Do not silently broaden the work.

## Implementation process

- Runtime code, configuration, dependencies, assets and CI changes require the coordinated factory process. The product must ship its coordinator instructions, worker/reviewer briefs, scripts, gates and dependency setup in this repository. Do not delegate that responsibility to Samson or rely on a private vault/global installation. The factory is not implemented in this bootstrap; do not pretend it can run before its tooling and a full job contract are available.
- The developer's Pi session is the coordinator. The developer using the kit is the human approver for their jobs; Darryl is not a required runtime approver.
- Start each structured job from a named commit with recorded working-tree state and frozen prerequisite hashes. No implementation job starts from this repository's unborn HEAD.
- Use a bounded manifest with allowed paths, acceptance criteria, observable expected outcomes, verification commands, budgets and a stopping point.
- One writer per isolated branch/worktree, at most two writers concurrently. Independent acceptance review uses a separate worktree and the established reviewer model.
- Guard claims must match what their assertions prove. Demonstrate that realistic injected defects fail the intended guards. Report skips and unavailable checks as NOT VERIFIED.
- Allow at most two repair-and-review rounds within approved scope and budget. Return to the developer using the kit for additional scope, paths or budget.
- Keep accepted results uncommitted until that developer explicitly approves a commit. Commits, pushes, publishing, deployments, destructive operations and cleanup require explicit approval.
- Documentation-only bootstrap work does not claim factory execution or acceptance verification.

## Product boundaries

- Read sources before asking task questions. Ask focused questions one at a time.
- Readiness is not permission to launch the factory. An independent partial slice requires its own approved scope and acceptance criteria.
- ClickUp access is read-only. Do not introduce comments, status changes or other writes as part of v1.
- Shared Git meeting notes are primary context, not automatic authority to amend a PRD. Keep personal meeting intake separate from shared publication.
- Retain source references and task continuity without creating a competing project specification.
- Preserve target repositories' own instructions and engineering/OpenSpec workflows.

## Portable Pi setup

- Ship reproducible Pi + Herdr setup, dependency/version requirements, credential-free configuration and readiness checks. Do not assume the developer has Samson's global agent setup.
- Adapt reusable technical operating instructions: scope discipline, source-first clarification, explicit approvals and evidence-based verification. Remove Samson's identity, voice/persona, Darryl's personal context and machine-specific assumptions.
- Do not copy personal authentication files, private records, unrelated extensions or integrations. Declare and supply setup for every required resource.
- Ask before modifying existing settings; do not silently replace global instructions or configuration.
- Prove actual instruction loading and the complete prepared workflow on a fresh macOS developer environment with no Samson vault or personal global setup. Use only the repository, declared prerequisites and independently supplied credentials/access.
- Documentation-only checks do not establish any of those runtime outcomes.

## Models and secrets

- Encode the known DeepSeek connection setup in credential-free instructions/configuration rather than requiring access to Darryl's machine or memory. Darryl will provide a separate team API key. Do not reopen provisioning research without a new need and approval.
- Never include real keys, tokens, personal meeting records or copied global credentials in distributed files.
- DeepSeek fallback is implementation-workers-only. Pause and preserve progress before offering a switch, then wait for explicit developer approval.
- Planning and acceptance review retain established models. Exhausted allowance pauses those stages; it does not authorise a provider switch.
- Known connection setup does not prove worker/reviewer isolation. Verify the boundary during implementation.
- Do not modify Samson's global factory policy or a user's global harness configuration as a side effect.

## Reuse

- During kit development, leave `../ai-os-kit` unchanged. Selectively adapt reviewed material, preserving applicable licenses and attribution. The shipped product must not depend on that sibling repository or any private development source.
- Do not import unrelated business onboarding, daily-priority management, personal admin or general-purpose framework work.
- Ask before changing existing files beyond the agreed task. Confirm renames, moves and deletions first.
