# Developer control centre

ConnectED-first personal workspace for preparing a selected development task and coordinating its implementation through Pi + Herdr.

## Status

This repository ships the DCC-001 offline factory foundation, A14 S1–S3 setup and the B4 coordinator-invoked factory loop. Setup prints a read-only plan and can create three workspace-local files after explicit approval and instruction-shadow acknowledgement. The loop previews an approved job, creates the isolated writer worktree/pane only after explicit launch approval, records each fixed attempt before dispatch, runs independent review in a separate worktree, routes one in-scope repair to the original writer and stages only the accepted exact candidate without committing. It does not install Pi or Herdr or distribute API keys, live sessions or global configuration.

The target workshop is 26 Nov 2026. macOS is the first product validation target; Windows is follow-up scope. The Linux SDK checks are not fresh Mac or Windows evidence. Codex and CC Switch integration are deferred.

## Agreed workflow

Select one ClickUp task, inspect its PRD/meeting/code context, clarify gaps one question at a time, then review readiness. If relevant, preview and separately approve one new OpenSpec draft, validate it and review the repository artifacts. The developer must separately approve any factory launch. Implementation and independent acceptance review preserve evidence and hand off uncommitted work.

- ClickUp is read-only.
- Shared project meeting notes in Git take priority over supplementary personal notes when established. The shared meeting-note process is not established and remains deferred.
- DeepSeek uses the connection setup Darryl already knows, with a separate team API key he will provide. Never put that key in this repository.
- `deepseek/deepseek-flash` is the default implementation writer from the first attempt, using its supported reasoning default. `openai/gpt-6.1-sol` with high reasoning coordinates and independently reviews. A later writer switch is writer-only, preserves progress and requires explicit approval of a route named in the plan; it never changes the coordinator or reviewer route. Planning and review retain their established models.
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

The scope is the 18 Nov snapshot of `projects/ConnectED/AI Workshop/developer-control-centre-v1-scope.md` from the Samson vault, including its later 18 Nov amendments and the approved B4 O18 model-policy and attempt-budget amendments recorded at its end. Its wiki-links refer to that vault, not files shipped here. Shipped SHA-256: `deaf692dd0d407c1f7606698224fc48d80cedfde48acc0c4e6d3dceee2ce89d8`.

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
python -B -m unittest discover -s tests -p 'test_*.py'
```

Use [the loop sequence](factory/COORDINATOR.md#job-sequence) for preview, one approved launch, record-driven review/repair and the explicit `handoff --approve` staging stop. The loop reuses the fixed inbox records and existing gates. It never commits, pushes or cleans up.

Use the [contract walkthrough](references/factory-contract.md) to fill the example, snapshot a disposable or explicitly approved target and run preflight. Keep manifests, receipts and test artifacts outside the target. A green gate is not launch approval. Use only trusted local checkouts and Git configuration; these commands are not a sandbox.

The build writes `dev-control-centre.tar.gz` into the requested directory (whose parent must exist). It uses an explicit distribution allowlist and does not install, publish or change global settings. `requirements-dev.txt` pins optional lint/typecheck tooling; use a developer-approved isolated environment provisioned separately. Ruff and mypy are not runtime dependencies. `mypy --check-untyped-defs` is not full type coverage, and Ruff is not a security audit. The full suite requires the Pi 1.4.0 SDK and Node specified in the setup guide; set `DCC_PI_SDK_MODULE` to its absolute `dist/index.js` path. A missing SDK is an evidence blocker, not a skip. The Linux handoff tests also require the absolute Pi 1.4.0 CLI via `DCC_PI_EXECUTABLE` and the existing `unshare`/kernel controls described in the handoff guide.

The draft end-to-end tests additionally require preinstalled OpenSpec 1.8.0 and its Node runtime. Set `DCC_B3_OPENSPEC` to the absolute path of its JavaScript entry point and `DCC_B3_NODE` to the absolute path of Node. Missing those prerequisites is an evidence blocker, not a skip. The draft runtime takes the approved tool paths explicitly; it does not install them.

Remaining stages include an approved live provider rehearsal through the shipped loop with independent review and uncommitted handoff, a fresh macOS prepared exercise, and Windows verification. The Linux deterministic-provider loop tests establish local plumbing, record ordering, route selection and exact staging, not authenticated provider operation or model quality. This archive does not establish V1–V10 completion.
