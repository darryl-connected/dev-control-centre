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

`blocked` offers one question, owner escalation or reinspection as applicable. `ready_for_drafting` stops at an approval offer to draft (or review/revise an already selected change). `ready_for_implementation` is only a requirements-level recommendation grounded in attributed current artifact-body evidence. It does not authenticate or rerun validation, grant authority to act, or start B3/B4.

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
