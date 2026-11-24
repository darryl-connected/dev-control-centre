# Offline factory contract and gates

One structured JSON manifest defines the job and generates the writer brief. Neither preflight nor integration grants approval, launches a factory, executes command strings, or authenticates anyone. Read the [coordinator instructions](../factory/COORDINATOR.md) for responsibilities and acceptance rules.

## Commands

Run from the kit directory or use absolute paths to the shipped scripts. Save manifest, brief and receipt outside the Git target. Replace the path examples with real paths; the skeleton is structurally valid before snapshot, not approved job data.

```sh
python -B scripts/factory-job.py example > /tmp/job.json
# Fill and approve the job fields, including absolute target and writer paths.
python -B scripts/factory-job.py snapshot /tmp/job.json > /tmp/job-snapshot.json
python -B scripts/factory-job.py preflight /tmp/job-snapshot.json --json
python -B scripts/factory-job.py render /tmp/job-snapshot.json > /tmp/job-brief.md
# Once candidate files are ready, give the reviewer the candidate identity.
python -B scripts/factory-job.py candidate /tmp/job-snapshot.json --candidate /path/to/candidate
# With the independent reviewer's receipt in hand, gate the exact candidate.
python -B scripts/factory-job.py integration /tmp/job-snapshot.json \
  --candidate /path/to/candidate --review /tmp/review.json --json
```

Exit codes: `0` passed the check, `1` rejected, `2` could not run. `snapshot` prints a new manifest; it never overwrites its input. `preflight` checks the contract, live baseline and package alignment. Only the developer can approve launch, and this slice does not implement it.

## Manifest shape

All fields are required. Unknown fields are rejected.

