"""Bounded coordinator-invoked Pi + Herdr factory loop.

This module does not approve anything. The coordinating developer previews a
plan, explicitly approves launch/handoff/switch, and every dispatch records a
fixed inbox attempt before a role turn is submitted. It reuses the existing
contract, candidate and inbox records as-is and never commits or pushes.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import factory_contract as contract

COORDINATOR = {"provider": "openai", "model": "gpt-6.1-sol", "reasoning": "high"}
WRITER = {"provider": "deepseek", "model": "deepseek-flash", "reasoning": "model-default"}
REVIEWER = {"provider": "openai", "model": "gpt-6.1-sol", "reasoning": "high"}
ROUTES = {"coordinator": COORDINATOR, "writer": WRITER, "reviewer": REVIEWER}
ROLE_ORDER = ("coordinator", "writer", "reviewer")
REPAIR_LIMIT = 2
POLICY = "attempt-budget-v1"
ATTEMPT_ENVELOPES = {
    "writer.initial": {"calls": 60, "minutes": 25},
    "writer.repair": {"calls": 30, "minutes": 15},
    "reviewer.initial": {"calls": 60, "minutes": 25},
    "reviewer.rereview": {"calls": 40, "minutes": 20},
}
ATTEMPT_KINDS = {"writer": {"initial": "writer.initial", "repair": "writer.repair"},
                 "reviewer": {"initial": "reviewer.initial", "rereview": "reviewer.rereview"}}
MODEL_RE = re.compile(r"(?:[a-z0-9][a-z0-9_.-]*/)?(?:gpt-[0-9]+(?:\.[0-9]+)*-sol|deepseek-flash)")
SLUG_RE = re.compile(r"[^a-z0-9]+")
ATTEMPT_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
JOB_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")
IDENTITY_OPTIONS = ("--provider", "--model", "-m", "--models", "--thinking")
MODEL_POLICY = {
    "writer": ("deepseek", "deepseek-flash"),
    "coordinator": ("openai", "gpt-6.1-sol"),
    "reviewer": ("openai", "gpt-6.1-sol"),
}
ROLE_PROMPT = {
    "writer": (
        "DCC factory role: implementation writer. Job {job}, attempt {attempt}, worktree {worktree}. "
        "Manifest {manifest}, manifest digest {manifest_digest}. Follow the assigned brief and approved paths only. "
        "Publish a fixed writer record when complete; do not commit, push or start review."
    ),
    "reviewer": (
        "DCC factory role: independent acceptance reviewer. Job {job}, attempt {attempt}, worktree {worktree}. "
        "Manifest {manifest}, candidate {candidate}, candidate digest {candidate_digest}. "
        "Review the exact candidate independently; publish the receipt and evidence. Do not repair the candidate."
    ),
    "repair": (
        "DCC factory role: implementation writer repair. Job {job}, attempt {attempt}, worktree {worktree}. "
        "The independent reviewer requested changes for candidate {candidate_digest}. "
        "Repair only inside the approved scope; publish a fixed writer record when complete."
    ),
}


class RunError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def route_text(route: dict) -> str:
    return f"{route['provider']}/{route['model']}"


def parse_route(text: str, *, role: str) -> dict:
    if not isinstance(text, str) or not MODEL_RE.fullmatch(text.strip()):
        raise RunError("invalid-route", f"{role} route must be an exact provider/model identity")
    provider, _, model = text.strip().partition("/")
    if not _:
        raise RunError("invalid-route", f"{role} route must include a provider prefix")
    return {"provider": provider, "model": model, "reasoning": "model-default" if role == "writer" else "high"}


def validate_routes(routes: dict) -> None:
    if set(routes) != set(ROLE_ORDER):
        raise RunError("invalid-route", "plans must bind coordinator, writer and reviewer routes")
    for role in ROLE_ORDER:
        route = routes[role]
        expected = ROUTES[role]
        if route.get("provider") != expected["provider"] or route.get("model") != expected["model"]:
            raise RunError("invalid-route", f"{role} must use {route_text(expected)}")
        if role != "writer" and route.get("reasoning") != expected["reasoning"]:
            raise RunError("invalid-route", f"{role} must use {expected['reasoning']} reasoning")
    if routes["reviewer"]["model"].rsplit("/", 1)[-1] == routes["writer"]["model"].rsplit("/", 1)[-1]:
        raise RunError("invalid-route", "reviewer and writer must be distinct models")


def private_dir(path: Path, code: str) -> Path:
    try:
        item = path.lstat()
    except OSError as exc:
        raise RunError(code, f"missing private directory {path}") from exc
    if not stat.S_ISDIR(item.st_mode) or item.st_uid != os.getuid() or item.st_mode & 0o077:
        raise RunError(code, f"{path} must be an owner-only directory")
    return path


def identity_override(arg: str) -> bool:
    """True when a Pi argument selects provider, model, model cycling or reasoning."""
    if arg in IDENTITY_OPTIONS:
        return True
    if any(arg.startswith(option + "=") for option in IDENTITY_OPTIONS):
        return True
    return arg.startswith("-m") and len(arg) > 2


def canonical(path: str, code: str) -> Path:
    if not isinstance(path, str) or not path or re.search(r"[\x00-\x1f\x7f]", path):
        raise RunError(code, "expected an absolute physical path")
    value = Path(path)
    if not value.is_absolute() or str(value) != path or ".." in value.parts or value == Path("/"):
        raise RunError(code, f"expected a canonical absolute path: {path}")
    return value


def approved_executable(path: Any, code: str) -> Path:
    """Return the exact approved executable path or fail; never look one up in PATH."""
    value = canonical(path, code)
    try:
        item = value.stat()
    except OSError as exc:
        raise RunError(code, f"{value} is not an executable file") from exc
    if not stat.S_ISREG(item.st_mode) or not os.access(value, os.X_OK):
        raise RunError(code, f"{value} is not an executable file")
    return value


def read_json(path: Path, code: str, limit: int = 2 * 1024 * 1024) -> dict:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RunError(code, f"cannot read {path}") from exc
    if not data or len(data) > limit:
        raise RunError(code, f"{path} is not a bounded record")
    try:
        row = json.loads(data)
    except (ValueError, RecursionError) as exc:
        raise RunError(code, f"{path} is not valid JSON") from exc
    if not isinstance(row, dict):
        raise RunError(code, f"{path} must contain a JSON object")
    return row


def write_private(path: Path, row: dict, *, replace: bool = True) -> None:
    data = (contract.canonical_json(row) + "\n").encode()
    directory = path.parent
    private_dir(directory, "unsafe-state")
    if not replace and path.exists():
        raise RunError("record-exists", f"{path} already exists")
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".pending-", delete=False) as handle:
        handle.write(data)
        handle.flush()
        os.fchmod(handle.fileno(), 0o400)
    try:
        if replace:
            os.replace(handle.name, path)
        else:
            os.link(handle.name, path)
    finally:
        try:
            os.unlink(handle.name)
        except FileNotFoundError:
            pass


def digest_file(path: Path) -> str:
    return contract.sha256_bytes(path.read_bytes())


def run(argv: list[str], *, cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)


def git(repo: Path, *args: str) -> str:
    result = run(["git", "-C", str(repo), *args])
    if result.returncode != 0:
        raise RunError("git-failed", f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def herdr(executable: Path, session: str, *args: str, timeout: int = 120) -> dict:
    result = run([str(executable), "--session", session, *args], timeout=timeout)
    if result.returncode != 0:
        raise RunError("herdr-failed", result.stderr.strip() or f"herdr {' '.join(args)} failed")
    text = result.stdout.strip()
    if not text:
        return {}
    try:
        row = json.loads(text)
    except ValueError as exc:
        raise RunError("herdr-failed", f"herdr returned non-JSON output: {text[:200]}") from exc
    return row if isinstance(row, dict) else {}


def wait_for_pi(executable: Path, session: str, pane: str, *, timeout: float = 30.0) -> None:
    """Wait for Herdr's own Pi detection and settled readiness in the launched pane."""
    deadline = time.monotonic() + timeout
    last = "no agent detected"
    while time.monotonic() < deadline:
        result = run([str(executable), "--session", session, "agent", "get", pane], timeout=10)
        if result.returncode == 0:
            try:
                row = json.loads(result.stdout)
            except ValueError:
                row = {}
            detected = find_id(row, "agent")
            status = find_id(row, "agent_status")
            if detected and detected != "pi":
                raise RunError("herdr-failed", f"Herdr detected {detected} instead of Pi in pane {pane}")
            if detected == "pi" and status in ("idle", "done"):
                return
            last = f"detected={detected} status={status}"
        else:
            last = result.stderr.strip()[:200] or "agent not detected"
        time.sleep(0.1)
    raise RunError("herdr-failed", f"Herdr did not recognise the approved Pi in pane {pane}: {last}")


