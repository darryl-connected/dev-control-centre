---
type: spec
status: active
date: 2026-11-18
topic: [ai-onboarding, developer-tooling, sdd-workflow]
owner: Darryl Lim
workshop: 2026-11-26
scope_state: agreed
implementation_state: not-started
---

# Developer control centre: v1 scope

## Purpose and status

Build a ConnectED developer control centre in the separate `dev-control-centre` repository, selectively adapting useful material from `ai-os-kit`. Developers use it to clarify an assigned task, retain its context and manage coding subagents through the factory. The source kit and Samson vault are development references, not required installations on developers' computers.

This records scope agreed during the 18 Nov grilling session and amended later that day: Pi + Herdr is the only current route, Darryl will provide a separate team API key using the known DeepSeek setup, and the repo must ship its own factory process and neutral Pi setup. A separate local repository has a documentation-only bootstrap. No runnable setup or factory implementation exists yet. This scope is not a frozen factory brief or evidence that any integration works.

The workshop teaches one workflow through the kit:

**Select task → inspect sources → clarify gaps → review readiness → developer starts factory → implement and independently review → preserve result and handoff.**

## Agreed decisions

References preserve the codes used in the scope conversation. D1-D3 were earlier proposals, not additional decisions recorded here.

| Reference | Agreement |
|---|---|
| D4 | Skip the existing seven-question business onboarding. |
| D5 | Include the code factory so the workspace coordinates coding subagents. |
| D6 | Include ClickUp context retrieval and Fathom meeting-note processing. |
| D7 | Include a task-starting procedure based on clarification before development, as discussed with CJ and Li Yin. |
| D8 | Task preparation stops at a readiness review. The developer explicitly decides when to start the factory. A ready verdict is not launch permission. |
| D9 | Default to one ClickUp task, informed by its parent PRD, relevant meetings and code. Flag wider gaps rather than adopting them as work. |
| D10 | Build one workflow through Pi + Herdr. Codex adaptation is deferred, not a current delivery requirement. |
| D11 | Build and validate macOS first. Windows remains required follow-up scope, not a simultaneous first-release blocker. Do not claim Windows support before end-to-end verification. |
| D12 | Pi + Herdr is the supported setup. Herdr manages agent terminals/workspaces; the factory supplies the execution and verification controls. |
| D13 | Shared project meeting notes take priority over personal meeting notes. Developers can process their own individual meetings as supplementary context. JM and KH are proposed shared-note contributors, not confirmed assigned owners. |
| D14 | ClickUp is read-only in v1. Developers may build write integrations themselves after the workshop; these are not v1 acceptance criteria. |
| D15 | Shared notes live in Git. Inspect KH's existing setup before proposing another repository or collection. Its suitability for meeting notes is not yet confirmed. |
| D16 | Task start inspects available sources before interviewing the developer. Ask focused questions one at a time. Separate answerable questions from decisions needing another owner. |
| D17 | V1 is ConnectED-first. Keep company-specific locations and identifiers configurable, without building a general-purpose configuration framework. |
| D18 | Each developer has a personal control centre outside the code repositories. It reads shared context and coordinates coding work through explicit repo mappings. |
| D19 | Replace business onboarding with guided technical configuration and verification. Ask only for missing configuration and report readiness/blockers. Personal Fathom access can be optional because shared notes support the core workflow. |
| D20 | The first complete run uses a prepared, realistic exercise, not live assigned production work. |
| D21 | Revised 18 Nov: Pi + Herdr only for now. This supersedes the two-route workshop requirement. Codex and CC Switch compatibility checks are outside current scope. Windows remains required follow-up after macOS. |
| D22 | V1 supports delivery of a selected task, not daily prioritisation or a complete personal AI operating system. Personal productivity extensions are for developers to add on their own time. |
| D23 | A material requirement gap can leave one part blocked while an explicitly narrowed, independent slice proceeds. Its acceptance criteria and independence must be established, then approved by the developer before factory launch. Otherwise the affected work waits. |
| D24 | Revised 18 Nov: use the DeepSeek connection setup Darryl already knows, with a separate API key he will provide for the team. Do not reopen provisioning research. This clarification is not evidence that the kit's worker-only routing has been tested. |
| D25 | DeepSeek fallback is for implementation workers only. Planning and acceptance review retain the established models. Exhausted planning/review allowance means pausing those stages, not silently changing their provider. |
| D26 | Switching an implementation worker to DeepSeek requires explicit developer approval. Pause, preserve progress and offer the switch; no automatic fallback. |
| D27 | Ship a self-contained factory process in the repository: coordinator instructions, worker/reviewer briefs, scripts, gates and dependency declarations/setup. The developer's Pi session coordinates jobs; the developer using it approves actions. No dependency on Samson being present, the Samson vault or Darryl's private machine configuration. |
| D28 | Provide Pi setup and neutral technical instructions adapted from Samson's operating instructions. Preserve scope discipline, clarification, approval boundaries and evidence-based verification. Remove Samson's identity, voice/persona, Darryl's personal context and machine-specific assumptions. Include required configuration and dependency setup without copying credentials or silently overwriting existing settings. |