| Field | Shape |
|---|---|
| `version` | `1` |
| `task` | `{id, goal}` |
| `repo` | absolute path to the target Git root |
| `base` | `{commit, status, index_digest, files}` from `snapshot` |
| `allowed_paths` | safe relative exact paths or globs (`*`, `**`, `?`) |
| `frozen` | exact path to SHA-256; may be empty |
| `tier` | `{id: "A" or "B", reason}` |
| `decisions` | `[{id, source}]`, approved decisions |
| `acceptance` | `[{id, source, input, action, expected, observation}]` |
| `guards` | `[{id, decisions, command, boundary, mutation, expected_failure, limits}]` |
| `risks`, `boundaries`, `out_of_scope`, `verification` | non-empty lists of strings; verification identifies the expected commands |
| `evidence`, `stopping_point`, `report` | non-empty strings |
| `budgets` | `{writer: {minutes, calls}, reviewer: {minutes, calls}}`, positive integers. These declare the manifest allowances; for the runner, preview and approve the exact per-attempt assignment limits from [workspace policy](../docs/customization.md#factory-policy-for-new-jobs). Cumulative use is reporting only unless an overall ceiling is explicitly selected. |
| `writer` | `{worktree, model}`; absolute worktree path, attested model |
| `lint_debt` | list of pre-existing warnings; empty when none |

A6 is checked structurally: every decision must map to at least one guard. Acceptance items and guards must reference declared decisions. The other A1–A8 obligations apply to the author and independent reviewer; structural checks are not proof that prose and behaviour agree.

### Path and baseline semantics

- Exact `src/foo.py` does not permit `src/foo.py.bak`. `*` and `?` stay in a segment; `**` crosses segments, and `**/name` also matches at the root. Absolute paths, `.`, `..`, backslashes, empty segments and `.git` are rejected. Prefer exact paths when the approved slice allows it.
- A named full SHA-1 commit, non-empty clean or staged-only content map, exact porcelain status (all untracked files, no rename inference), and SHA-256 of raw `git ls-files --stage -z` output are recorded. Unstaged or untracked baseline work, staged deletions and missing prerequisites are rejected. Carry reviewed staged-only baseline files into the isolated candidate before review.
- Dropping any baseline file fails even inside an allowed directory. Frozen paths must match their reviewed digest and retain their baseline mode. Submodules, non-regular entries other than supported tracked links, and symlink ancestors of mapped paths are rejected.
- A tracked symlink is recorded as mode `120000` and the SHA-256 of its exact `readlink` bytes. Its path and Git blob must agree between HEAD and the index, and its on-disk link bytes must match the blob. Only relative payloads that stay lexically inside the repository are supported. No destination is resolved, checked for existence, or opened. No link may be added, deleted, replaced, or retargeted, even on an allowed path. Snapshot and candidate check their checkout's HEAD/index/worktree agreement; integration also checks link identities against the pinned baseline and uses the same map for the separate review checkout.
- Candidate identity covers working-tree regular file bytes and executable modes and the immutable tracked link metadata. Non-ignored untracked regular files are included; non-ignored untracked symlinks are rejected. Ignored output is excluded. Regular-file index blobs are not part of candidate identity. Transfer reviewed bytes and modes, leaving links untouched; do not transfer the candidate's index. Integration checks that the target is unchanged and the separate candidate belongs to the same Git repository at the base commit.

## Review receipt

The coordinator records the independent reviewer's attestation:

```json
{
  "version": 1,
  "manifest_digest": "...",
  "candidate_digest": "...",
  "verdict": "approved",
  "reviewer": {"model": "openai-codex/gpt-6.1-sol", "worktree": "/abs/review-worktree"},
  "findings": [{"id": "F1", "severity": "low", "status": "closed", "description": "..."}],
  "verification": [
    {"command": "python -B -m unittest", "status": "pass", "evidence": "exit 0; observed expected output", "skipped": []}
  ],
  "mutations": [
    {"guard": "G1", "result": "failed-as-expected", "evidence": "named negative assertion failed on the mutated fixture"}
  ],
  "not_verified": ["physical device GPU behaviour"]
}
```

Integration rejects mismatched manifest or candidate digests, a non-approved verdict, unresolved blocking/high/critical findings, incomplete expected command records, non-passing verification, or incomplete/unsuccessful mutation attestations. The reviewer worktree must be distinct from target, candidate and writer, in the same repository, and contain the same files/modes. The reviewer model must be an exact provider/model identity; model brands and same-model assignments are not independence checks. The standalone gate has no approved runner plan, so for direct coordination the coordinator must match it against the approved route and dispatched worktree. Runner handoff additionally requires the exact planned reviewer identity and dispatched worktree. Neither gate authenticates the model or attestation. Each command record includes a `skipped` list; skips and limitations are NOT VERIFIED. Never approve an unverified critical requirement.

## Tooling alignment

```sh
python -B scripts/factory-alignment.py --json
```

Preflight and integration use the same alignment checks. Resources resolve relative to the package code, not the working directory, target or a private vault. Alignment checks A1–A8 rule IDs, required gate references, generated rather than handwritten briefs, renderer labels and deterministic positive/negative contract probes. It checks the fingerprint of the root `AGENTS.md` Implementation process section and the raw bytes of the named package files, including all role instructions, frozen scope, tests, license and runtime code. The named files and `references/factory-alignment.json` are required local resources. Historical `scripts/validate-brief.py` is advisory only.

```sh
python -B scripts/factory-alignment.py --print-fingerprints > /tmp/fingerprint-proposal.json
```

Review changes to the named sources and fingerprint values independently before deliberately updating the recorded file. Neither a gate nor `--print-fingerprints` rewrites it. The initial fingerprints are part of the candidate for independent review, not a writer's proof of approval. Matching hashes do not establish semantic alignment, execution safety or provenance.

## Evidence and limits

Preflight and integration report local gate wall-clock `duration_ms`. Separately record manual manifest authoring minutes (example to accepted preflight) and receipt authoring minutes (review report to accepted integration) in the local job record. No ledger service is installed.

No gate applies changes, stages, commits, pushes or cleans up. Receipts attest evidence without executing commands; a hash proves file identity, not correctness. Use trusted local Git repositories and configuration. Git status is run with optional index writes and filesystem monitoring disabled. Baseline checks decline repositories with configured Git process or clean filters rather than executing them. The tools are not a network, process or filesystem sandbox and do not protect against concurrent changes. Link checks are for trusted sequential POSIX checkouts, not Windows acceptance or a guarantee about where a link would resolve. Clean HOME relocation does not establish filesystem isolation. Pi instruction loading, live Herdr execution, account access, worker fallback, installers and fresh macOS/Windows acceptance remain NOT VERIFIED.

[License and source attribution](../LICENSE)