def find_id(row: Any, key: str) -> str | None:
    if isinstance(row, dict):
        for name, value in row.items():
            if name == key and isinstance(value, str):
                return value
        for value in row.values():
            found = find_id(value, key)
            if found:
                return found
    elif isinstance(row, list):
        for value in row:
            found = find_id(value, key)
            if found:
                return found
    return None


def session_name(job: str, plan_digest: str) -> str:
    slug = SLUG_RE.sub("-", job.lower()).strip("-")[:18] or "job"
    return f"dcc-{slug}-{plan_digest[:8]}"


def outside_repos(path: Path, manifest: dict) -> None:
    roots = [Path(manifest["repo"]).resolve(), contract.PACKAGE_ROOT]
    for root in roots:
        if path == root or path.is_relative_to(root):
            raise RunError("unsafe-state", f"state and worktrees must stay outside {root}")


def load_manifest(path: str) -> dict:
    manifest = read_json(canonical(path, "invalid-manifest"), "invalid-manifest")
    errors, _warnings = contract.validate_manifest(manifest, require_baseline=True)
    if errors:
        raise RunError("invalid-manifest", "; ".join(errors[:4]))
    return manifest


def listener_binding(registration: str, manifest: dict, *, manual_fixture: bool = False) -> dict:
    path = canonical(registration, "invalid-listener")
    if path.name != "registration.json":
        raise RunError("invalid-listener", "expected registration.json")
    row = read_json(path, "invalid-listener", 4096)
    if row.get("version") != 1 or row.get("manifest_digest") != contract.manifest_digest(manifest):
        raise RunError("unverified-listener", "registration is not bound to this manifest")
    if type(row.get("expires_ms")) is not int or row["expires_ms"] <= time.time_ns() // 1_000_000:
        raise RunError("unverified-listener", "registration has expired")
    if not isinstance(row.get("job"), str) or not JOB_RE.fullmatch(row["job"]) or not isinstance(row.get("session"), str):
        raise RunError("unverified-listener", "registration identity is malformed")
    session_file_raw = row.get("session_file")
    if not isinstance(session_file_raw, str):
        raise RunError("unverified-listener", "registration session file is malformed")
    session_file = canonical(session_file_raw, "unverified-listener")
    try:
        item = session_file.lstat()
    except OSError as exc:
        raise RunError("unverified-listener", "registered Pi transcript is missing") from exc
    if not stat.S_ISREG(item.st_mode) or item.st_uid != os.getuid() or item.st_mode & 0o077:
        raise RunError("unverified-listener", "registered Pi transcript must be a private regular file")
    try:
        lines = session_file.read_bytes().splitlines()
        header = json.loads(lines[0])
    except (ValueError, OSError) as exc:
        raise RunError("unverified-listener", "registered Pi transcript header is invalid") from exc
    if header.get("type") != "session" or header.get("id") != row.get("session"):
        raise RunError("unverified-listener", "registered Pi transcript does not match its session id")
    inbox = path.parent
    duplicates = []
    for other in sorted(inbox.parent.glob("*/registration.json")) if inbox.parent.parent != inbox.parent else []:
        if other == path:
            continue
        try:
            candidate = read_json(other, "invalid-listener", 4096)
        except RunError:
            continue
        if candidate.get("session") == row.get("session"):
            duplicates.append(str(other))
    if duplicates:
        raise RunError("duplicate-listener", f"session is registered by more than one inbox: {duplicates[:2]}")
    registration_hash = digest_file(path)
    mode = "manual-approved-fixture" if manual_fixture else "enabled-listener"
    if manual_fixture:
        return {"registration": str(path), "registration_sha256": registration_hash, "job": row["job"],
                "session": row["session"], "session_file": str(session_file),
                "expires_ms": row["expires_ms"], "mode": mode}
    rows = []
    for line in lines[1:]:
        try:
            entry = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(entry, dict):
            rows.append(entry)
    by_id = {entry.get("id"): entry for entry in rows if isinstance(entry.get("id"), str)}
    chain = []
    current = rows[-1] if rows else None
    seen = set()
    while isinstance(current, dict) and current.get("id") not in seen:
        chain.append(current)
        seen.add(current.get("id"))
        current = by_id.get(current.get("parentId") or current.get("parent_id"))
    ordered = list(reversed(chain)) if chain else rows
    latest = None
    for entry in ordered:
        kind = entry.get("customType") or entry.get("custom_type")
        if kind == "dcc-handoff-state-v1":
            latest = entry.get("data")
    enabled = False
    if isinstance(latest, dict):
        enabled = (latest.get("enabled") is True and latest.get("session") == row.get("session")
                   and latest.get("file") == str(session_file) and latest.get("registration") == str(path)
                   and latest.get("hash") == registration_hash)
    if not enabled:
        raise RunError("unverified-listener",
                       "no enabled /dcc-handoff state for this exact registration; use an approved manual fixture exception")
    return {"registration": str(path), "registration_sha256": registration_hash, "job": row["job"],
            "session": row["session"], "session_file": str(session_file),
            "expires_ms": row["expires_ms"], "mode": mode}


