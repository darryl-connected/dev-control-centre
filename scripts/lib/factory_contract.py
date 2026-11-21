"""
factory_contract.py — Shared contract for factory job manifests and gates.

Single source of truth for:
- the structured manifest shape and validation rules
- the worker-brief renderer
- the legacy Markdown brief check (advisory only)
- baseline, candidate and content-map helpers
- tooling alignment checks and reviewed-source fingerprints

The gate is not a security boundary. A review receipt is an attestation that
binds a file set to a verdict; it does not prove the commands were run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TypeGuard

PACKAGE_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = 1
RULE_IDS = tuple(f"A{i}" for i in range(1, 9))

TIERS = ("A", "B")
TOP_LEVEL_KEYS = {
    "version",
    "task",
    "repo",
    "base",
    "allowed_paths",
    "frozen",
    "tier",
    "decisions",
    "acceptance",
    "guards",
    "risks",
    "boundaries",
    "out_of_scope",
    "verification",
    "evidence",
    "stopping_point",
    "report",
    "budgets",
    "writer",
    "lint_debt",
}
BASE_KEYS = {"commit", "status", "index_digest", "files"}
LINK_MODE = "120000"
ENTRY_MODES = ("100644", "100755", LINK_MODE)
AGENT_KEYS = {"worktree", "model"}
BUDGET_KEYS = {"minutes", "calls"}
DECISION_KEYS = {"id", "source"}
ACCEPTANCE_KEYS = {"id", "source", "input", "action", "expected", "observation"}
GUARD_KEYS = {
    "id",
    "decisions",
    "command",
    "boundary",
    "mutation",
    "expected_failure",
    "limits",
}
TIER_KEYS = {"id", "reason"}
TASK_KEYS = {"id", "goal"}
REVIEW_KEYS = {
    "version",
    "manifest_digest",
    "candidate_digest",
    "verdict",
    "reviewer",
    "findings",
    "verification",
    "mutations",
    "not_verified",
}
REVIEW_REVIEWER_KEYS = {"model", "worktree"}
FINDING_KEYS = {"id", "severity", "status", "description"}
VERIFICATION_KEYS = {"command", "status", "evidence", "skipped"}
MUTATION_KEYS = {"guard", "result", "evidence"}

# Authorisation lines. A brief that omits one of these is not a valid job.
PROHIBITIONS = (
    ("handoff", "no hand-offs", r"do not hand off|no hand-?offs?"),
    (
        "subagents",
        "no sub-agents",
        r"do not spawn sub-agents|no sub-agents|do not spawn subagents",
    ),
    ("commits", "no commits", r"do not commit|no commits"),
    ("pushes", "no pushes", r"do not push|no push"),
    ("network", "no network", r"do not use the network|no network|without network|no external network"),
    ("worktrees", "no worktrees or panes", r"do not create worktrees|no worktrees"),
)

AGENTS_READ_RE = r"read AGENTS\.md"
COMMIT_RE = re.compile(r"\b(?:base commit|based on)\b[^0-9a-f\n]{0,20}([0-9a-f]{7,40}|NONE)\b", re.IGNORECASE)
FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
SOL_MODEL_RE = re.compile(r"(?:[a-z0-9][a-z0-9_.-]*/)?gpt-[0-9]+(?:\.[0-9]+)*-sol")
PLACEHOLDER_RE = re.compile(r"<[A-Za-z][^<>\n]{0,80}>")

# Markdown fields kept only for historical briefs. New jobs use the manifest.
MARKDOWN_FIELDS = (
    ("task", "task ID", (r"^\s*(?:#+\s*)?TASK\b", r"\btask id\b")),
    ("base", "base commit", (r"base commit\b", r"\bbased on\b")),
    ("allowed_paths", "allowed paths", (r"allowed paths?\b",)),
    (
        "acceptance",
        "acceptance criteria or required outcome",
        (r"acceptance criteria\b", r"required outcome\b"),
    ),
    ("out_of_scope", "explicit out of scope", (r"^\s*(?:#+\s*|\*\*\s*)?out[- ]of[- ]scope\b",)),
    ("review_tier", "review tier (A or B)", (r"review tier\b",)),
    ("acceptance_examples", "acceptance examples", (r"acceptance examples?\b",)),
    ("risk_cases", "risk cases", (r"risk cases?\b",)),
    ("boundaries", "real/mocked boundaries", (r"\bboundaries\b",)),
    ("defect_demonstration", "defect demonstration", (r"defect demonstration\b", r"mutation demonstration\b")),
    (
        "not_proven",
        "what each guard does not prove",
        (r"does not prove\b", r"what escapes\b", r"still passes this guard\b"),
    ),
    ("verification", "verification commands", (r"verification commands?\b",)),
    ("budget", "budget", (r"\bbudget\b",)),
    ("stopping_point", "stopping point", (r"stopping point\b",)),
    ("report_format", "report format", (r"\bFINISH\b", r"\breport format\b")),
)

ALIGNMENT_SECTION_FINGERPRINTS = (
    ("AGENTS.md", "## Implementation process"),
)

ALIGNMENT_FILE_FINGERPRINTS = (
    "LICENSE",
    "README.md",
    "docs/scope.md",
    "factory/COORDINATOR.md",
    "factory/WORKER.md",
    "factory/REVIEWER.md",
    "requirements-dev.txt",
    "scripts/build.py",
    "scripts/lib/factory_contract.py",
    "scripts/factory-job.py",
    "scripts/factory-alignment.py",
    "scripts/validate-brief.py",
    "tests/test_factory_job.py",
    "tests/test_factory_alignment.py",
    "tests/test_validate_brief.py",
    "tests/test_instruction_packaging.py",
    "tests/test_e2e_factory.py",
    "templates/pi/APPEND_SYSTEM.md",
    "references/factory-contract.md",
)

ALIGNMENT_FINGERPRINT_PATH = "references/factory-alignment.json"


class ContractError(Exception):
    """Raised when a tool cannot read or resolve its input (exit code 2)."""


# --------------------------------------------------------------------------- #
# Canonical hashing and git helpers
# --------------------------------------------------------------------------- #


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def manifest_digest(manifest: dict) -> str:
    return sha256_text(canonical_json(manifest))


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    env.update(
        GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="",
        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
        LC_ALL="C",
    )
    try:
        raw = subprocess.run(
            ["git", "-C", str(repo), "-c", "core.fsmonitor=false", *args],
            capture_output=True,
            check=False,
            env=env,
        )
        result = subprocess.CompletedProcess(
            raw.args, raw.returncode, stdout=raw.stdout.decode("utf-8", errors="surrogateescape"),
            stderr=raw.stderr.decode("utf-8", errors="surrogateescape"),
        )
    except OSError as error:
        raise ContractError(f"git is unavailable: {error}") from error
    if check and result.returncode != 0:
        raise ContractError(
            f"git {' '.join(args)} failed in {repo}: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def real_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def repo_toplevel(repo: str | Path) -> Path:
    root = real_path(repo)
    if not root.is_dir():
        raise ContractError(f"repository path does not exist: {root}")
    result = git(root, "rev-parse", "--show-toplevel", check=False)
    if result.returncode != 0:
        raise ContractError(f"not a git repository: {root}")
    top = real_path(result.stdout.removesuffix("\n"))
    if top != root:
        raise ContractError(f"path is not the repository root: {root} (root is {top})")
    return top


def git_common_dir(repo: str | Path) -> Path:
    root = real_path(repo)
    result = git(root, "rev-parse", "--git-common-dir")
    path = Path(result.stdout.removesuffix("\n"))
    return real_path(path if path.is_absolute() else root / path)


def resolve_commit(repo: str | Path, rev: str) -> str:
    root = real_path(repo)
    result = git(root, "rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}", check=False)
    if result.returncode != 0:
        raise ContractError(f"commit does not exist in {root}: {rev}")
    return result.stdout.strip()


def index_digest(repo: Path) -> str:
    result = git(repo, "ls-files", "--stage", "-z")
    return sha256_bytes(result.stdout.encode("utf-8", errors="surrogateescape"))


def worktree_status(repo: Path) -> list[str]:
    # Git status can execute process or clean filters. Decline those checkouts
    # rather than running programs configured in the target repository.
    filters = git(repo, "config", "--name-only", "--get-regexp", r"^filter\..*\.(process|clean)$", check=False)
    if filters.returncode == 0:
        raise ContractError("baseline status cannot use Git repositories with configured process or clean filters")
    if filters.returncode != 1:
        raise ContractError(f"cannot inspect Git configuration in {repo}: {filters.stderr.strip()}")
    result = git(
        repo, "status", "--porcelain=v1", "--untracked-files=all",
        "--no-renames", "--ignore-submodules=all",
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def is_staged_only(status_lines: Iterable[str]) -> tuple[bool, str]:
    for line in status_lines:
        if line.startswith("??"):
            return False, f"untracked path in baseline: {line[3:]}"
        if len(line) < 4 or line[1:3] != "  ":
            return False, f"unstaged or invalid change in baseline: {line}"
        if line[0] == "D":
            return False, f"staged deletion in baseline: {line}"
        if line[0] not in "AMT":
            return False, f"unsupported status in baseline: {line}"
    return True, ""


def _tracked_entries(repo: Path) -> list[tuple[str, str, str]]:
    result = git(repo, "ls-files", "--stage", "-z")
    entries: list[tuple[str, str, str]] = []
    for record in result.stdout.split("\0"):
        if not record:
            continue
        try:
            meta, path = record.split("\t", 1)
            mode, oid, stage = meta.split(" ")
        except ValueError as error:
            raise ContractError(f"cannot parse index entry: {record!r}") from error
        if stage != "0":
            raise ContractError(f"unmerged index entry: {path}")
        entries.append((mode, oid, path))
    return entries


def _head_link_ids(repo: Path) -> dict[str, str]:
    links = {}
    tree = git(repo, "--no-replace-objects", "ls-tree", "-r", "--full-tree", "-z", "HEAD")
    for record in tree.stdout.split("\0"):
        if record:
            meta, path = record.split("\t", 1)
            mode, _kind, oid = meta.split(" ")
            if mode == LINK_MODE:
                links[path] = oid
    return links


def _require_unchanged_links(expected: dict[str, str], observed: dict[str, str], boundary: str) -> None:
    for path in sorted(expected.keys() | observed.keys()):
        if observed.get(path) != expected.get(path):
            raise ContractError(f"{boundary}: symlink added, removed, replaced or retargeted: {path}")


def _link_digests(files: dict[str, dict]) -> dict[str, str]:
    return {path: entry["sha256"] for path, entry in files.items() if entry.get("mode") == LINK_MODE}


def _safe_relative(path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute() or path.startswith("~"):
        raise ContractError(f"absolute path is not allowed: {path}")
    if "\\" in path:
        raise ContractError(f"backslash path is not allowed: {path}")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ContractError(f"unsafe path: {path}")
    if any(part.lower() == ".git" for part in parts):
        raise ContractError(f"path inside .git is not allowed: {path}")
    if "\x00" in path or re.search(r"[\ud800-\udfff]", path):
        raise ContractError(f"path is not valid UTF-8 text: {path!r}")
    return path


def _validate_link_payload(path: str, payload: bytes) -> None:
    # POSIX lexical containment only. Never stat, resolve or open the destination.
    if not payload or payload.startswith(b"/"):
        raise ContractError(f"symlink target must be relative: {path}")
    depth = path.count("/")
    for part in payload.split(b"/"):
        if part == b"..":
            depth -= 1
            if depth < 0:
                raise ContractError(f"symlink target escapes the repository: {path}")
        elif part not in (b"", b"."):
            depth += 1


def _file_entry(root: Path, path: str, *, tracked_link: bool = False) -> dict:
    _safe_relative(path)
    full = root / path
    try:
        for parent in reversed(full.relative_to(root).parents):
            if parent == Path("."):
                continue
            mode = (root / parent).lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ContractError(f"symlink parent is not allowed: {path}")
            if not stat.S_ISDIR(mode):
                return {"deleted": True}
        info = full.lstat()
    except FileNotFoundError:
        return {"deleted": True}
    if stat.S_ISLNK(info.st_mode):
        if not tracked_link:
            raise ContractError(f"symlink is not allowed unless tracked at HEAD and in the index: {path}")
        payload = os.readlink(os.fsencode(full))
        _validate_link_payload(path, payload)
        return {"sha256": sha256_bytes(payload), "mode": LINK_MODE}
    if tracked_link:
        raise ContractError(f"tracked symlink was replaced in the worktree: {path}")
    if not stat.S_ISREG(info.st_mode):
        raise ContractError(f"not a regular file: {path}")
    return {
        "sha256": sha256_bytes(full.read_bytes()),
        "mode": "100755" if info.st_mode & 0o111 else "100644",
    }


def content_map(repo: str | Path) -> dict[str, dict]:
    """Map every tracked and untracked non-ignored path to its content and mode.

    Ignored files are excluded by design: build output is not candidate content.
    Only unchanged HEAD/index/worktree symlinks are mapped, without following them.
    """
    root = repo_toplevel(repo)
    tracked = _tracked_entries(root)
    head_links = _head_link_ids(root)
    index_links = {path: oid for mode, oid, path in tracked if mode == LINK_MODE}
    _require_unchanged_links(head_links, index_links, "index symlink drift from HEAD")
    result: dict[str, dict] = {}
    for index_mode, _, path in tracked:
        if index_mode not in ENTRY_MODES:
            kind = "submodule" if index_mode == "160000" else "non-regular index entry"
            raise ContractError(f"{kind} is not allowed: {path}")
        result[path] = _file_entry(root, path, tracked_link=index_mode == LINK_MODE)
    head_digests = {}
    for path, oid in head_links.items():
        # Undo the git wrapper's lossless decode; hash the raw blob, including non-UTF-8 bytes.
        blob = git(root, "--no-replace-objects", "cat-file", "blob", oid).stdout
        head_digests[path] = sha256_bytes(blob.encode("utf-8", errors="surrogateescape"))
    _require_unchanged_links(head_digests, _link_digests(result), "worktree symlink drift from HEAD")
    others = git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout
    for path in others.split("\0"):
        if path:
            result[path] = _file_entry(root, path)
    return result


def candidate_digest(manifest_digest_value: str, files: dict[str, dict]) -> str:
    return sha256_text(canonical_json({"manifest": manifest_digest_value, "files": files}))


def capture_baseline(repo: str | Path) -> dict:
    root = repo_toplevel(repo)
    commit = resolve_commit(root, "HEAD")
    # Refuse unsafe entries and ancestors before asking Git to inspect checkout status.
    files = content_map(root)
    status = worktree_status(root)
    staged_only, reason = is_staged_only(status)
    if not staged_only:
        raise ContractError(f"baseline is not clean or staged-only: {reason}")
    if not files or not FULL_SHA_RE.fullmatch(commit):
        raise ContractError("baseline requires a full 40-character commit SHA and a non-empty content map")
    for path, entry in files.items():
        if entry.get("deleted"):
            raise ContractError(f"baseline prerequisite is missing: {path}")
    return {
        "commit": commit,
        "status": status,
        "index_digest": index_digest(root),
        "files": files,
    }


# --------------------------------------------------------------------------- #
# Path patterns
# --------------------------------------------------------------------------- #


def _glob_to_regex(pattern: str) -> str:
    _safe_relative(pattern)
    out: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if pattern.startswith("**/", i):
                out.append("(?:.*/)?")
                i += 3
                continue
            if pattern.startswith("**", i):
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
            continue
        if char == "?":
            out.append("[^/]")
            i += 1
            continue
        out.append(re.escape(char))
        i += 1
    return "".join(out)


def path_is_allowed(path: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if "*" in pattern or "?" in pattern:
            if re.fullmatch(_glob_to_regex(pattern), path):
                return True
        elif path == pattern:
            return True
    return False


def validate_patterns(patterns: Iterable[str], field: str, errors: list[str]) -> None:
    seen = set()
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern.strip():
            errors.append(f"{field}: every entry must be a non-empty string")
            continue
        try:
            _safe_relative(pattern)
        except ContractError as error:
            errors.append(f"{field}: {error}")
            continue
        if pattern in seen:
            errors.append(f"{field}: duplicate pattern {pattern}")
        seen.add(pattern)


# --------------------------------------------------------------------------- #
# Manifest validation
# --------------------------------------------------------------------------- #


def _nonempty(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def _is_int(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _keys(obj: dict, allowed: set, field: str, errors: list[str]) -> None:
    for key in obj:
        if key not in allowed:
            errors.append(f"{field}: unknown key {key!r}")


def _string_list(value: Any, field: str, errors: list[str], allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{field}: must be a list of strings")
        return []
    if not allow_empty and not value:
        errors.append(f"{field}: must not be empty")
    cleaned = []
    for item in value:
        if not _nonempty(item):
            errors.append(f"{field}: every entry must be a non-empty string")
            continue
        cleaned.append(item.strip())
    return cleaned


def validate_manifest(data: Any, require_baseline: bool = True) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for a manifest. Never touches the network."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["manifest: must be a JSON object"], warnings
    _keys(data, TOP_LEVEL_KEYS, "manifest", errors)

    version = data.get("version")
    if not _is_int(version) or version != SCHEMA_VERSION:
        errors.append(f"version: must be {SCHEMA_VERSION}")

    task = data.get("task")
    if not isinstance(task, dict):
        errors.append("task: must be an object")
    else:
        _keys(task, TASK_KEYS, "task", errors)
        for key in ("id", "goal"):
            if not _nonempty(task.get(key)):
                errors.append(f"task.{key}: must be a non-empty string")

    repo = data.get("repo")
    if not _nonempty(repo):
        errors.append("repo: must be an absolute path string")
    elif not Path(repo).is_absolute():
        errors.append("repo: must be an absolute path")

    base = data.get("base")
    if not isinstance(base, dict):
        errors.append("base: must be an object (run snapshot)")
    else:
        _keys(base, BASE_KEYS, "base", errors)
        commit = base.get("commit")
        if not isinstance(commit, str):
            if require_baseline or commit not in (None, ""):
                errors.append("base.commit: must be a full 40-character lowercase commit SHA")
        elif commit == "":
            if require_baseline:
                errors.append("base.commit: a full commit SHA is required (run snapshot)")
        elif not FULL_SHA_RE.fullmatch(commit):
            errors.append("base.commit: must be a full 40-character lowercase commit SHA")
        status = base.get("status")
        if not isinstance(status, list) or not all(_nonempty(line) for line in status):
            errors.append("base.status: must be a list of git status lines")
        else:
            staged_only, reason = is_staged_only(status)
            if not staged_only:
                errors.append(f"base.status: {reason}")
        digest = base.get("index_digest")
        if not (not require_baseline and digest == "") and (
            not isinstance(digest, str) or not HASH_RE.fullmatch(digest)
        ):
            errors.append("base.index_digest: must be a sha256 hex digest (run snapshot)")
        files = base.get("files")
        if files is not None or not require_baseline:
            if not isinstance(files, dict):
                errors.append("base.files: must be an object of path -> entry")
            else:
                for path, entry in files.items():
                    try:
                        _safe_relative(path)
                    except ContractError as error:
                        errors.append(f"base.files: {error}")
                    if not isinstance(entry, dict):
                        errors.append(f"base.files[{path}]: must be an object")
                        continue
                    if entry.get("deleted") is True:
                        errors.append(f"base.files[{path}]: baseline prerequisite must not be deleted")
                        continue
                    _keys(entry, {"sha256", "mode"}, f"base.files[{path}]", errors)
                    if not isinstance(entry.get("sha256"), str) or not HASH_RE.fullmatch(entry["sha256"]):
                        errors.append(f"base.files[{path}]: sha256 must be a 64-character digest")
                    if entry.get("mode") not in ENTRY_MODES:
                        errors.append(f"base.files[{path}]: mode must be 100644, 100755 or 120000")
                if require_baseline and not files:
                    errors.append("base.files: a non-empty baseline content map is required (run snapshot)")
        elif require_baseline:
            errors.append("base.files: baseline content map is required (run snapshot)")

    allowed = data.get("allowed_paths")
    if not isinstance(allowed, list) or not allowed:
        errors.append("allowed_paths: must be a non-empty list")
    else:
        validate_patterns(allowed, "allowed_paths", errors)

    frozen = data.get("frozen")
    if not isinstance(frozen, dict):
        errors.append("frozen: must be an object of exact path -> sha256 (may be empty)")
    else:
        for path, digest in frozen.items():
            try:
                _safe_relative(path)
            except ContractError as error:
                errors.append(f"frozen: {error}")
            if "*" in path or "?" in path:
                errors.append(f"frozen[{path}]: frozen entries must be exact paths")
            if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
                errors.append(f"frozen[{path}]: must be a 64-character sha256 digest")

    tier = data.get("tier")
    if not isinstance(tier, dict):
        errors.append("tier: must be an object")
    else:
        _keys(tier, TIER_KEYS, "tier", errors)
        if tier.get("id") not in TIERS:
            errors.append("tier.id: must be A or B")
        if not _nonempty(tier.get("reason")):
            errors.append("tier.reason: must state why the tier applies")

    decisions = data.get("decisions")
    decision_ids: set[str] = set()
    if not isinstance(decisions, list) or not decisions:
        errors.append("decisions: must be a non-empty list of approved decisions")
    else:
        for index, decision in enumerate(decisions):
            field = f"decisions[{index}]"
            if not isinstance(decision, dict):
                errors.append(f"{field}: must be an object")
                continue
            _keys(decision, DECISION_KEYS, field, errors)
            if not _nonempty(decision.get("id")):
                errors.append(f"{field}.id: must be a non-empty string")
            elif decision["id"] in decision_ids:
                errors.append(f"{field}.id: duplicate decision {decision['id']}")
            else:
                decision_ids.add(decision["id"])
            if not _nonempty(decision.get("source")):
                errors.append(f"{field}.source: must name where the decision is recorded")

    acceptance = data.get("acceptance")
    acceptance_ids: set[str] = set()
    if not isinstance(acceptance, list) or not acceptance:
        errors.append("acceptance: must be a non-empty list")
    else:
        for index, item in enumerate(acceptance):
            field = f"acceptance[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{field}: must be an object")
                continue
            _keys(item, ACCEPTANCE_KEYS, field, errors)
            for key in ("source", "input", "action", "expected", "observation"):
                if not _nonempty(item.get(key)):
                    errors.append(f"{field}.{key}: must be a non-empty string")
            item_id = item.get("id")
            if not _nonempty(item_id):
                errors.append(f"{field}.id: must be a non-empty string")
            elif item_id in acceptance_ids:
                errors.append(f"{field}.id: duplicate acceptance {item_id}")
            else:
                acceptance_ids.add(item_id)
            source = item.get("source")
            if _nonempty(source) and source.strip() not in decision_ids:
                errors.append(f"{field}.source: unknown decision {source!r}")
            if _nonempty(item.get("source")) and not re.search(
                r"\b(?:given|when|action|input|draw|tap|click|run)\b", f"{item.get('action')} {item.get('input')}", re.IGNORECASE
            ):
                warnings.append(f"{field}.action: state an input or user action explicitly")

    guards = data.get("guards")
    mapped: set[str] = set()
    guard_ids: set[str] = set()
    if not isinstance(guards, list) or not guards:
        errors.append("guards: must be a non-empty list")
    else:
        for index, guard in enumerate(guards):
            field = f"guards[{index}]"
            if not isinstance(guard, dict):
                errors.append(f"{field}: must be an object")
                continue
            _keys(guard, GUARD_KEYS, field, errors)
            guard_id = guard.get("id")
            if not _nonempty(guard_id):
                errors.append(f"{field}.id: must be a non-empty string")
            elif guard_id in guard_ids:
                errors.append(f"{field}.id: duplicate guard {guard_id}")
            else:
                guard_ids.add(guard_id)
            refs = guard.get("decisions")
            if not isinstance(refs, list) or not refs:
                errors.append(f"{field}.decisions: must list at least one approved decision")
            else:
                for ref in refs:
                    if not _nonempty(ref) or ref.strip() not in decision_ids:
                        errors.append(f"{field}.decisions: unknown decision {ref!r}")
                    else:
                        mapped.add(ref.strip())
            for key in ("command", "boundary", "mutation", "expected_failure", "limits"):
                if not _nonempty(guard.get(key)):
                    errors.append(f"{field}.{key}: must be a non-empty string")

    for missing in sorted(decision_ids - mapped):
        errors.append(f"decisions: {missing} is approved but not mapped to any guard (A6)")

    for key in ("risks", "boundaries", "out_of_scope", "verification"):
        entries = _string_list(data.get(key), key, errors)
        if key == "verification" and len(entries) != len(set(entries)):
            errors.append("verification: duplicate commands")
    for key in ("evidence", "stopping_point", "report"):
        if not _nonempty(data.get(key)):
            errors.append(f"{key}: must be a non-empty string")

    budgets = data.get("budgets")
    if not isinstance(budgets, dict):
        errors.append("budgets: must be an object")
    else:
        for agent in ("writer", "reviewer"):
            record = budgets.get(agent)
            field = f"budgets.{agent}"
            if not isinstance(record, dict):
                errors.append(f"{field}: must be an object")
                continue
            _keys(record, BUDGET_KEYS, field, errors)
            for key in ("minutes", "calls"):
                value = record.get(key)
                if not _is_int(value) or value <= 0:
                    errors.append(f"{field}.{key}: must be a positive integer")
        _keys(budgets, {"writer", "reviewer"}, "budgets", errors)

    writer = data.get("writer")
    if not isinstance(writer, dict):
        errors.append("writer: must be an object")
    else:
        _keys(writer, AGENT_KEYS, "writer", errors)
        for key in ("worktree", "model"):
            if not _nonempty(writer.get(key)):
                errors.append(f"writer.{key}: must be a non-empty string")
        if _nonempty(writer.get("worktree")) and not Path(writer["worktree"]).is_absolute():
            errors.append("writer.worktree: must be an absolute path")

    debt = data.get("lint_debt")
    if not isinstance(debt, list):
        errors.append("lint_debt: must be a list (empty when there is none)")
    else:
        for item in debt:
            if not _nonempty(item):
                errors.append("lint_debt: entries must be non-empty strings")

    return errors, warnings


# --------------------------------------------------------------------------- #
# Example manifest and brief rendering
# --------------------------------------------------------------------------- #


def example_manifest(repo_hint: str = "/absolute/path/to/repo") -> dict:
    return {
        "version": SCHEMA_VERSION,
        "task": {"id": "TASK-ID", "goal": "One-line goal"},
        "repo": repo_hint,
        "base": {
            "commit": "",
            "status": [],
            "index_digest": "",
            "files": {},
        },
        "allowed_paths": ["src/example.py"],
        "frozen": {},
        "tier": {"id": "A", "reason": "test-only change with no runtime code"},
        "decisions": [{"id": "D1", "source": "approved requirement reference"}],
        "acceptance": [
            {
                "id": "C1",
                "source": "D1",
                "input": "the exact input or fixture",
                "action": "the user or test action",
                "expected": "the independently expected outcome",
                "observation": "how the outcome is observed",
            }
        ],
        "guards": [
            {
                "id": "G1",
                "decisions": ["D1"],
                "command": "verification command that exercises C1",
                "boundary": "the real boundary exercised (storage, renderer, migration)",
                "mutation": "a realistic injected defect at that boundary",
                "expected_failure": "the observation that must fail under the mutation",
                "limits": "what still passes this guard",
            }
        ],
        "risks": ["the failure and edge case this task guards"],
        "boundaries": ["what is real and what is mocked, with the reason"],
        "out_of_scope": ["what this task must not touch or build"],
        "verification": ["the approved verification command, in order"],
        "evidence": "exits, counts, before/after and mutation evidence to produce",
        "stopping_point": "stop on budget, new scope or an unverifiable critical requirement",
        "report": "report outcomes, evidence, NOT VERIFIED items and open findings",
        "budgets": {
            "writer": {"minutes": 60, "calls": 120},
            "reviewer": {"minutes": 45, "calls": 90},
        },
        "writer": {"worktree": "/absolute/path/to/candidate-worktree", "model": "writer-model"},
        "lint_debt": [],
    }


def _bullets(values: Iterable[str], indent: str = "- ") -> str:
    return "\n".join(f"{indent}{value}" for value in values)


def render_brief(manifest: dict) -> str:
    """Render a deterministic worker brief. Only validated manifests should reach this."""
    decisions = {item["id"]: item["source"] for item in manifest.get("decisions", [])}
    lines: list[str] = []
    lines.append(
        "You are a worker agent in a software factory job. A coordinator owns the plan. "
        "You own exactly one task."
    )
    lines.append("")
    lines.append("BEFORE ANYTHING ELSE: read AGENTS.md at the repository root. It is the working contract for this repository.")
    lines.append("")
    lines.append(
        "Authorisation: implementation is authorised. Do not hand off. Do not spawn sub-agents. "
        "Do not create worktrees or panes. Do not commit. Do not push. Do not use the network. "
        "Leave your change uncommitted."
    )
    lines.append("")
    task = manifest.get("task", {})
    lines.append(f"TASK {task.get('id', '')}. {task.get('goal', '')}")
    lines.append("")
    lines.append(f"Base commit: {manifest.get('base', {}).get('commit') or 'NOT SNAPSHOTTED'}")
    lines.append(f"Target repository: {manifest.get('repo', '')}")
    lines.append(f"Writer worktree: {manifest['writer']['worktree']}")
    lines.append(f"Writer model: {manifest['writer']['model']}")
    lines.append(f"Review tier: {manifest['tier']['id']}; {manifest['tier']['reason']}")
    lines.append("")
    lines.append("Allowed paths: " + ", ".join(manifest["allowed_paths"]) + ". Everything else is out of scope.")
    for path, digest in sorted(manifest["frozen"].items()):
        lines.append(f"- Frozen: {path} (SHA-256 {digest})")
    for item in manifest["lint_debt"]:
        lines.append(f"- Pre-existing lint debt: {item}")
    lines.append("")
    lines.append("Required outcome:")
    for item in manifest.get("acceptance", []):
        lines.append(f"- {item['id']} (from {item['source']}): {item.get('expected', '')}")
    lines.append("")
    lines.append("Acceptance examples:")
    for item in manifest.get("acceptance", []):
        lines.append(
            f"- {item['id']}: input {item.get('input', '')} -> action {item.get('action', '')} "
            f"-> independently expected {item.get('expected', '')} -> observed by {item.get('observation', '')}"
        )
    lines.append("")
    lines.append("Decision traceability (A6): every approved decision maps to an executable guard.")
    lines.append("")
    lines.append("| Decision | Source | Guard | Guard command |")
    lines.append("|---|---|---|---|")
    for guard in manifest.get("guards", []):
        for ref in guard.get("decisions", []):
            lines.append(
                f"| {ref} | {decisions.get(ref, '')} | {guard['id']} | {guard.get('command', '')} |"
            )
    lines.append("")
    lines.append("Defect demonstration:")
    for guard in manifest.get("guards", []):
        lines.append(f"- {guard['id']} at {guard['boundary']}: inject {guard['mutation']}; {guard['expected_failure']}")
    lines.append("")
    lines.append("What each guard does not prove:")
    for guard in manifest.get("guards", []):
        lines.append(f"- {guard['id']}: {guard.get('limits', '')}")
    lines.append("")
    lines.append("Risk cases:")
    lines.append(_bullets(manifest.get("risks", [])))
    lines.append("")
    lines.append("Boundaries:")
    lines.append(_bullets(manifest.get("boundaries", [])))
    lines.append("")
    lines.append("Out of scope:")
    lines.append(_bullets(manifest.get("out_of_scope", [])))
    lines.append("")
    lines.append("Evidence you must produce:")
    lines.append(manifest.get("evidence", ""))
    lines.append("")
    lines.append("Verification commands:")
    for index, command in enumerate(manifest.get("verification", []), 1):
        lines.append(f"{index}. {command}")
    lines.append("")
    budgets = manifest.get("budgets", {})
    writer_budget = budgets.get("writer", {})
    reviewer_budget = budgets.get("reviewer", {})
    lines.append(
        f"Budget: writer {writer_budget.get('minutes', '')} minutes and {writer_budget.get('calls', '')} tool calls; "
        f"reviewer {reviewer_budget.get('minutes', '')} minutes and {reviewer_budget.get('calls', '')} tool calls. "
        "Up to two repair rounds inside those totals."
    )
    lines.append(f"Stopping point: {manifest.get('stopping_point', '')}")
    lines.append("")
    lines.append(f"FINISH: {manifest.get('report', '')}. Never report a check as passing unless you ran it.")
    return "\n".join(lines) + "\n"


TEMPLATE_BRIEF = """You are a legacy worker agent. Base commit <sha>.

