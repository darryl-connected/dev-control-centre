# Prepare and resume one selected task

Use `/skill:grilling` for source-first clarification. This helper is local, read-only except for approved private revisions, and has no authority to implement, draft OpenSpec artifacts or launch the factory. It makes no ClickUp request and does not read credentials. It needs Python 3.10+ and trusted local Git, an existing [personal workspace](pi-setup.md), a configured repository alias, and the [existing local hub mapping](knowledge-hub.md). Setup does not assess a task. Preserve the target project's own workflow and any explicit-only skill boundary.

## Inspect first

Supply saved JSON from the separate [selected-task B1 reader](clickup.md), not a task URL. A selected task and its bounded imported context are evidence, not actions. Keep inputs and outputs private and outside Git. The helper checks B1's native identity and parent/comment attribution. It records the import hash/time separately from the imported service metadata; no service freshness is observed. Incomplete comment/ancestor evidence or unexpanded replies block dependent claims.

```sh
umask 077
python -B scripts/prepare.py inspect --workspace "$WORKSPACE" --repo cmpl --intake "$INTAKE"
```

Omit `--repo` only when one mapping applies unambiguously. This selects one repository even when it has several workspaces or technology stacks. Association recognizes a leading `PRD000` label in a task/ancestor title and standalone `PRD: PRD000` or `Product requirements: PRD000` lines in task/ancestor/comment text. Distinct explicit IDs conflict, including lists joined by comma, slash, semicolon or `and` in those forms. Similar phrasing or an incidental reference in prose is not a binding. A supplied association carries an attributed reason and does not erase conflicting source evidence. Resolve material disagreements with the source owner rather than assuming the developer's selection settles them.

`context.sources` contains repository-relative paths, SHA-256 of exact bytes, displayed line ranges and actual UTF-8 text. A heading link includes its section; navigation tables show selected rows, not other projects' bodies. Hub commits are clean and physical under the existing adapter policy. The code target need not be clean: selected dirty and untracked working bytes are labeled alongside HEAD, the staged index digest/entry and porcelain-status digest/state. Root and applicable ancestor `AGENTS.md`, available root ownership/configuration and explicitly selected workflow and code paths are read; the helper does not interpret arbitrary links or scan source bodies repo-wide. A target with linked worktree metadata, submodules, executable clean filters, unsupported index flags or unsafe selected paths is blocked. These are sequential checks of trusted local repositories, not an atomic concurrent snapshot or a security sandbox.

## Select context, then author a review packet

An optional `--review "$PACKET"` takes a private version-1 JSON file. Use a selection-only packet first. For example:

```json
{
  "version": 1,
  "task": "abc123",
  "select": {
    "paths": ["packages/reporting/export.ts"],
    "workflow": [".agents/skills/openspec-workflow/SKILL.md"],
    "change": "export-reports"
  }
}
```

Optional `association` takes `prd`, `by` and `reason`, supplied by the developer when needed. `change` is the exact applicable change name, never guessed from task wording. Select the applicable lifecycle and change (if known) under target rules. Unspecified changes are not inventoried; absence of selected artifacts is not a claim that the repository has none. For a selected conventional change the helper reads available `proposal.md`, `design.md`, `tasks.md` and `specs/<capability>/spec.md`; nonstandard layouts cannot establish an implementation recommendation with this helper. It does not run an OpenSpec command. If applicable artifacts already exist, prefer reviewing/revising them to drafting a duplicate.

Read the displayed bodies before adding `review` to that packet. It takes:

| Field | Shape and meaning |
|---|---|
| `context_digest`, `by` | Copy `context.digest` from the current selection; give the reviewer's attributed name. |
| `decisions` | Object keyed by stable decision IDs. Each entry has `state`, `owner`, `citations` and either `state: "settled"` with `value`, or `state: "open"` with `question`. An open decision may carry an `answer` object with `by`, `role`, `text`. Both declared owner and answer role must be `developer` to close it this way. For another owner, keep the blocker and obtain current owner source evidence before recording a settled fact. |
| `scopes` | Object keyed by slice IDs, always including `full`. Each entry has `summary`, an `acceptance` list, a list of `decisions` keys it depends on, and `citations`. `full` must account for all decisions. A proposed independent slice also needs a source-backed `independence` explanation. |
| `scope_approval` | Optional `scope`, `by` and `status` (`approved` or `refused`). Supply only after the developer decides on the presented narrowed scope. Dependent work must remain named and excluded; its blockers do not transfer approval. |
| `source_gaps` | Optional object keyed by gap IDs; each has `reason` and a list of affected `scopes` including `full` if material. Use an empty list for optional context, not invented owners or locations. |
| `assumptions`, `exclusions` | Optional lists of short notes. Keep dependent exclusions visible. Do not include credentials, environment, unrelated source text or authority tokens. |
| `artifact_review` | Optional `change`, `scope`, `reviewed_by`, `validation_by`, `observed_at` (ISO timestamp with offset), `validation` (brief observation), `result` (`passed`, `failed`, `not_observed`), and `citations`. An attributed pass must be for the active scope and cover all complete current artifact bodies in the selected conventional set, including design when present. The active scope also needs a current citation from the selected target-owned workflow. |

Every citation is an object `{ "source": "<source id as shown>", "sha256": "<body hash as shown>", "line": 1, "end_line": 2 }` within a displayed range. Cite the actual settled facts and meaningful gaps. Ask the single `active_question` and wait. An owner-only question remains visible but is not asked as a developer decision. When an answer arrives, retain the original decision key, citations, question and the attributable answer in the reassessed packet. Verify actual scope independence yourself; schema checks do not infer semantic truth or authenticate owners, approval or validation claims.