def baseline_is_unchanged(manifest: dict) -> list[str]:
    repo = contract.repo_toplevel(manifest["repo"])
    base = manifest["base"]
    errors = []
    if contract.resolve_commit(repo, "HEAD") != base["commit"]:
        errors.append("target HEAD moved")
    if contract.worktree_status(repo) != base["status"]:
        errors.append("target worktree status changed")
    if contract.index_digest(repo) != base["index_digest"]:
        errors.append("target index changed")
    if contract.content_map(repo) != base["files"]:
        errors.append("target file contents changed")
    return errors


def _cap(value: str, code: str) -> dict:
    calls, _, minutes = value.partition(":")
    if not calls.isdigit() or not minutes.isdigit():
        raise RunError("invalid-budget", f"{code} must be CALLS:MINUTES")
    return {"calls": int(calls), "minutes": int(minutes)}


def preview(
    manifest_path: str,
    *,
    registration: str,
    writer_worktree: str,
    reviewer_worktree: str,
    plan_out: str,
    herdr_executable: str,
    pi_executable: str,
    session_dir: str,
    agent_dir: str,
    brief: str,
    extension: str | None = None,
    pi_arg: Iterable[str] = (),
    alternate_writer: Iterable[str] = (),
    writer_attempt_limit: str = "",
    reviewer_attempt_limit: str = "",
    repair_writer_limit: str = "",
    rereview_limit: str = "",
    overall_limit: str = "",
    used_shared: str = "",
    used_writer: str = "",
    used_reviewer: str = "",
    used_coordinator: str = "",
    manual_fixture: bool = False,
) -> dict:
    manifest = load_manifest(manifest_path)
    validate_routes(ROUTES)
    preflight = contract.preflight(manifest)
    if not preflight["ok"]:
        raise RunError("preflight-failed", "; ".join(preflight["errors"][:6]))
    brief_path = canonical(brief, "invalid-brief")
    if brief_path.read_bytes() != contract.render_brief(manifest).encode():
        raise RunError("invalid-brief", "brief is not the exact rendered brief for this manifest")
    binding = listener_binding(registration, manifest, manual_fixture=manual_fixture)
    writer = canonical(writer_worktree, "invalid-worktree")
    reviewer = canonical(reviewer_worktree, "invalid-worktree")
    if writer == reviewer:
        raise RunError("invalid-worktree", "writer and reviewer worktrees must be distinct")
    if writer.exists() or reviewer.exists():
        raise RunError("worktree-exists", "planned worktree paths must not exist before launch")
    for path in (writer, reviewer):
        outside_repos(path, manifest)
    private_dir(canonical(plan_out, "unsafe-state").parent, "unsafe-state")
    for tool in (approved_executable(herdr_executable, "missing-tool"),
                 approved_executable(pi_executable, "missing-tool")):
        if not tool.is_file() or not os.access(tool, os.X_OK):
            raise RunError("missing-tool", f"{tool} is not an executable file")
    private_dir(canonical(session_dir, "unsafe-state"), "unsafe-state")
    private_dir(canonical(agent_dir, "unsafe-state"), "unsafe-state")
    extension_path = None
    if extension is not None:
        extension_path = canonical(extension, "missing-tool")
        if not extension_path.is_file():
            raise RunError("missing-tool", f"{extension_path} is not a file")
    pi_args = list(pi_arg)
    if any(identity_override(arg) for arg in pi_args):
        raise RunError("invalid-route", "pi arguments cannot override the approved role provider, model or reasoning identity")
    alternates = []
    for model in alternate_writer:
        route = parse_route(model, role="writer")
        if route["model"].rsplit("/", 1)[-1] == ROUTES["reviewer"]["model"].rsplit("/", 1)[-1]:
            raise RunError("invalid-route", "an alternate writer must remain distinct from the reviewer")
        alternates.append(route_text(route))
    supplied = {"writer.initial": writer_attempt_limit, "writer.repair": repair_writer_limit,
                "reviewer.initial": reviewer_attempt_limit, "reviewer.rereview": rereview_limit}
    attempt_limits = {}
    for key, envelope in ATTEMPT_ENVELOPES.items():
        value = supplied[key] or f"{envelope['calls']}:{envelope['minutes']}"
        cap = _cap(value, key)
        if cap["calls"] > envelope["calls"] or cap["minutes"] > envelope["minutes"] or cap["calls"] <= 0 or cap["minutes"] <= 0:
            raise RunError("invalid-budget", f"{key} must be a positive bounded allowance within its approved envelope")
        attempt_limits[key] = cap
    overall = _cap(overall_limit, "overall") if overall_limit else None
    initial = {"writer": {"minutes": 0, "calls": 0}, "reviewer": {"minutes": 0, "calls": 0},
               "coordinator": {"minutes": 0, "calls": 0}, "shared": {"minutes": 0, "calls": 0}}
    for name, value in (("writer", used_writer), ("reviewer", used_reviewer), ("coordinator", used_coordinator)):
        if value:
            initial[name] = _cap(value, f"used {name}")
    attributed = {"calls": sum(initial[name]["calls"] for name in ("writer", "reviewer", "coordinator")),
                  "minutes": sum(initial[name]["minutes"] for name in ("writer", "reviewer", "coordinator"))}
    if used_shared:
        shared = _cap(used_shared, "used shared")
        if shared["calls"] < attributed["calls"] or shared["minutes"] < attributed["minutes"]:
            raise RunError("invalid-budget", "explicit shared use is smaller than the attributed role/coordinator use")
        initial["shared"] = shared
    else:
        initial["shared"] = attributed
    manifest_value = contract.manifest_digest(manifest)
    plan: dict[str, Any] = {
        "version": 1, "policy": POLICY,
        "task": manifest["task"]["id"], "goal": manifest["task"]["goal"],
        "manifest": str(canonical(manifest_path, "invalid-manifest")), "manifest_digest": manifest_value,
        "brief": str(brief_path), "brief_sha256": digest_file(brief_path),
        "repo": manifest["repo"], "base": manifest["base"], "listener": binding,
        "routes": ROUTES, "writer_alternates": sorted(set(alternates)),
        "worktrees": {"writer": str(writer), "reviewer": str(reviewer)},
        "budgets": manifest["budgets"], "attempt_limits": attempt_limits, "overall_limit": overall,
        "initial_usage": initial, "manual_fixture": manual_fixture,
        "tools": {"herdr": str(canonical(herdr_executable, "missing-tool")),
                  "pi": str(canonical(pi_executable, "missing-tool")),
                  "extension": str(extension_path) if extension_path else None,
                  "session_dir": str(canonical(session_dir, "unsafe-state")),
                  "agent_dir": str(canonical(agent_dir, "unsafe-state")), "pi_args": pi_args},
        "created_at": now(),
    }
    plan["herdr_session"] = session_name(plan["task"], contract.sha256_bytes((contract.canonical_json(plan)).encode()))
    plan["plan_digest"] = contract.sha256_bytes((contract.canonical_json(plan)).encode())
    write_private(canonical(plan_out, "unsafe-state"), plan, replace=False)
    return plan