BEFORE ANYTHING ELSE: read AGENTS.md at the repository root.

Authorisation: do not hand off. Do not spawn sub-agents. Do not create worktrees or panes. Do not commit. Do not push. Do not use the network.

TASK <id>. <one-line goal>

Base commit: <sha>
Allowed paths: <exact files>. Everything else is out of scope.
Out of scope: <what this task must not touch or build>

Required outcome: <numbered, checkable>
Review tier: <A or B, and why>

Acceptance examples: <source -> input or user action -> independently expected outcome -> how it is observed>
Risk cases: <the failure and edge cases this task must guard>
Boundaries: <what is real, what is mocked and why>
Defect demonstration: <a realistic injected defect and the assertion that must fail>
What each guard does not prove: <per guard, what still passes it>

Evidence you must produce: <commands, before/after, mutation evidence>
Verification commands: <approved commands, in order>
Budget: <wall-clock limit> and <tool-call limit>.
Stopping point: <when to stop>.

FINISH: report <fields>, under <N> lines. Never report a check as passing unless you ran it.
"""


# --------------------------------------------------------------------------- #
# Legacy Markdown brief check (advisory only)
# --------------------------------------------------------------------------- #


def _field_value(body: str, pattern: str) -> str | None:
    for match in re.finditer(pattern, body, re.IGNORECASE | re.MULTILINE):
        line_end = body.find("\n", match.end())
        if line_end == -1:
            line_end = len(body)
        rest = body[match.end() : line_end].lstrip(" *:`")
        rest = rest.strip()
        if rest and not rest.startswith("<"):
            return rest
        # A heading or empty label: take the next list item or plain paragraph
        # line, but stop at the next label so an empty field cannot borrow it.
        for line in body[line_end:].splitlines()[1:]:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                break
            if stripped.startswith("<"):
                break
            if re.match(r"^[A-Za-z][A-Za-z /_-]{0,40}:", stripped):
                break
            return stripped.lstrip("-*# ").strip()
    return None


def check_markdown_brief(text: str, repo: str | Path | None = None) -> tuple[list[str], list[str]]:
    """Advisory check for historical Markdown briefs. Not the authorising gate."""
    body = text.replace("**", "").replace("`", "")
    errors: list[str] = []
    warnings: list[str] = ["legacy Markdown brief: advisory only; structured jobs use factory-job.py"]
    for _key, label, patterns in MARKDOWN_FIELDS:
        if not any(_field_value(body, pattern) for pattern in patterns):
            errors.append(f"missing or empty field: {label}")

    if not re.search(AGENTS_READ_RE, body, re.IGNORECASE):
        errors.append("missing instruction to read AGENTS.md at the repository root")
    for _key, label, pattern in PROHIBITIONS:
        if not re.search(pattern, body, re.IGNORECASE):
            errors.append(f"missing authorisation line: {label}")

    commit = COMMIT_RE.search(body)
    if commit is None:
        errors.append("base commit is not stated as a SHA or NONE")
    elif re.fullmatch(r"[0-9a-f]{7,40}", commit.group(1), re.IGNORECASE) is None and commit.group(1) != "NONE":
        errors.append(f"base commit is not a commit SHA or NONE: {commit.group(1)}")
    elif repo and re.fullmatch(r"[0-9a-f]{7,40}", commit.group(1), re.IGNORECASE):
        try:
            resolve_commit(repo, commit.group(1))
        except ContractError as error:
            errors.append(str(error))
    elif re.fullmatch(r"[0-9a-f]{7,40}", commit.group(1), re.IGNORECASE):
        warnings.append("base commit SHA format checked only; pass --repo to verify it exists")

    budget = re.search(r"\bbudget\b", body, re.IGNORECASE)
    if budget:
        window = body[budget.end() : budget.end() + 400].lstrip().split("\n\n")[0]
        if not re.search(r"\b\d+\s*(?:min|minute)", window, re.IGNORECASE):
            errors.append("budget states no wall-clock limit (minutes)")
        if not re.search(r"\b\d+\s*(?:tool[- ]?)?calls?\b", window, re.IGNORECASE):
            errors.append("budget states no tool-call limit")
    else:
        errors.append("budget states no wall-clock limit (minutes)")
        errors.append("budget states no tool-call limit")

    tier = re.search(r"review tier\b[:\s]*([A-Za-z0-9]+)", body, re.IGNORECASE)
    if tier and tier.group(1).upper() not in TIERS:
        errors.append(f"review tier must be A or B: {tier.group(1)}")

    placeholders = sorted(set(PLACEHOLDER_RE.findall(text)))
    if placeholders:
        shown = ", ".join(placeholders[:6]) + (", ..." if len(placeholders) > 6 else "")
        warnings.append(f"unfilled template placeholder(s): {shown}")
    return errors, warnings


# --------------------------------------------------------------------------- #
# Alignment
# --------------------------------------------------------------------------- #


def extract_section(text: str, heading: str) -> str | None:
    lines = text.splitlines()
    level = len(heading) - len(heading.lstrip("#"))
    start = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == heading or stripped.startswith(heading + " "):
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("#"):
            this_level = len(stripped) - len(stripped.lstrip("#"))
            if this_level <= level:
                end = index
                break
    return "\n".join(lines[start:end]).strip("\n") + "\n"


def _local_resource(root: Path, path: str) -> Path:
    full = root / path
    if full.resolve() != full:
        raise ContractError(f"alignment resource must not be a symlink: {path}")
    return full


def alignment_source_hash(root: Path, path: str, section: str | None) -> str | None:
    full = _local_resource(root, path)
    if not full.is_file():
        return None
    if section is None:
        return sha256_bytes(full.read_bytes())
    extracted = extract_section(full.read_text(encoding="utf-8"), section)
    return None if extracted is None else sha256_text(extracted)


def expected_fingerprint_entries() -> list[dict]:
    entries: list[dict] = [
        {"path": path, "section": section}
        for path, section in ALIGNMENT_SECTION_FINGERPRINTS
    ]
    entries.extend({"path": path, "section": None} for path in ALIGNMENT_FILE_FINGERPRINTS)
    return entries


def load_fingerprints(root: Path) -> dict | None:
    path = _local_resource(root, ALIGNMENT_FINGERPRINT_PATH)
    if not path.is_file():
        return None
    data = read_json(path, "fingerprints")
    version = data.get("version")
    if (
        set(data) != {"version", "note", "entries"}
        or not _is_int(version) or version != SCHEMA_VERSION
        or not _nonempty(data.get("note")) or not isinstance(data.get("entries"), list)
    ):
        raise ContractError(f"{ALIGNMENT_FINGERPRINT_PATH}: malformed fingerprint header or entries")
    return data


def _probe_alignment() -> list[tuple[str, str]]:
    """Deterministic contract probes. Each returns (name, failure) or (name, '')."""
    failures: list[tuple[str, str]] = []

    valid = example_manifest()
    errors, _ = validate_manifest(valid, require_baseline=False)
    failures.append(("probe.valid_manifest", "; ".join(errors)))

    broken = example_manifest()
    broken["task"]["goal"] = ""
    errors, _ = validate_manifest(broken, require_baseline=False)
    failures.append(("probe.empty_field_rejected", "" if errors else "an empty goal was accepted"))

    broken = example_manifest()
    broken["budgets"]["writer"]["minutes"] = True
    errors, _ = validate_manifest(broken, require_baseline=False)
    failures.append(("probe.bool_budget_rejected", "" if errors else "a bool budget was accepted"))

    broken = example_manifest()
    broken["guards"] = []
    errors, _ = validate_manifest(broken, require_baseline=False)
    failures.append(
        ("probe.unmapped_decision_rejected", "" if errors else "an unmapped decision was accepted")
    )

    broken = example_manifest()
    broken["unexpected"] = "x"
    errors, _ = validate_manifest(broken, require_baseline=False)
    failures.append(
        ("probe.unknown_key_rejected", "" if errors else "an unknown key was accepted")
    )

    broken = example_manifest()
    broken["guards"][0]["mutation"] = ""
    errors, _ = validate_manifest(broken, require_baseline=False)
    failures.append(
        ("probe.empty_mutation_rejected", "" if errors else "a blank mutation was accepted")
    )

    legacy = """TASK X. goal