## Functional boundary

### C1: Guided technical setup

- Configure the personal workspace, target code repositories and shared knowledge location.
- Verify required repository access, ClickUp reads and the Pi + Herdr factory route.
- Distinguish configured, working, optional and blocked capabilities.
- Ask only for missing configuration. Do not repeat the business/voice/revenue interview.
- Keep credentials and personal information out of the distributed kit.
- Setup is not permission to overwrite global harness settings or install software without approval.

### C2: Project and personal meeting context

- Consume the shared Git collection as primary meeting context.
- Include a Fathom intake/processing procedure for publishing contributors and optional personal use.
- Keep personal intake separate from shared publication. Do not automatically publish private meetings.
- Retain source references so developers can trace the statements used during preparation.
- Shared-note precedence does not turn a meeting statement into an approved PRD amendment. Surface material source conflicts for resolution rather than silently choosing new behaviour.
- Inspect KH's collection and contribution conventions before designing another structure.

### C3: Interactive task start

- Start from one selected ClickUp task.
- Read the task, relevant PRD sections/comments, shared notes, relevant personal notes and project/code instructions before asking questions.
- Identify confirmed scope, assumptions, contradictions, dependencies and missing decisions.
- Interview the developer one question at a time. Do not ask questions already answered in accessible sources.
- Produce a readiness review with proposed scope, acceptance criteria, blocked work and questions needing an owner.
- Where partial progress is possible, explain why the proposed slice is independent of the unresolved decision.
- Stop for the developer's decision. No coding factory launch follows automatically.
- Keep reports and proposed clarification text local; do not write to ClickUp.

### C4: Factory execution

- Adapt the existing coordinated factory rather than treating its skill file alone as an implementation.
- Ship the required factory scripts, contracts, coordinator instructions, worker/reviewer briefs and Pi + Herdr orchestration in this repository. Declare external dependencies and provide their setup; do not assume a globally installed private factory.
- Preserve bounded jobs, isolated writers, independent acceptance review, evidence-based verification and human-controlled external/destructive actions.
- The developer's Pi session acts as coordinator using the shipped process. The developer using the kit approves launch, fallback switches, commits, pushes, destructive/external actions and scope/budget changes. Darryl is not a required runtime approver for their jobs.
- Implement the task/brief/evidence format and orchestration for Pi + Herdr. Preserve the existing factory acceptance standard.
- Preserve project-owned engineering rules and the existing development/OpenSpec workflow rather than replacing them with personal copies.
- Retain the source factory's default uncommitted handoff. Task-start or factory-launch approval does not authorise commits, pushes or publishing.
- Apply D25-D26 to model fallback. Demonstrate writer/reviewer provider separation; a global provider switch alone is not proof of role isolation.

### C5: Task continuity

- Preserve task context, decisions, blocked questions, implementation progress and verification evidence in the personal workspace.
- Support resuming after a session boundary or an approved worker-provider change.
- Preserve the task record across fresh Pi sessions and approved worker-provider changes. Cross-harness transfer is outside current scope.
- Keep current project truth linked to its source rather than treating personal notes as a competing specification.

### C6: Portable Pi setup and operating instructions

- Provide reproducible Pi + Herdr setup with required versions, dependencies, configuration and readiness checks documented in the repo.
- Adapt the reusable technical parts of Samson's Pi instructions. Do not distribute his identity, voice/persona, Darryl's personal profile, private records or machine-specific paths.
- Keep approval and verification rules explicit. Instructions alone are not evidence of enforced gates.
- Distribute credential-free configuration templates and instructions for supplying credentials locally, including the separate team DeepSeek key through the known connection setup.
- Do not require developers to access the Samson vault, copy its global agent directory or install its unrelated extensions, skills or integrations.
- Make any required resource explicit and available through the repo or declared dependency setup. Do not silently inherit it from the development machine.
- Detect existing settings and require approval before changing them. Never copy authentication files or overwrite global instructions as a side effect.
- Validate on a fresh developer environment using only this repository, declared prerequisites and independently supplied credentials/access.

These are required capabilities, not a frozen list of skill names or a file layout.

## Delivery sequence