def load_state(path: str) -> tuple[Path, dict]:
    state_path = canonical(path, "invalid-state")
    state = read_json(state_path, "invalid-state")
    if state.get("version") != 1 or state.get("plan_digest") is None:
        raise RunError("invalid-state", "expected a version 1 loop state")
    if state.get("policy") != POLICY:
        raise RunError("stale-state", "old-format budget state; re-preview this job with explicit consent")
    return state_path, state


def save_state(path: Path, state: dict) -> None:
    write_private(path, state)


def event(state: dict, name: str, **fields: Any) -> None:
    state.setdefault("events", []).append({"name": name, "at": now(), **fields})


def _bump(bucket: dict, calls: int, minutes: int) -> None:
    bucket["calls"] += calls
    bucket["minutes"] += minutes


def spend(state: dict, raw: str) -> None:
    if not raw:
        return
    usage = state.setdefault("usage", {})
    for name in ("writer", "reviewer", "coordinator", "shared"):
        usage.setdefault(name, {"minutes": 0, "calls": 0})
    attempts = state.setdefault("attempt_usage", {})
    for item in raw.split(","):
        selector, _, numbers = item.partition(":")
        calls_raw, _, minutes_raw = numbers.partition(":")
        if not calls_raw.isdigit() or not minutes_raw.isdigit():
            raise RunError("invalid-budget", "expected selector:calls:minutes entries")
        calls, minutes = int(calls_raw), int(minutes_raw)
        if selector in ("writer", "reviewer", "coordinator", "shared"):
            if selector == "shared":
                _bump(usage["shared"], calls, minutes)
                continue
            role = selector
            if role in ("writer", "reviewer"):
                ids = attempt_ids(state, role)
                if not ids:
                    raise RunError("invalid-budget", f"no registered {role} attempt to charge")
                key = f"{role}.{ids[-1]}"
                _bump(attempts.setdefault(key, {"minutes": 0, "calls": 0}), calls, minutes)
            _bump(usage[role], calls, minutes)
            _bump(usage["shared"], calls, minutes)
            continue
        role, _, attempt = selector.partition(".")
        key = f"{role}.{attempt}"
        if role not in ("writer", "reviewer") or key not in state.get("attempt_allocations", {}):
            raise RunError("invalid-budget", f"unknown attempt selector {selector}")
        _bump(attempts.setdefault(key, {"minutes": 0, "calls": 0}), calls, minutes)
        _bump(usage[role], calls, minutes)
        _bump(usage["shared"], calls, minutes)


def attempt_remaining(state: dict, key: str) -> tuple[int, int]:
    limit = state.get("attempt_allocations", {}).get(key)
    if limit is None:
        raise RunError("invalid-budget", f"attempt {key} has no recorded allowance")
    used = state.get("attempt_usage", {}).get(key, {"minutes": 0, "calls": 0})
    return limit["minutes"] - used["minutes"], limit["calls"] - used["calls"]


def overall_remaining(state: dict) -> tuple[int, int] | None:
    limit = state.get("overall_limit")
    if limit is None:
        return None
    used = state.get("usage", {}).get("shared", {"minutes": 0, "calls": 0})
    return limit["minutes"] - used["minutes"], limit["calls"] - used["calls"]


def require_dispatch_allowance(state: dict, role: str, attempt: str) -> None:
    key = f"{role}.{attempt}"
    minutes, calls = attempt_remaining(state, key)
    if minutes <= 0 or calls <= 0:
        state["blocked"] = {"reason": "budget-exhausted", "scope": "attempt", "attempt": key,
                            "remaining": {"minutes": max(minutes, 0), "calls": max(calls, 0)}, "at": now()}
        event(state, "stopped", reason="budget-exhausted", scope="attempt", attempt=key)
        raise RunError("budget-exhausted", f"{key} allowance is exhausted; no role was launched")
    remaining_overall = overall_remaining(state)
    if remaining_overall is not None and (remaining_overall[0] <= 0 or remaining_overall[1] <= 0):
        state["blocked"] = {"reason": "budget-exhausted", "scope": "overall",
                            "remaining": {"minutes": max(remaining_overall[0], 0),
                                          "calls": max(remaining_overall[1], 0)}, "at": now()}
        event(state, "stopped", reason="budget-exhausted", scope="overall")
        raise RunError("budget-exhausted", "the selected overall ceiling is exhausted; no role was launched")


def attempt_ids(state: dict, role: str) -> list[str]:
    return [row["attempt"] for row in state.get("attempts", []) if row["role"] == role]


def next_attempt(state: dict, role: str) -> str:
    used = attempt_ids(state, role)
    number = 1
    while f"a{number}" in used:
        number += 1
    return f"a{number}"


