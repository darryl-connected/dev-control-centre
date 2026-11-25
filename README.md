# Developer control centre

ConnectED-first personal workspace for preparing a selected development task, with an optional Pi + Herdr factory. This is a starter kit. [Customize your persona, skills, integrations and workflow](docs/customization.md) without changing target-repository rules or granting external access.

## Start here (macOS)

Already cloned DCC? [Install Pi, sign in, and paste the starter prompt](docs/pi-setup.md#quickstart-macos) from the DCC checkout. Herdr can wait until you’re ready to use the factory.

## Status

This repository ships the DCC-001 offline factory foundation, A14 S1–S3 setup and the B4 coordinator-invoked factory loop. Setup prints a read-only plan, preserves existing workspace settings and can register missing resources after approval. The instruction template is opt-in, with separate shadow acknowledgement. The loop previews an approved job, creates the isolated writer worktree/pane only after explicit launch approval, records each fixed attempt before dispatch, runs independent review in a separate worktree, routes eligible in-scope repairs to the original writer and stages only the accepted exact candidate without committing. It does not install Pi or Herdr or distribute API keys, live sessions or global configuration.

The target workshop is 26 Nov 2026. macOS is the first product validation target; Windows is follow-up scope. The Linux SDK checks are not fresh Mac or Windows evidence. Codex and CC Switch integration are deferred.

## Agreed workflow

Select one ClickUp task, inspect its PRD/meeting/code context, clarify gaps one question at a time, then review readiness. If relevant, preview and separately approve one new OpenSpec draft, validate it and review the repository artifacts. The developer must separately approve any factory launch. Implementation and independent acceptance review preserve evidence and hand off uncommitted work.

- The shipped ClickUp reader is read-only. Write integrations are not shipped; you may build your own with the appropriate access and approval.
- Shared project meeting notes in Git take priority over supplementary personal notes when established. The shared meeting-note process is not established and remains deferred.
- DeepSeek uses the connection setup Darryl already knows, with a separate team API key he will provide. Never put that key in this repository.
- The factory recommends its defaults: `deepseek/deepseek-flash` with model-default reasoning for the writer and `openai/gpt-6.1-sol` with high reasoning for the coordinator and reviewer. Brands, model diversity and a 1M reviewer context are not requirements. Choose exact routes, reasoning and limits for new jobs through [workspace policy](docs/customization.md#factory-policy-for-new-jobs). Review still uses a separate session and worktree. A later approved writer switch preserves progress and never changes the frozen coordinator or reviewer route.
- This personal control centre lives outside target code repositories and must respect their engineering rules.

## Standalone delivery requirements

- **D27: Factory in the repo.** Ship coordinator instructions, worker/reviewer briefs, scripts, gates and dependency setup. The developer's Pi session coordinates jobs, and that developer approves actions. Neither Samson nor his vault or private global setup may be required.
- **D28: Neutral Pi setup.** Ship reproducible Pi + Herdr setup, credential-free configuration and technical operating instructions adapted from Samson's instructions. Keep scope discipline, clarification, approval boundaries and evidence-based verification. Remove Samson's identity/voice, Darryl's personal context and machine-specific assumptions. Ask before changing existing settings.

The offline SDK probe observes actual resource loading and command expansion, not model obedience or live execution. Fresh macOS V9/prepared exercise, full macOS V10 and Windows follow-up are NOT VERIFIED. Authenticated integrations are NOT VERIFIED. A [standalone, read-only ClickUp reader](docs/clickup.md) observes one developer-selected task and bounded parent/comment context. Setup reports the reader without checking authentication or making a request. The [local preparation helper](docs/task-preparation.md) consumes saved selected-task intake, displays verified source bodies, records focused clarification and resumes approved private notes. Preparation does not draft OpenSpec artifacts or authorize launch. The separate [OpenSpec draft helper](docs/task-preparation.md#draft-and-validate-one-new-change) uses the current saved scope and an explicitly approved preview to write one new repository-owned draft after local strict validation. It cannot revise an existing change, sign off content or start the factory. Personal Fathom is optional. The optional local knowledge adapter maps an existing checkout and indexes citations for one explicitly selected PRD. The adapter itself does not copy source bodies or start a task. The coordinator-invoked loop is available locally; live provider and account operation through it is NOT VERIFIED. Registration is not overall readiness or launch approval.

## Documents

- [Agreed scope snapshot](docs/scope.md): decisions, exclusions, acceptance direction and unresolved dependencies.
- [Repository working rules](AGENTS.md): constraints for agents developing this kit.
- [Coordinator](factory/COORDINATOR.md), [worker](factory/WORKER.md) and [reviewer](factory/REVIEWER.md) instructions, plus the coordinator-invoked [loop CLI](scripts/factory-run.py).
- [Opt-in factory handoff](docs/factory-handoff.md): local writer/reviewer notices in one approved persistent conversation; the coordinator still dispatches and verifies.
- [Local knowledge hub](docs/knowledge-hub.md): manual checkout updates, approved mapping and selected-source citations.
- [ClickUp reader](docs/clickup.md) and [API reference](references/clickup-api.md): selected-task intake only. Observed task text is not a readiness verdict or permission to act.
- [Offline factory contract](references/factory-contract.md): CLI walkthrough, manifest and receipt formats and gate limitations.
- [Pi setup and fresh Mac checklist](docs/pi-setup.md), [neutral Pi template](templates/pi/APPEND_SYSTEM.md) and the [setup](skills/setup/SKILL.md), [factory](skills/factory/SKILL.md) and [grilling](skills/grilling/SKILL.md) skills.

The scope is the 18 Nov snapshot of `projects/ConnectED/AI Workshop/developer-control-centre-v1-scope.md` from the Samson vault, including its later amendments and the approved user-owned customization amendment recorded at its end. Its wiki-links refer to that vault, not files shipped here. Shipped SHA-256: `7f763955a7bc13e805167545356e4ddb0e5b2d334c5130faf9988dfba9404364`.

## Adaptation source

The offline factory tools and rules selectively adapt source material under the [MIT license and attribution](LICENSE). The source vault and original kit are not runtime dependencies. Keep development references read-only and do not import them wholesale.

Do not import the seven-question business onboarding, daily planning, general AI-OS audits, personal automation coaching or unrelated admin/publishing integrations.

## Run locally

The offline tooling uses Python 3 standard library (3.10+ syntax; this slice tested with Python 3.15.2) and Git (tested with 2.56.0). No Python packages, provider credentials or network are needed for the gates. From this tree or the extracted archive:

```sh
python -B scripts/factory-alignment.py
python -B scripts/factory-job.py example
python -B scripts/factory-run.py preview --help
python -B scripts/build.py --output /tmp/dcc-dist
python -B scripts/verify-suite.py
```

[`verify-suite.py`](docs/verification.md) defaults to `native`, the portable test profile, including local Git, offline Pi and Herdr evidence. It needs no Linux security tooling. `python -B scripts/verify-suite.py --profile linux-security` selects the separate Linux-only evidence. The command reports selected and excluded suites, checks prerequisites before imports, and passes through the selected suite's status. `--check` does not import or execute tests. Run the required profiles from the checkout or extracted archive in each role's own declared environment. A native pass is not a full-suite pass.

Use [the loop sequence](factory/COORDINATOR.md#job-sequence) for preview, one approved launch, record-driven review/repair and the explicit `handoff --approve` staging stop. The loop reuses the fixed inbox records and existing gates. It never commits, pushes or cleans up.

Use the [contract walkthrough](references/factory-contract.md) to fill the example, snapshot a disposable or explicitly approved target and run preflight. Keep manifests, receipts and test artifacts outside the target. A green gate is not launch approval. Use only trusted local checkouts and Git configuration; these commands are not a sandbox.

The build writes `dev-control-centre.tar.gz` into the requested directory (whose parent must exist). It uses an explicit distribution allowlist and does not install, publish or change global settings. `requirements-dev.txt` pins optional lint/typecheck tooling; use a developer-approved isolated environment provisioned separately. Ruff and mypy are not runtime dependencies. `mypy --check-untyped-defs` is not full type coverage, and Ruff is not a security audit. See [verification prerequisites](docs/verification.md) for the separate native and Linux tool lists. A missing required tool is a blocker, not a skip. The draft runtime takes the approved OpenSpec and Node paths explicitly; it does not install them.

Remaining stages include an approved live provider rehearsal through the shipped loop with independent review and uncommitted handoff, a fresh macOS prepared exercise, and Windows verification. The deterministic-provider loop tests establish local plumbing, record ordering, route selection and exact staging, not authenticated provider operation or model quality. This archive does not establish V1–V10 completion.