Base commit: deadbee
read AGENTS.md
Authorisation: do not hand off. Do not spawn sub-agents. Do not commit. Do not push. Do not use the network.
Allowed paths:
Required outcome:
Out of scope:
Review tier: B
Acceptance examples:
Risk cases:
Boundaries:
Defect demonstration:
What each guard does not prove:
Verification commands:
Budget: 1 minute and 1 call.
Stopping point:
FINISH:
"""
    errors, _ = check_markdown_brief(legacy)
    failures.append(
        ("probe.legacy_empty_labels_rejected", "" if errors else "empty Markdown labels were accepted")
    )

    rendered = render_brief(valid)
    needed = [
        "read AGENTS.md",
        "Do not commit",
        "Do not push",
        "Do not use the network",
        "Do not hand off",
        "Do not spawn sub-agents",
        "Decision traceability",
        "Defect demonstration",
        "What each guard does not prove",
        "Verification commands",
        "Budget:",
        "FINISH:",
    ]
    missing = [item for item in needed if item.lower() not in rendered.lower()]
    failures.append(
        (
            "probe.rendered_brief_complete",
            f"rendered brief is missing: {', '.join(missing)}" if missing else "",
        )
    )
    return failures


def alignment_check(root: str | Path | None = None) -> dict:
    """Check factory tooling alignment. Structural and reviewed-source drift only.

    It does not prove that prose and behaviour mean the same thing. Semantic
    alignment stays NOT VERIFIED.
    """
    base = real_path(root or PACKAGE_ROOT)
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    coordinator_path = _local_resource(base, "factory/COORDINATOR.md")
    coordinator_text = coordinator_path.read_text(encoding="utf-8") if coordinator_path.is_file() else ""
    testing_contract = extract_section(coordinator_text, "## Testing contract") or ""
    missing_rules = [rule for rule in RULE_IDS if not re.search(rf"\*\*{rule}\b", testing_contract)]
    record("rules", not missing_rules, f"missing rule IDs: {', '.join(missing_rules)}" if missing_rules else "A1-A8 present")

    gate_terms = ("factory-job.py", "factory-alignment.py")
    record(
        "coordinator_gate_reference",
        all(term in coordinator_text for term in gate_terms),
        "coordinator instructions must reference factory-job.py and factory-alignment.py",
    )

    record(
        "no_legacy_template",
        extract_section(coordinator_text, "## Brief template") is not None
        and "You are a worker agent in a software factory pilot. You are in <repo>" not in coordinator_text,
        "coordinator instructions must point to the generated brief, not the superseded handwritten template",
    )

    agents_path = _local_resource(base, "AGENTS.md")
    agents_text = agents_path.read_text(encoding="utf-8") if agents_path.is_file() else ""
    implementation_rules = extract_section(agents_text, "## Implementation process") or ""
    record(
        "agents_gate_reference",
        all(term in implementation_rules for term in gate_terms),
        "AGENTS.md factory section must point at the structured gate",
    )

    if coordinator_text:
        rendered = render_brief(example_manifest())
        required_labels = [
            "Decision traceability",
            "Defect demonstration",
            "Acceptance examples",
            "Risk cases",
            "Boundaries",
            "Out of scope",
            "Evidence you must produce",
            "Verification commands",
            "What each guard does not prove",
        ]
        missing = [label for label in required_labels if label not in rendered]
        record("renderer_fields", not missing, f"renderer missing: {', '.join(missing)}" if missing else "all contract fields rendered")

    probes = _probe_alignment()
    for name, failure in probes:
        record(name, not failure, failure or "passed")

    fingerprints = None
    try:
        fingerprints = load_fingerprints(base)
    except ContractError as error:
        errors.append(str(error))
    else:
        if fingerprints is None:
            errors.append(f"fingerprints: {ALIGNMENT_FINGERPRINT_PATH} is missing")
    if fingerprints is not None:
        expected = [(entry["path"], entry["section"]) for entry in expected_fingerprint_entries()]
        recorded: dict[tuple[str, str | None], str] = {}
        for index, entry in enumerate(fingerprints["entries"]):
            if (
                not isinstance(entry, dict) or set(entry) != {"path", "section", "sha256"}
                or not isinstance(entry["path"], str)
                or (entry["section"] is not None and not isinstance(entry["section"], str))
                or not isinstance(entry["sha256"], str) or not HASH_RE.fullmatch(entry["sha256"])
            ):
                errors.append(f"fingerprints: malformed entry at index {index}")
                continue
            key = (entry["path"], entry["section"])
            if key not in expected or key in recorded:
                errors.append(f"fingerprints: unexpected or duplicate entry {key!r}")
                continue
            recorded[key] = entry["sha256"]
        missing_entries = [item for item in expected if item not in recorded]
        record(
            "fingerprint_entries",
            not missing_entries,
            f"missing reviewed entries: {missing_entries}" if missing_entries else "every required source has a fingerprint",
        )
        drift: list[str] = []
        for path, section in expected:
            label = f"{path}#{section}" if section else path
            try:
                digest = alignment_source_hash(base, path, section)
            except (ContractError, OSError, ValueError) as failure:
                drift.append(f"{label}: {failure}")
                continue
            if digest is None:
                drift.append(f"{label} is missing")
            elif recorded.get((path, section)) != digest:
                drift.append(f"{label} changed since review")
        record(
            "fingerprint_drift",
            not drift,
            "; ".join(drift) if drift else "sources match recorded fingerprints",
        )

    ok = not errors
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "limitations": [
            "structural checks and reviewed-source fingerprints only",
            "semantic alignment of rules, tests and behaviour is NOT VERIFIED",
            "fingerprints must be re-reviewed deliberately; this tool never updates them",
        ],
    }


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #


def _check_baseline(manifest: dict) -> list[str]:
    errors: list[str] = []
    repo = repo_toplevel(manifest["repo"])
    base = manifest["base"]
    actual_commit = resolve_commit(repo, "HEAD")
    if actual_commit != base["commit"]:
        errors.append(f"base.commit: target HEAD is {actual_commit}, manifest records {base['commit']}")
    current_files = content_map(repo)
    status = worktree_status(repo)
    if status != base["status"]:
        errors.append("base.status: working-tree state changed since the snapshot")
    current_index = index_digest(repo)
    if current_index != base["index_digest"]:
        errors.append("base.index_digest: index changed since the snapshot")
    if current_files != base["files"]:
        errors.append("base.files: target file contents changed since the snapshot")
    for path, digest in manifest["frozen"].items():
        if current_files.get(path, {}).get("sha256") != digest:
            errors.append(f"frozen: target {path} does not match its reviewed hash")
    return errors


def preflight(manifest: dict, root: str | Path | None = None) -> dict:
    errors, warnings = validate_manifest(manifest, require_baseline=True)
    if not errors:
        try:
            if not Path(manifest["repo"]).is_absolute():
                raise ContractError("repo must be an absolute path")
            repo = repo_toplevel(manifest["repo"])
            resolve_commit(repo, manifest["base"]["commit"])
            errors.extend(_check_baseline(manifest))
        except ContractError as error:
            errors.append(str(error))
    alignment = alignment_check(root)
    if not alignment["ok"]:
        errors.extend(f"alignment: {error}" for error in alignment["errors"])
    return {
        "command": "preflight",
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "alignment": alignment,
    }


def review_receipt_errors(
    receipt: Any,
    manifest: dict,
    candidate_manifest_digest: str,
    candidate_files_digest: str,
    candidate_files: dict,
    candidate_path: Path,
    target_path: Path,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    if not isinstance(receipt, dict):
        return ["review: receipt must be a JSON object"], notes
    _keys(receipt, REVIEW_KEYS, "review", errors)
    version = receipt.get("version")
    if not _is_int(version) or version != SCHEMA_VERSION:
        errors.append(f"review.version: must be {SCHEMA_VERSION}")
    if receipt.get("manifest_digest") != candidate_manifest_digest:
        errors.append("review.manifest_digest: does not match the manifest under review")
    if receipt.get("candidate_digest") != candidate_files_digest:
        errors.append("review.candidate_digest: does not match the candidate file content")
    if receipt.get("verdict") != "approved":
        errors.append("review.verdict: must be 'approved'")

    reviewer = receipt.get("reviewer")
    if not isinstance(reviewer, dict):
        errors.append("review.reviewer: must be an object")
        reviewer = {}
    else:
        _keys(reviewer, REVIEW_REVIEWER_KEYS, "review.reviewer", errors)
    model = reviewer.get("model")
    if not _nonempty(model):
        errors.append("review.reviewer.model: must name the reviewer model")
    else:
        lower_model = model.strip().lower()
        if "deepseek" in lower_model or not SOL_MODEL_RE.fullmatch(lower_model):
            errors.append(f"review.reviewer.model: acceptance review must run on Sol, not {model!r}")
        writer_model = manifest["writer"]["model"].strip().lower()
        # Model identity is independent of how a provider prefix is spelled.
        if lower_model.rsplit("/", 1)[-1] == writer_model.rsplit("/", 1)[-1]:
            errors.append("review.reviewer.model: the reviewer must not be the writer's model")

    review_tree_raw = reviewer.get("worktree")
    if not _nonempty(review_tree_raw) or not Path(review_tree_raw).is_absolute():
        errors.append("review.reviewer.worktree: must name an absolute review worktree path")
    else:
        try:
            review_tree = repo_toplevel(review_tree_raw)
            distinct = {real_path(candidate_path), real_path(target_path)}
            writer_tree = manifest.get("writer", {}).get("worktree")
            if writer_tree:
                distinct.add(real_path(writer_tree))
            if review_tree in distinct:
                errors.append("review.reviewer.worktree: must be distinct from the target, candidate and writer worktrees")
            if git_common_dir(review_tree) != git_common_dir(target_path):
                errors.append("review.reviewer.worktree: must belong to the same repository")
            else:
                review_files = content_map(review_tree)
                if review_files != candidate_files:
                    errors.append("review.reviewer.worktree: reviewed files do not match the candidate content")
        except (ContractError, OSError) as error:
            errors.append(f"review.reviewer.worktree: {error}")

    findings = receipt.get("findings")
    if not isinstance(findings, list):
        errors.append("review.findings: must be a list (empty when there are none)")
    else:
        ids: set[str] = set()
        for index, finding in enumerate(findings):
            field = f"findings[{index}]"
            if not isinstance(finding, dict):
                errors.append(f"{field}: must be an object")
                continue
            _keys(finding, FINDING_KEYS, field, errors)
            finding_id = finding.get("id")
            if not _nonempty(finding_id) or finding_id in ids:
                errors.append(f"{field}.id: must be a unique non-empty string")
            else:
                ids.add(finding_id)
            status = str(finding.get("status", "")).strip().lower()
            severity = str(finding.get("severity", "")).strip().lower()
            if not _nonempty(finding.get("description")):
                errors.append(f"{field}.description: must describe the finding")
            blocking = ("blocking", "high", "critical")
            closed = ("closed", "resolved", "fixed", "accepted")
            if severity not in (*blocking, "medium", "low", "info"):
                errors.append(f"{field}.severity: must name a recognized severity")
            if status not in (*closed, "open"):
                errors.append(f"{field}.status: must name a recognized status")
            elif status == "open":
                if severity in blocking:
                    errors.append(f"{field}: unresolved {severity} finding blocks integration")
                elif severity in ("medium", "low", "info"):
                    notes.append(f"{field}: open {severity} finding recorded")

    verification = receipt.get("verification")
    expected = [item.strip() for item in manifest.get("verification", [])]
    seen: dict[str, dict] = {}
    if not isinstance(verification, list):
        errors.append("review.verification: must be a list of command records")
    else:
        for index, record in enumerate(verification):
            field = f"verification[{index}]"
            if not isinstance(record, dict):
                errors.append(f"{field}: must be an object")
                continue
            _keys(record, VERIFICATION_KEYS, field, errors)
            command = record.get("command")
            if not _nonempty(command):
                errors.append(f"{field}.command: must name the command")
                continue
            command = command.strip()
            if command in seen:
                errors.append(f"{field}.command: duplicate command record {command!r}")
            seen[command] = record
            status = str(record.get("status", "")).lower()
            if status not in ("pass", "passed"):
                errors.append(f"{field}.status: {command!r} is {status or 'unreported'}, not verified")
            if not _nonempty(record.get("evidence")):
                errors.append(f"{field}.evidence: must state what was observed")
            skipped = record.get("skipped")
            if not isinstance(skipped, list) or not all(_nonempty(item) for item in skipped):
                errors.append(f"{field}.skipped: must be a list of non-empty strings (may be empty)")
            elif skipped:
                notes.append(f"{command}: {len(skipped)} skipped item(s) are NOT VERIFIED: {skipped}")
        for command in expected:
            if command not in seen:
                errors.append(f"review.verification: no record for required command {command!r}")

    guard_ids = [guard["id"] for guard in manifest.get("guards", [])]
    mutations = receipt.get("mutations")
    mutation_by_guard: dict[str, dict] = {}
    if not isinstance(mutations, list):
        errors.append("review.mutations: must be a list of guard mutation records")
    else:
        for index, record in enumerate(mutations):
            field = f"mutations[{index}]"
            if not isinstance(record, dict):
                errors.append(f"{field}: must be an object")
                continue
            _keys(record, MUTATION_KEYS, field, errors)
            guard = record.get("guard")
            if not isinstance(guard, str) or guard not in guard_ids:
                errors.append(f"{field}.guard: unknown guard {guard!r}")
                continue
            if guard in mutation_by_guard:
                errors.append(f"{field}.guard: duplicate mutation record for {guard}")
            mutation_by_guard[guard] = record
            result = str(record.get("result", "")).lower()
            if result not in ("fail", "failed", "failed-as-expected"):
                errors.append(f"{field}.result: guard {guard} did not fail under the mutation ({result or 'unreported'})")
            if not _nonempty(record.get("evidence")):
                errors.append(f"{field}.evidence: must state the observed failure")
        for guard in guard_ids:
            if guard not in mutation_by_guard:
                errors.append(f"review.mutations: no mutation evidence for guard {guard}")

    not_verified = receipt.get("not_verified")
    if not isinstance(not_verified, list):
        errors.append("review.not_verified: must be a list (empty when everything was verified)")
    else:
        for item in not_verified:
            if not _nonempty(item):
                errors.append("review.not_verified: entries must be non-empty strings")
            else:
                notes.append(f"NOT VERIFIED: {item}")

    notes.append("attested commands were not replayed by this gate; reviewer identity is not authenticated")
    return errors, notes


def integration(
    manifest: dict,
    candidate: str | Path,
    receipt: dict,
    root: str | Path | None = None,
) -> dict:
    errors, warnings = validate_manifest(manifest, require_baseline=True)
    notes: list[str] = []
    if errors:
        return {
            "command": "integration",
            "ok": False,
            "errors": errors,
            "warnings": warnings,
            "notes": notes,
        }

    alignment = alignment_check(root)
    if not alignment["ok"]:
        errors.extend(f"alignment: {error}" for error in alignment["errors"])

    target = repo_toplevel(manifest["repo"])
    candidate_path = real_path(candidate)
    try:
        if candidate_path == target:
            errors.append("candidate: must be a separate worktree, not the target checkout")
        candidate_root = repo_toplevel(candidate_path)
        if git_common_dir(candidate_root) != git_common_dir(target):
            errors.append("candidate: must belong to the same repository as the target")
        candidate_head = resolve_commit(candidate_root, "HEAD")
        if candidate_head != manifest["base"]["commit"]:
            errors.append(f"candidate: HEAD is {candidate_head}, expected base {manifest['base']['commit']}")
        errors.extend(_check_baseline(manifest))
    except (ContractError, OSError) as error:
        errors.append(f"candidate: {error}")
        return {
            "command": "integration",
            "ok": False,
            "errors": errors,
            "warnings": warnings,
            "notes": notes,
            "alignment": alignment,
        }

    baseline_files = manifest["base"]["files"]
    try:
        files = content_map(candidate_root)
        _require_unchanged_links(_link_digests(baseline_files), _link_digests(files), "candidate symlink drift from baseline")
    except ContractError as error:
        errors.append(f"candidate: {error}")
        return {
            "command": "integration",
            "ok": False,
            "errors": errors,
            "warnings": warnings,
            "notes": notes,
            "alignment": alignment,
        }

    for path in sorted(baseline_files):
        if path not in files or files[path].get("deleted"):
            errors.append(f"candidate: baseline prerequisite dropped: {path}")
    for path in sorted(manifest["frozen"]):
        if path not in files or files[path].get("deleted"):
            errors.append(f"frozen: {path} is missing from the candidate")
        elif files[path].get("sha256") != manifest["frozen"][path]:
            errors.append(f"frozen: {path} does not match its reviewed hash")
        elif files[path].get("mode") != baseline_files.get(path, {}).get("mode"):
            errors.append(f"frozen: {path} does not match its baseline mode")
    changed = sorted(
        path
        for path in set(baseline_files) | set(files)
        if baseline_files.get(path) != files.get(path)
    )
    for path in changed:
        if path in manifest["frozen"]:
            continue
        if not path_is_allowed(path, manifest["allowed_paths"]):
            errors.append(f"allowed_paths: change outside the allowlist: {path}")

    manifest_value = manifest_digest(manifest)
    files_value = candidate_digest(manifest_value, files)
    receipt_errors, receipt_notes = review_receipt_errors(
        receipt,
        manifest,
        manifest_value,
        files_value,
        files,
        candidate_root,
        target,
    )
    errors.extend(receipt_errors)
    notes.extend(receipt_notes)

    return {
        "command": "integration",
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "notes": notes,
        "alignment": alignment,
        "manifest_digest": manifest_value,
        "candidate_digest": files_value,
        "changed_paths": changed,
        "gate_limit": "a read-only check of hashes, paths and an attestation; it does not replay tests",
    }


def read_json(path: str | Path, label: str) -> dict:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"invalid JSON constant {value}")

    full = Path(path)
    try:
        data = json.loads(
            full.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object, parse_constant=reject_constant,
        )
    except OSError as error:
        raise ContractError(f"cannot read {label} {full}: {error}") from error
    except ValueError as error:
        raise ContractError(f"{label} {full} is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ContractError(f"{label} {full} must be a JSON object")
    return data