def allocate_attempt(state: dict, role: str, attempt: str, kind: str) -> str:
    key = ATTEMPT_KINDS[role].get(kind)
    if key is None:
        raise RunError("invalid-attempt", f"unknown attempt kind {kind}")
    slot = f"{role}.{attempt}"
    allocations = state.setdefault("attempt_allocations", {})
    if slot in allocations:
        return slot
    if role == "writer" and kind == "initial" and attempt_ids(state, role):
        raise RunError("attempt-reused", "initial writer allowance cannot be reissued to another attempt")
    allocations[slot] = dict(state["attempt_limits"][key])
    state.setdefault("attempt_usage", {}).setdefault(slot, {"minutes": 0, "calls": 0})
    state.setdefault("attempt_kinds", {})[slot] = kind
    event(state, "attempt-allocated", role=role, attempt=attempt, kind=kind, limit=allocations[slot])
    return slot


def register_attempt(state: dict, role: str, attempt: str, kind: str = "initial") -> None:
    import factory_inbox as inbox
    slot = allocate_attempt(state, role, attempt, kind)
    if any(row["role"] == role and row["attempt"] == attempt for row in state.get("attempts", [])):
        raise RunError("attempt-reused", f"{slot} is already registered")
    try:
        inbox.register_attempt(state["listener"]["registration"], role, attempt,
                               state.get("candidate_file") if role == "reviewer" else None)
    except (inbox.Refusal, OSError) as exc:
        raise RunError("attempt-refused", str(exc)) from exc
    state.setdefault("attempts", []).append({"role": role, "attempt": attempt, "registered_at": now()})
    event(state, "attempt-registered", role=role, attempt=attempt)


def assignment_prompt(state: dict, role: str, attempt: str, *, findings: str = "", repair: bool = False) -> str:
    inbox = Path(state["listener"]["registration"]).parent
    stage = "writer" if role == "writer" else "reviewer"
    report = inbox / f"{stage}.{attempt}.report.md"
    evidence = inbox / f"{stage}.{attempt}.evidence.md"
    kit = contract.PACKAGE_ROOT
    lines = [
        f"DCC factory role: {'implementation writer repair' if repair else ('implementation writer' if role == 'writer' else 'independent acceptance reviewer')}.",
        f"Job {state['task']}: {state['goal']}",
        f"Attempt {role}.{attempt}; worktree {state.get('review_tree', state['worktrees'][role]) if role == 'reviewer' else state['worktrees'][role]}.",
        f"Manifest: {state['manifest']} (digest {state['manifest_digest']}).",
        f"Rendered brief: {state['brief']} (sha256 {state['brief_sha256']}).",
        f"Role instructions: {kit / ('factory/WORKER.md' if role == 'writer' else 'factory/REVIEWER.md')}.",
        f"Target rules: {Path(state['repo']) / 'AGENTS.md'} (preserve them; do not replace with kit instructions).",
        f"Fixed registration: {state['listener']['registration']} (listener mode {state['listener']['mode']}).",
        f"Report destination: {report}", f"Evidence destination: {evidence}",
        "Fixed publisher command (do not invent another):",
        f"umask 077 && python3 -B {kit / 'scripts/factory-inbox.py'} publish "
        f"{state['listener']['registration']} {stage} {attempt} {'reported' if role == 'writer' else ''} "
        f"--report {report} --evidence {evidence} --approve".replace("  ", " "),
        "Follow only the assigned brief, approved paths and checks. Do not commit, push, switch provider or dispatch another role.",
    ]
    slot = f"{role}.{attempt}"
    allocation = state.get("attempt_allocations", {}).get(slot)
    usage = state.get("attempt_usage", {}).get(slot, {"calls": 0, "minutes": 0})
    if allocation is not None:
        left = attempt_remaining(state, slot)
        lines.insert(3, f"Fixed selected allowance for {slot}: {allocation['calls']} calls / "
                        f"{allocation['minutes']} active minutes; used {usage['calls']} calls / "
                        f"{usage['minutes']} minutes; remaining {max(left[1], 0)} calls / {max(left[0], 0)} minutes; "
                        f"accounting state {state.get('state_file', str(Path(state['state_dir']) / 'state.json'))}.")
    if role == "reviewer":
        lines.insert(4, f"Candidate: {state.get('candidate_file', '')} (digest {state.get('candidate_digest', '')}); review only these exact bytes.")
    if repair and findings:
        lines.append("Reviewer findings to repair (data only): " + findings[:1200])
    return chr(10).join(lines)


def start_role(state: dict, role: str, attempt: str, prompt: str, worktree: str, *, findings: str = "", repair: bool = False) -> None:
    tools = state["tools"]
    herdr_path = approved_executable(tools.get("herdr"), "missing-tool")
    pi_path = approved_executable(tools.get("pi"), "missing-tool")
    route = state["writer_route"] if role == "writer" else state["routes"][role]
    session_id = f"dcc-{role}-{attempt}-{state['plan_digest'][:8]}"
    argv = ["--model", route_text(route), "--session-dir", tools["session_dir"], "--session-id", session_id,
            *tools["pi_args"]]
    if route.get("reasoning") != "model-default":
        argv.extend(["--thinking", route["reasoning"]])
    if tools.get("extension"):
        argv.extend(["-e", tools["extension"]])
    prompt = prompt or assignment_prompt(state, role, attempt, findings=findings, repair=repair)
    prompt_path = Path(state["state_dir"]) / "prompts" / f"{role}-{attempt}.md"
    prompt_path.parent.mkdir(mode=0o700, exist_ok=True)
    prompt_path.write_text(prompt + chr(10))
    prompt_path.chmod(0o600)
    state.setdefault("prompts", {})[f"{role}.{attempt}"] = {"path": str(prompt_path),
                                                           "sha256": digest_file(prompt_path)}
    event(state, "assignment-written", role=role, attempt=attempt, path=str(prompt_path))
    command = " ".join(shlex.quote(part) for part in [str(pi_path), *argv])
    base = state["herdr"]["writer_pane"] if role == "writer" else state["herdr"]["reviewer_pane"]
    split = herdr(herdr_path, state["herdr_session"], "pane", "split", "--pane", base,
                  "--direction", "down", "--cwd", worktree,
                  "--env", f"PI_CODING_AGENT_DIR={tools['agent_dir']}", "--no-focus")
    pane = find_id(split, "pane_id")
    if not pane or pane == base:
        raise RunError("herdr-failed", "could not create a dedicated role pane")
    state.setdefault("panes", []).append({"role": role, "attempt": attempt, "pane": pane})
    herdr(herdr_path, state["herdr_session"], "pane", "run", pane, command, timeout=120)
    wait_for_pi(herdr_path, state["herdr_session"], pane)
    renamed = herdr(herdr_path, state["herdr_session"], "agent", "rename", pane, f"{role}-{attempt}", timeout=30)
    state.setdefault("sessions", {})[session_id] = {
        "role": role, "attempt": attempt, "worktree": worktree, "model": route_text(route),
        "thinking": route.get("reasoning"), "argv": argv, "executable": str(pi_path),
        "launch": {"mechanism": "pane-run", "command": command}}
    event(state, "agent-started", role=role, attempt=attempt, session=session_id,
          detail=find_id(renamed, "pane_id"), executable=str(pi_path), mechanism="pane-run")
    submitted = herdr(herdr_path, state["herdr_session"], "agent", "prompt", pane, prompt, timeout=60)
    settled: str | None = None
    try:
        waited = herdr(herdr_path, state["herdr_session"], "agent", "wait", pane,
                       "--timeout", "15000", timeout=30)
        settled = find_id(waited, "status")
    except RunError:
        settled = None
    event(state, "prompt-submitted", role=role, attempt=attempt, session=session_id,
          accepted=bool(submitted), settled=settled)
    state["phase"] = "dispatched"
    state["last_dispatch"] = {"role": role, "attempt": attempt, "at": now()}