| Reference | Stage | Completion evidence |
|---|---|---|
| A13 | Prove standalone setup in a fresh macOS developer environment. | Use shipped setup and instructions without the Samson vault or personal global configuration, then complete the prepared factory exercise. |
| A6 | Prove macOS Pi + Herdr first. | Complete the prepared task through context gathering, clarification, approval, factory execution, review and handoff. |
| A8 | Rehearse the Pi + Herdr workshop route and approved DeepSeek worker fallback. | Demonstrate task continuity, setup readiness and the developer approval boundaries before teaching them. |
| A12 | Add and validate Windows support after the macOS baseline. | Reproduce the complete supported route on Windows; successful installation alone is insufficient. Exact timing and environment are not yet agreed. |

Pi + Herdr on macOS is the route for the 26 Nov workshop. Codex adaptation (formerly A7) is deferred and is not required for current completion.

Most developers being on Macs is Darryl's planning assumption, not a verified attendee inventory.

## Workshop acceptance direction

The first complete run uses a small, prepared repository and realistic task/PRD/meeting context. It must exercise the following observable outcomes. Exact fixtures, commands and job budgets belong in the implementation brief.

| Reference | Input or action | Expected outcome and observation |
|---|---|---|
| V1 | Run technical setup with a missing required dependency or inaccessible source. | Setup identifies the specific blocker instead of reporting the route ready. Optional personal Fathom access does not block an otherwise working core route. |
| V2 | Start the prepared task with an intentional requirement gap/source conflict. | Preparation cites the relevant sources, asks focused questions and preserves unanswered owner decisions rather than implementing a guess. |
| V3 | Complete clarification and obtain a ready verdict. | No factory starts until the developer explicitly requests it. Inspect the actual launch behaviour, not just report wording. |
| V4 | Leave a material decision unresolved while proposing an unaffected slice. | The review names the exclusion and explains independence. The developer approves the narrowed brief; dependent behaviour is not implemented. |
| V5 | Execute the approved prepared task. | Isolated implementation and independent review yield the requirement-defined observable result. A realistic injected defect must fail the intended guard. |
| V6 | Simulate an exhausted implementation allowance. | Work pauses with a resumable record. No DeepSeek request occurs before approval; after approval only implementation uses the fallback. Planning/review remain on their configured providers. |
| V7 | Resume from a fresh Pi session, including after an approved worker-provider change. | The task's decisions, exclusions, progress and evidence remain available without pretending live sessions have transferred. |
| V8 | Run v1 preparation against ClickUp. | Task context is retrieved without comments, status changes or other ClickUp mutations. A read-only label alone is not evidence of this boundary. |
| V9 | In a fresh macOS developer environment, use only this repository, declared prerequisites and independently supplied credentials/access. No Samson vault or personal global setup is available. | Shipped instructions and tooling support setup and the prepared task through explicit developer approval, isolated implementation, independent review and uncommitted handoff. The developer's Pi session coordinates without fetching private Samson resources or requiring Darryl to approve their job. Inspect actual execution and dependencies, not only instruction wording. |
| V10 | Load the shipped neutral instructions in Pi; exercise setup both with no personal settings and with existing settings present. | Verify Pi actually loads the intended instructions without Samson's identity, voice/persona or Darryl's personal context. Setup identifies required configuration and asks before changing existing settings; an unapproved run leaves them unchanged. Check loaded resources and file changes rather than relying only on assistant responses. |

Passing this exercise does not establish reliability across the production monorepo, all real requirements, every app version or Windows before its own validation.

## Explicitly out of scope for v1

- X1: The seven-question business onboarding and its voice/revenue/personal-priority setup.
- X2: Daily planning, backlog prioritisation, general AI-OS audits, personal automation coaching and unrelated publishing/admin tools.
- X3: ClickUp writes, including comments, status changes, task creation, reassignment and PRD edits.
- X4: General-purpose multi-company configuration, Codex adaptation, CC Switch compatibility checks or additional harnesses. Windows remains the agreed follow-up platform after macOS.
- X5: Automatic factory launch, automatic DeepSeek fallback or taking wider feature work merely because task preparation discovers it.
- X6: Automatic publication of personal meetings or granting broader source access than the developer already has.
- X7: Automatic commits, pushes, deployments or production changes during a coding job.
- X8: Building a replacement shared knowledge service before inspecting KH's existing repository.
- X9: Changes to Samson's global factory policy as a side effect of adapting the separate developer kit.

## Dependencies and unresolved implementation work