`blocked` offers one question, owner escalation or reinspection as applicable. `ready_for_drafting` stops at an approval offer to draft (or review/revise an already selected change). `ready_for_implementation` is only a requirements-level recommendation grounded in attributed current artifact-body evidence. It does not authenticate or rerun validation, grant authority to act, or start drafting or the factory.

## Approve a private revision and resume

Inspect can display just the compact plan for save, without exporting full bodies. Review the exact file that would be approved:

```sh
umask 077
python -B scripts/prepare.py inspect --workspace "$WORKSPACE" --repo cmpl \
  --intake "$INTAKE" --review "$PACKET" --plan-only > "$DISPLAYED_PLAN"
python -B scripts/prepare.py save --plan "$DISPLAYED_PLAN" --approve
python -B scripts/prepare.py resume --workspace "$WORKSPACE" --repo cmpl --task abc123
```

No `--approve`, no save. Inspect/resume are read-only; redirects above are the operator's own actions. Approved save rechecks the exact bounded plan and its current parent, then exclusively creates a new revision under `.dcc/tasks/<alias>/<native-id>/`. Task directories and revision files have private POSIX modes (0700/0600); old revisions remain unchanged. Keep the original intake at its approved path if you want a current recheck. Records contain selected citation identities/limited excerpts, decisions, exclusions, owner blockers and next step, not full source exports, authentication, sessions, inboxes or reusable launch approval. Changed mapping, intake or source evidence blocks a current positive assessment and offers reinspection while preserving historical notes. A lineage cannot be silently rebound to another checkout path.

Limits: 32 MiB intake, 4 MiB per selected source, 128 selected sources and 64 MiB aggregate selected bytes, 1 MiB review packet, 8 MiB compact plan/revision, and 128 revisions or 64 MiB aggregate history for one task. Required unavailable, oversized, truncated or drifting bodies cannot count as reviewed. The POSIX safety checks are not a hostile-process sandbox, encrypted storage, a complete secret classifier, or crash/multiple-writer exactly-once storage.

## Draft and validate one new change

The [draft CLI](../scripts/draft.py) is separate from preparation. Use it only when the developer asks for a draft of one new change. Save the current `ready_for_drafting` revision first. It must select the mapped repo, native task and exact change ID. Cite the target-owned workflow in the active scope, including on a narrowed slice; inspect any applicable `openspec/AGENTS.md` or `openspec/changes/AGENTS.md` in preparation. If the change already exists, review it separately. This helper does not revise it or make a duplicate.

Use the target-approved, already-installed OpenSpec 1.8.0 CLI and its compatible Node runtime. Pass an installed executable via `--openspec`, or the JavaScript entry point via `--openspec` with an explicit `--node` executable. There is no install, download, fallback, or access to global OpenSpec configuration. The supported layout has physical `openspec/` and `openspec/changes/` directories and `openspec/config.yaml` with an unquoted top-level `schema: spec-driven`, optionally ordinary `context:` and `rules:` blocks. No custom schemas, central stores, linked planning context or multi-area delta paths. If the target uses a different workflow, stop and follow its process separately.

The coordinator authors Markdown following the target workflow and clarified scope. Keep the private UTF-8 JSON outside Git. For change `export-reports`, provide an object in this shape (the strings below are placeholders, not valid draft content):

```json
{
  "version": 1,
  "artifacts": {
    "openspec/changes/export-reports/proposal.md": "<proposal Markdown>",
    "openspec/changes/export-reports/design.md": "<design Markdown>",
    "openspec/changes/export-reports/tasks.md": "- [ ] Example unchecked task\n",
    "openspec/changes/export-reports/specs/report-export/spec.md": "<delta spec Markdown>"
  }
}
```

Use one to 32 capability deltas. JSON string contents are written as exact UTF-8 bytes; include intended line breaks. Do not supply `.openspec.yaml`: the real CLI generates it in the disposable copy, and the preview displays its exact bytes too. The preview checks `new change` and `status` output against the supported artifact layout and shows the current B2 scope, exclusions and citations. It does not validate Markdown or write into the target.

```sh
umask 077
python -B scripts/draft.py preview --workspace "$WORKSPACE" --repo cmpl --task abc123 \
  --change export-reports --draft "$AUTHORED_JSON" --openspec "$OPENSPEC" > "$DRAFT_PREVIEW"
# Stop here unless the developer approves the displayed paths, contents and scope.
python -B scripts/draft.py apply --plan "$DRAFT_PREVIEW" --approve "$DISPLAYED_SHA256"
```

Copy `approval_sha256` from the reviewed preview. This is an operator assertion for those particular displayed bytes, not authentication or reusable consent. Keep the inputs unchanged. Apply checks the currently saved revision, cited inputs, exact authored bytes, tool entry identities and absence of a change; a drift or newly occupied destination requires a fresh review, not a force flag. OpenSpec runs with a disposable home and telemetry disabled, outside the target. The projection contains exact config and relevant existing main specs, not the whole checkout. Apply requires a real `validate <change> --type change --strict --json --no-interactive` pass before publishing the exact previewed artifacts together. Invalid drafts and refusals write nothing to the target. Success does not change existing spec or app bytes or write the Git index. Nothing calls ClickUp, installs software or launches the factory.

Review the resulting repository artifacts, including unchecked tasks and the actual validation report. If appropriate, re-inspect the task and record current artifact citations through B2. A strict pass is structural, not content approval or evidence of an implementation. Stop before seeking separate launch approval. Limits: 2 MiB authored JSON, 8 MiB canonical plan; local trusted tools and sequential operation only. This is not a process sandbox, concurrent transaction, tool-origin verification, or guarantee against every crash or filesystem error.