def safe_dispatch(state: dict, role: str, attempt: str, prompt: str, worktree: str,
                  *, findings: str = "", repair: bool = False) -> None:
    try:
        start_role(state, role, attempt, prompt, worktree, findings=findings, repair=repair)
    except RunError as exc:
        state["blocked"] = {"reason": "dispatch-failed", "role": role, "detail": exc.detail, "at": now()}
        event(state, "dispatch-failed", role=role, attempt=attempt)
        raise


def worker_worktree(manifest: dict, state: dict) -> Path:
    path = Path(state["worktrees"]["writer"]).resolve()
    head = contract.resolve_commit(path, "HEAD")
    if head != manifest["base"]["commit"]:
        raise RunError("worktree-drift", "writer worktree HEAD moved from the approved base")
    return path


def provision_review_copy(manifest: dict, state: dict) -> Path:
    writer = worker_worktree(manifest, state)
    cycle = len(attempt_ids(state, "reviewer")) + 1
    reviewer = Path(f"{state['worktrees']['reviewer']}-r{cycle}").resolve()
    if reviewer.exists():
        raise RunError("worktree-exists", "review worktree already exists")
    git(Path(manifest["repo"]), "worktree", "add", "--detach", str(reviewer), manifest["base"]["commit"])
    files = contract.content_map(writer)
    for relative, entry in files.items():
        if entry.get("deleted"):
            continue
        source = writer / relative
        destination = reviewer / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if entry["mode"] == contract.LINK_MODE:
            continue
        shutil.copyfile(source, destination)
        destination.chmod(0o755 if entry["mode"] == "100755" else 0o644)
    mismatched = contract.content_map(reviewer) != files
    if mismatched:
        raise RunError("candidate-mismatch", "review copy does not contain the exact writer bytes")
    return reviewer


def read_record(state: dict, role: str, attempt: str) -> dict | None:
    import factory_inbox as inbox
    try:
        return inbox.inspect(state["listener"]["registration"], role, attempt)
    except (inbox.Refusal, OSError) as exc:
        raise RunError("record-refused", str(exc)) from exc


def published(state: dict, role: str, attempt: str) -> dict | None:
    record = read_record(state, role, attempt)
    if not record or record.get("status") != "published":
        return None
    return record["record"]


def receipt_path(state: dict, stage: str, attempt: str) -> Path:
    root = Path(state["listener"]["registration"]).parent
    return root / f"{stage}.{attempt}" / "records" / "report"


def candidate_identity(manifest: dict, worktree: Path) -> dict:
    files = contract.content_map(worktree)
    manifest_value = contract.manifest_digest(manifest)
    return {"manifest_digest": manifest_value, "candidate_digest": contract.candidate_digest(manifest_value, files),
            "candidate": str(worktree), "files": files}


def write_candidate(state: dict, manifest: dict, worktree: Path) -> Path:
    row = candidate_identity(manifest, worktree)
    directory = Path(state["listener"]["registration"]).parent
    path = directory / "candidate.json"
    write_private(path, row, replace=True)
    state["candidate_file"] = str(path)
    state["candidate_digest"] = row["candidate_digest"]
    return path


def materialize_baseline(manifest: dict, worktree: Path) -> None:
    source_root = contract.repo_toplevel(manifest["repo"])
    files = manifest["base"]["files"]
    for relative, entry in files.items():
        if entry.get("deleted"):
            continue
        source = source_root / relative
        destination = worktree / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if entry.get("mode") == contract.LINK_MODE:
            continue
        destination.write_bytes(source.read_bytes())
        destination.chmod(0o755 if entry["mode"] == "100755" else 0o644)
    if contract.content_map(worktree) != files:
        raise RunError("baseline-transfer", "writer worktree does not match the approved staged baseline")


def dispatch_reviewer(state: dict, manifest: dict) -> None:
    writer_attempt = attempt_ids(state, "writer")[-1]
    worktree = provision_review_copy(manifest, state)
    state["review_tree"] = str(worktree)
    write_candidate(state, manifest, worktree)
    if state["herdr"].get("reviewer_pane") is None:
        created = herdr(Path(state["tools"]["herdr"]), state["herdr_session"], "workspace", "create",
                        "--cwd", str(worktree), "--label", f"dcc {state['task']} reviewer", "--no-focus")
        workspace = find_id(created, "workspace_id")
        pane = find_id(created, "pane_id")
        if not workspace or not pane:
            raise RunError("herdr-failed", "reviewer workspace create returned no ids")
        state["herdr"]["reviewer_workspace_id"] = workspace
        state["herdr"]["reviewer_pane"] = pane
    state["review_cycle"] = writer_attempt
    attempt = next_attempt(state, "reviewer")
    kind = "rereview" if attempt_ids(state, "reviewer") else "initial"
    allocate_attempt(state, "reviewer", attempt, kind)
    require_dispatch_allowance(state, "reviewer", attempt)
    register_attempt(state, "reviewer", attempt, kind)
    safe_dispatch(state, "reviewer", attempt, "", str(worktree))
    state["phase"] = "review-dispatched"
    event(state, "review-dispatched", writer_attempt=writer_attempt, attempt=attempt)