| Reference | Open item | Current status |
|---|---|---|
| U1 | KH's knowledge-base repo location, current contents, meeting-note suitability and access. | The 2 Nov meeting records a repo being built, not a verified current deployment. Inspect before designing its integration. |
| U2 | Shared-note publishing and corrections. | JM/KH are suggested contributors. Confirm ownership and conventions; do not treat them as assigned. |
| U3 | Codex app orchestration and CC Switch compatibility. | Deferred by revised D21. Not a current implementation dependency or workshop acceptance requirement. |
| U4 | Separate team DeepSeek API key. | Darryl will provide the key using the connection setup he already knows. No new provisioning research is required. Keep the key out of the distributed kit and verify worker-only routing under V6; that behaviour is not established by the known connection setup. |
| U5 | Factory contract/model adaptation. | The current Samson factory explicitly excludes DeepSeek. Implement the approved kit-specific writer fallback without silently changing global rules. Resolve the exact model/role configuration in the build contract. |
| U6 | Per-job budgets, concurrency, commands, repair limits and exact integration paths. | Inspect the implementation and freeze a full factory manifest before coding. This scope document is not that manifest. |
| U7 | Windows environment and delivery date. | Support is required after macOS; native/WSL strategy and timing are not settled. |
| U8 | Workshop time slot, attendee machines/accounts and prerequisites. | Confirm before fixing lesson timings or claiming setup readiness for everyone. |
| U9 | Standalone factory packaging and neutral Pi setup. | Required by D27-D28, not implemented. Inspect reusable dependencies, package the factory process/tooling and provide neutral instructions and setup. Resolve resource loading and version requirements in the build brief; prove absence of private-machine dependencies under V9-V10. |

## Accepted risks

- R1: Pi + Herdr only reduces integration and rehearsal work but leaves no Codex route for developers who prefer it. Codex support is deferred.
- R2: Shared notes depend on contributors keeping them current. Git history does not itself establish freshness or correctness.
- R3: Separate personal workspaces require correct repo mappings and source tracking.
- R4: Independent partial work can still be affected by later decisions if its assumed independence is wrong.
- R5: DeepSeek writer fallback reduces pressure on the usual allowance but cannot replace exhausted planning/review capacity under D25.
- R6: A controlled exercise can miss real-project complexity. Report its limits and validate broader use separately.
- R7: Shipping the factory and Pi setup makes their versions, dependencies and updates the kit's responsibility. A working personal installation can hide missing resources; fresh-environment verification is required.

## Sources

- S1: Darryl's 18 Nov 2026 scope-grilling conversation. Final instruction: "yes do it then commit and push", approving this scope file and an appended decision entry, followed by commit and push of those changes.
- S2: [[projects/ConnectED/meetings/2026-11-04 - chat-with-cj]]: plan-first workflow, task context, personal orchestration workspace, skills and verification discussion.
- S3: [[projects/ConnectED/meetings/2026-11-10 - chat-with-li-yin]]: clarify unknowns before the OpenSpec proposal; connected tools, persistent planning context and separate review.
- S4: [[projects/ConnectED/meetings/2026-11-05 - kl-workshop-gathering-plans]]: 24-27 Nov working week and 26 Nov AI workshop.
- S5: [[projects/ConnectED/meetings/2026-11-02 - weekly-tech-pm-sync]]: planned KH knowledge-base repo with current consolidated architecture and historical PRD snapshots.
- S6: `$SAMSON_CODE_DIR/ai-os-kit/README.md`, `AGENTS.md` and `skills/onboard/SKILL.md`, inspected during scoping: current general-purpose kit and seven-question onboarding.
- S7: [[.pi/skills/factory/SKILL]]: current Samson factory roles, contracts, verification and orchestration baseline. No global rules changed.
- S8 (historical research, not a current dependency): [CC Switch](https://github.com/farion1231/cc-switch), [DeepSeek routing guide](https://github.com/farion1231/cc-switch/blob/main/docs/guides/codex-deepseek-routing-guide-en.md), [desktop model visibility](https://github.com/farion1231/cc-switch/blob/main/docs/guides/codex-desktop-custom-model-visibility-en.md) and [official auth preservation](https://github.com/farion1231/cc-switch/blob/main/docs/guides/codex-official-auth-preservation-guide-en.md), inspected 18 Nov. Repository documentation, not a local runtime verification.
- S9: [[decisions/log#2026-11-18 - ConnectED developer control centre v1 scope]]: original decision record for this scope.
- S10: [[decisions/log#2026-11-18 - Developer control centre narrowed to Pi and Herdr]]: later amendment approved by Darryl in this session. Pi + Herdr only for now; use the known DeepSeek setup with a separate team API key.
- S11: Darryl's later 18 Nov clarification: Samson will not be on developers' computers; the factory process must ship in the repo, with Pi setup and operating instructions stripped of Samson's voice. Samson proposed D27-D28 and fresh-environment acceptance; Darryl replied "yes my boy".
- S12: [[decisions/log#2026-11-18 - Ship the factory and neutral Pi setup with the developer kit]]: decision record for D27-D28. The private operating manual was inspected as an adaptation source, not copied into the kit.