def dispatch_repair(state: dict, manifest: dict) -> None:
    repairs = state.get("repairs", 0)
    if repairs >= REPAIR_LIMIT:
        state["blocked"] = {"reason": "repair-limit", "role": "writer", "at": now()}
        raise RunError("repair-limit", "two approved repair rounds are already recorded")
    attempt = next_attempt(state, "writer")
    allocate_attempt(state, "writer", attempt, "repair")
    require_dispatch_allowance(state, "writer", attempt)
    register_attempt(state, "writer", attempt, "repair")
    findings = ""
    reviewer_attempts = attempt_ids(state, "reviewer")
    if reviewer_attempts:
        try:
            receipt = read_json(receipt_path(state, "reviewer", reviewer_attempts[-1]), "invalid-receipt")
            findings = "; ".join(f"{row.get('id')}: {row.get('description')}"
                                 for row in receipt.get("findings", []) if isinstance(row, dict))
        except (RunError, ValueError):
            findings = "reviewer report unavailable"
    safe_dispatch(state, "writer", attempt, "", state["worktrees"]["writer"], findings=findings, repair=True)
    state["repairs"] = repairs + 1
    state["phase"] = "repair-dispatched"
    event(state, "repair-dispatched", attempt=attempt)


def advance(state_path: str, *, spend_raw: str = "", manual: bool = False) -> dict:
    path, state = load_state(state_path)
    if manual and not state.get("manual_fixture"):
        raise RunError("manual-not-approved", "manual handling requires the explicit approved fixture exception")
    if state.get("manual_fixture") and not manual:
        raise RunError("manual-required", "this approved fixture exception requires explicit --manual handling")
    if manual:
        event(state, "manual-handling", reader="same fixed receipts")
    if state.get("blocked"):
        raise RunError("blocked-state", f"job is stopped ({state['blocked'].get('reason')}); no role launched")
    if state.get("phase") == "handed-off":
        raise RunError("complete-state", "handoff is already staged; no role launched")
    spend(state, spend_raw)
    manifest = load_manifest(state["manifest"])
    if contract.manifest_digest(manifest) != state["manifest_digest"]:
        state["blocked"] = {"reason": "manifest-drift", "at": now()}
        save_state(path, state)
        raise RunError("manifest-drift", "manifest bytes changed since launch")
    drift = baseline_is_unchanged(manifest)
    if drift:
        state["blocked"] = {"reason": "baseline-drift", "detail": "; ".join(drift), "at": now()}
        event(state, "stopped", reason="baseline-drift")
        save_state(path, state)
        raise RunError("baseline-drift", "; ".join(drift))

    state["state_dir"] = str(path.parent)
    writer_attempts = attempt_ids(state, "writer")
    writer_record = published(state, "writer", writer_attempts[-1]) if writer_attempts else None
    if writer_record is None:
        save_state(path, state)
        raise RunError("no-completion", "no published writer record; idle or absent state is not completion")
    if writer_record["outcome"] == "blocked":
        state["blocked"] = {"reason": "writer-blocked", "attempt": writer_attempts[-1], "at": now()}
        event(state, "stopped", reason="writer-blocked")
        save_state(path, state)
        return {"status": "stopped", "reason": "writer-blocked", "launched": False}

    reviewer_attempts = attempt_ids(state, "reviewer")
    reviewer_record = published(state, "reviewer", reviewer_attempts[-1]) if reviewer_attempts else None
    if reviewer_attempts and reviewer_record is None:
        save_state(path, state)
        raise RunError("no-completion", "reviewer attempt has no published receipt; no role launched")
    if reviewer_record is None:
        try:
            dispatch_reviewer(state, manifest)
        except RunError:
            save_state(path, state)
            raise
        save_state(path, state)
        return {"status": "review-dispatched", "launched": "reviewer",
                "attempt": attempt_ids(state, "reviewer")[-1]}
    if reviewer_record["outcome"] == "changes_requested":
        if state.get("review_cycle") != writer_attempts[-1]:
            try:
                dispatch_reviewer(state, manifest)
            except RunError:
                save_state(path, state)
                raise
            save_state(path, state)
            return {"status": "review-dispatched", "launched": "reviewer",
                    "attempt": attempt_ids(state, "reviewer")[-1]}
        try:
            dispatch_repair(state, manifest)
        except RunError:
            save_state(path, state)
            raise
        save_state(path, state)
        return {"status": "repair-dispatched", "launched": "writer",
                "attempt": attempt_ids(state, "writer")[-1]}
    if reviewer_record["outcome"] == "blocked":
        state["blocked"] = {"reason": "reviewer-blocked", "attempt": reviewer_attempts[-1], "at": now()}
        event(state, "stopped", reason="reviewer-blocked")
        save_state(path, state)
        return {"status": "stopped", "reason": "reviewer-blocked", "launched": False}
    state["phase"] = "ready-to-handoff"
    state["review"] = {"attempt": reviewer_attempts[-1], "outcome": "approved",
                       "candidate_digest": reviewer_record["candidate_digest"]}
    event(state, "review-approved", attempt=reviewer_attempts[-1])
    save_state(path, state)
    return {"status": "ready-to-handoff", "launched": False}


def handoff(state_path: str, *, approve: bool) -> dict:
    if not approve:
        raise RunError("approval-required", "staging requires explicit --approve")
    path, state = load_state(state_path)
    if state.get("blocked"):
        raise RunError("blocked-state", "job is stopped; nothing is staged")
    if state.get("phase") != "ready-to-handoff":
        raise RunError("not-approved", "no approved reviewer receipt is recorded")
    manifest = load_manifest(state["manifest"])
    if contract.manifest_digest(manifest) != state["manifest_digest"]:
        raise RunError("manifest-drift", "manifest bytes changed since launch")
    drift = baseline_is_unchanged(manifest)
    if drift:
        state["blocked"] = {"reason": "baseline-drift", "detail": "; ".join(drift), "at": now()}
        save_state(path, state)
        raise RunError("baseline-drift", "; ".join(drift))
    reviewer = Path(state["review_tree"]).resolve()
    candidate = worker_worktree(manifest, state)
    receipt = read_json(receipt_path(state, "reviewer", state["review"]["attempt"]), "invalid-receipt")
    result = contract.integration(manifest, candidate, receipt)
    if not result["ok"]:
        raise RunError("integration-refused", "; ".join(result["errors"][:6]))
    if result["candidate_digest"] != state["review"]["candidate_digest"]:
        raise RunError("candidate-drift", "approved candidate identity changed before handoff")
    target = contract.repo_toplevel(manifest["repo"])
    files = contract.content_map(reviewer)
    changed = result["changed_paths"]
    for relative in changed:
        source = reviewer / relative
        destination = target / relative
        entry = files.get(relative, {})
        if entry.get("deleted"):
            destination.unlink()
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        destination.chmod(0o755 if entry["mode"] == "100755" else 0o644)
    git(target, "add", "--", *changed)
    status = contract.worktree_status(target)
    if not status or any(row[:2] not in ("M ", "A ", "D ") for row in status):
        raise RunError("stage-refused", f"unexpected staging state: {status}")
    if contract.resolve_commit(target, "HEAD") != manifest["base"]["commit"]:
        raise RunError("stage-refused", "HEAD moved during handoff")
    state["phase"] = "handed-off"
    state["handoff"] = {"paths": changed, "candidate_digest": result["candidate_digest"], "at": now()}
    event(state, "handed-off", paths=changed)
    save_state(path, state)
    return {"status": "handed-off", "paths": changed, "staged_only": True, "committed": False,
            "head": manifest["base"]["commit"]}


def switch_writer(state_path: str, *, model: str, approve: bool, reason: str) -> dict:
    if not approve:
        raise RunError("approval-required", "an eligible writer switch requires explicit --approve")
    path, state = load_state(state_path)
    blocked = state.get("blocked") or {}
    if state.get("phase") == "handed-off":
        raise RunError("blocked-state", "a handed-off job cannot switch roles")
    if state.get("phase") not in ("dispatched", "switch-dispatched", "repair-dispatched") and not blocked:
        raise RunError("blocked-state", "only a stopped or dispatched writer is eligible for a switch")
    if blocked.get("reason") not in (None, "writer-unavailable", "dispatch-failed", "writer-blocked"):
        raise RunError("blocked-state", f"a recorded {blocked.get('reason')} state cannot be switched around")
    last = state.get("last_dispatch") or {}
    if last.get("role") == "writer" and last.get("attempt") and not published(state, "writer", last["attempt"]):
        raise RunError("writer-active", "the active writer attempt has no published record; switch refused")
    route = parse_route(model, role="writer")
    identity = route_text(route)
    if identity not in state.get("writer_alternates", []):
        raise RunError("unapproved-route", "alternate writer was not bound and approved in the plan")
    if identity == route_text(state["writer_route"]):
        raise RunError("unapproved-route", "alternate writer must differ from the current route")
    if route["model"].rsplit("/", 1)[-1] == state["routes"]["reviewer"]["model"].rsplit("/", 1)[-1]:
        raise RunError("unapproved-route", "an alternate writer must remain distinct from the reviewer")
    manifest = load_manifest(state["manifest"])
    if baseline_is_unchanged(manifest):
        state["blocked"] = {"reason": "baseline-drift", "at": now()}
        save_state(path, state)
        raise RunError("baseline-drift", "target moved; refuse the switch and re-brief")
    if not reason.strip():
        raise RunError("invalid-request", "record the reason for the switch")
    if state.get("repairs", 0) >= REPAIR_LIMIT:
        state["blocked"] = {"reason": "repair-limit", "role": "writer", "at": now()}
        save_state(path, state)
        raise RunError("repair-limit", "two repair allowances are already recorded; an approved switch is not a third")
    attempt = next_attempt(state, "writer")
    allocate_attempt(state, "writer", attempt, "repair")
    try:
        require_dispatch_allowance(state, "writer", attempt)
    except RunError:
        save_state(path, state)
        raise
    state["writer_route"] = route
    state["switch"] = {"from": route_text(state["routes"]["writer"]), "to": identity,
                       "reason": reason, "attempt": attempt, "at": now()}
    state.pop("blocked", None)
    register_attempt(state, "writer", attempt, "repair")
    safe_dispatch(state, "writer", attempt, "", state["worktrees"]["writer"])
    state["phase"] = "switch-dispatched"
    state["repairs"] = state.get("repairs", 0) + 1
    event(state, "writer-switched", to=identity, attempt=attempt, repairs=state["repairs"])
    save_state(path, state)
    return {"status": "switch-dispatched", "writer": identity, "attempt": attempt,
            "coordinator": route_text(state["routes"]["coordinator"]),
            "reviewer": route_text(state["routes"]["reviewer"]), "launched": "writer"}


def stop(state_path: str, *, reason: str, role: str = "") -> dict:
    if not reason.strip():
        raise RunError("invalid-request", "record the reason for the stop")
    path, state = load_state(state_path)
    state["blocked"] = {"reason": reason, "role": role or None, "at": now()}
    event(state, "stopped", reason=reason, role=role or None)
    save_state(path, state)
    return {"status": "stopped", "reason": reason, "launched": False}


def status(state_path: str) -> dict:
    _path, state = load_state(state_path)
    overall = overall_remaining(state)
    records = {}
    for row in state.get("attempts", []):
        record = read_record(state, row["role"], row["attempt"]) or {"status": "unreadable", "record": {}}
        records[f"{row['role']}.{row['attempt']}"] = {
            "status": record["status"],
            "outcome": record["record"].get("outcome") if record["status"] == "published" else None,
        }
    return {"task": state["task"], "phase": state["phase"], "blocked": state.get("blocked"),
            "listener_mode": state["listener"].get("mode"),
            "routes": {"coordinator": route_text(state["routes"]["coordinator"]),
                       "writer": route_text(state.get("writer_route", state["routes"]["writer"])),
                       "reviewer": route_text(state["routes"]["reviewer"])},
            "worktrees": state["worktrees"], "records": records,
            "policy": state.get("policy"), "usage": state.get("usage"),
            "attempt_allocations": state.get("attempt_allocations", {}),
            "attempt_usage": state.get("attempt_usage", {}),
            "attempt_remaining": {key: dict(zip(("minutes", "calls"), attempt_remaining(state, key)))
                                  for key in state.get("attempt_allocations", {})},
            "overall_limit": state.get("overall_limit"),
            "overall_remaining": None if overall is None else {"minutes": overall[0], "calls": overall[1]},
            "dispatch_is_not_inferred": True}
