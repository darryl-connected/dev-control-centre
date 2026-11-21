"""Private version 1 factory notifications. Neither a gate nor a process launcher."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path
from typing import Any

import factory_contract as contract

REGISTRATION = "registration.json"
RECORD = 4096
IDENTITY = 2 * 1024 * 1024
PAYLOAD = 128 * 1024
STAGES = {"writer": ("reported", "blocked"), "reviewer": ("approved", "changes_requested", "blocked")}
JOB_KEYS = {"version", "job", "session", "session_file", "expires_ms", "manifest_digest"}
BINDINGS = {"version", "job", "session", "manifest_digest", "stage", "attempt", "candidate_digest"}
EVENT_KEYS = BINDINGS | {"outcome", "report_sha256", "evidence_sha256"}
DETAILS = {
    "invalid-request": "Check route arguments with --help.",
    "approval-required": "Runtime writes require explicit --approve.",
    "missing-registration": "No job registration at the specified path.",
    "invalid-registration": "Expected a private version 1 job registration.",
    "expired-registration": "The job registration has expired.",
    "unsafe-path": "Use an absolute, canonical path with safe directory ancestry.",
    "invalid-manifest": "Expected a bounded valid factory manifest and job ID.",
    "invalid-session": "Expected an established persistent Pi session file.",
    "invalid-attempt": "Expected a registered role and attempt with matching identity.",
    "record-exists": "An immutable runtime record already exists.",
    "invalid-payload": "Expected bounded private report and evidence files.",
    "receipt-mismatch": "Reviewer receipt does not match the registered candidate and verdict.",
    "invalid-event": "Published event or its bound records do not match.",
    "write-failed": "Could not create the private runtime records.",
}


class Refusal(Exception):
    def __init__(self, code: str):
        super().__init__(f"{code}: {DETAILS[code]}")


def matches(value: Any, pattern: str) -> bool:
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def identity(value: Any) -> bool:
    return matches(value, r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")


def digest(value: Any) -> bool:
    return matches(value, r"[a-f0-9]{64}")


def attempt_id(value: Any) -> bool:
    return matches(value, r"[a-z0-9][a-z0-9_-]{0,31}")


def canonical_path(value: Any) -> Path:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 2048 or re.search(r"[\x00-\x1f\x7f]", value):
        raise Refusal("unsafe-path")
    path = Path(value)
    if not path.is_absolute() or path.anchor != "/" or path == Path("/") or str(path) != value or ".." in path.parts:
        raise Refusal("unsafe-path")
    return path


def directory(path: Path, *, private: bool = False) -> None:
    for parent in (*reversed(path.parents), path):
        item = parent.lstat()
        sticky_system_dir = item.st_uid == 0 and item.st_mode & stat.S_ISVTX
        if (not stat.S_ISDIR(item.st_mode) or item.st_uid not in (0, os.getuid())
                or (item.st_mode & 0o022 and not sticky_system_dir)):
            raise Refusal("unsafe-path")
        if parent == path and private and (item.st_uid != os.getuid() or item.st_mode & 0o077):
            raise Refusal("unsafe-path")


def read_bytes(path: Path, limit: int, *, prefix: bool = False, immutable: bool = False) -> bytes:
    initial = path.lstat()
    if not stat.S_ISREG(initial.st_mode):
        raise ValueError("not a regular file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as handle:
        item = os.fstat(handle.fileno())
        if (not stat.S_ISREG(item.st_mode) or item.st_uid != os.getuid() or item.st_mode & 0o077
                or (immutable and stat.S_IMODE(item.st_mode) != 0o400)
                or (item.st_dev, item.st_ino) != (initial.st_dev, initial.st_ino)
                or item.st_size <= 0 or (not prefix and item.st_size > limit)):
            raise ValueError("not a bounded private record")
        if prefix:
            data = handle.readline(limit + 1)
            if len(data) <= limit and data.endswith(b"\n"):
                return data
        else:
            data = handle.read(limit + 1)
            if len(data) == item.st_size:
                return data
    raise ValueError("incomplete record")


def encode(value: dict) -> bytes:
    # Protocol records (not reports) have a flat, canonical wire representation.
    return (contract.canonical_json(value) + "\n").encode("utf-8")


def json_object(data: bytes, *, canonical: bool = False) -> dict:
    def pairs(items: list[tuple[str, Any]]) -> dict:
        row = dict(items)
        if len(row) != len(items):
            raise ValueError("duplicate key")
        return row

    def invalid_constant(_value: str) -> None:
        raise ValueError("invalid constant")

    row = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid_constant)
    if not isinstance(row, dict) or (canonical and encode(row) != data):
        raise ValueError("invalid record")
    return row


def source(raw: str, limit: int, code: str, *, prefix: bool = False) -> bytes:
    path = canonical_path(raw)
    try:
        directory(path.parent)
        return read_bytes(path, limit, prefix=prefix)
    except (OSError, ValueError) as exc:
        raise Refusal(code) from exc


def source_json(raw: str, limit: int, code: str, *, prefix: bool = False) -> dict:
    try:
        return json_object(source(raw, limit, code, prefix=prefix))
    except (ValueError, RecursionError) as exc:
        raise Refusal(code) from exc


def fresh(expires_ms: Any) -> None:
    if type(expires_ms) is not int or not 0 < expires_ms < 2**53:
        raise ValueError("invalid expiry")
    if expires_ms <= time.time_ns() // 1_000_000:
        raise Refusal("expired-registration")


def registration(raw: str) -> tuple[Path, dict]:
    path = canonical_path(raw)
    if path.name != REGISTRATION:
        raise Refusal("invalid-registration")
    try:
        directory(path.parent, private=True)
        row = json_object(read_bytes(path, RECORD, immutable=True), canonical=True)
        if (row.keys() != JOB_KEYS or type(row["version"]) is not int or row["version"] != 1
                or not identity(row["job"]) or not identity(row["session"]) or not digest(row["manifest_digest"])):
            raise ValueError("invalid registration")
        canonical_path(row["session_file"])
        fresh(row["expires_ms"])
    except FileNotFoundError as exc:
        raise Refusal("missing-registration") from exc
    except (OSError, ValueError, RecursionError) as exc:
        raise Refusal("invalid-registration") from exc
    return path, row


def immutable(path: Path, data: bytes) -> None:
    """Expose complete data atomically without replacement; no crash guarantee."""
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-") as handle:
        handle.write(data)
        handle.flush()
        os.fchmod(handle.fileno(), 0o400)
        os.link(handle.name, path)


def stored_status(status: str, record: dict) -> dict:
    return {"status": status, "authority": "notification-only", "record": record}


def register_job(raw: str, manifest_path: str, session_file: str, expires_ms: int) -> dict:
    root = canonical_path(raw)
    try:
        directory(root, private=True)
    except OSError as exc:
        raise Refusal("unsafe-path") from exc
    try:
        fresh(expires_ms)
    except ValueError as exc:
        raise Refusal("invalid-registration") from exc
    manifest = source_json(manifest_path, IDENTITY, "invalid-manifest")
    errors, _warnings = contract.validate_manifest(manifest, require_baseline=True)
    if errors or not identity(manifest.get("task", {}).get("id")):
        raise Refusal("invalid-manifest")
    session = source_json(session_file, RECORD, "invalid-session", prefix=True)
    if session.get("type") != "session" or session.get("version") != 3 or not identity(session.get("id")):
        raise Refusal("invalid-session")
    try:
        workspace = canonical_path(session.get("cwd"))
    except Refusal as exc:
        raise Refusal("invalid-session") from exc
    for protected in (Path(__file__).resolve().parents[2], workspace.resolve(), Path(manifest["repo"]).resolve(),
                      Path(manifest["writer"]["worktree"]).resolve()):
        if root.is_relative_to(protected) or protected.is_relative_to(root):
            raise Refusal("unsafe-path")
    row = {"version": 1, "job": manifest["task"]["id"], "session": session["id"], "session_file": session_file,
           "expires_ms": expires_ms, "manifest_digest": contract.manifest_digest(manifest)}
    data = encode(row)
    if len(data) > RECORD:
        raise Refusal("invalid-registration")
    immutable(root / REGISTRATION, data)
    return stored_status("registered", row)


def attempt_location(path: Path, stage: str, attempt: str) -> Path:
    if stage not in STAGES or not attempt_id(attempt):
        raise Refusal("invalid-attempt")
    return path.parent / f"{stage}.{attempt}"


def binding(job: dict, stage: str, attempt: str, candidate: str | None) -> dict:
    return {**{key: job[key] for key in ("version", "job", "session", "manifest_digest")},
            "stage": stage, "attempt": attempt, "candidate_digest": candidate}


def register_attempt(raw: str, stage: str, attempt: str, candidate_file: str | None) -> dict:
    path, job = registration(raw)
    slot = attempt_location(path, stage, attempt)
    candidate = None
    if stage == "reviewer" and candidate_file:
        data = source_json(candidate_file, IDENTITY, "invalid-attempt")
        candidate = data.get("candidate_digest")
        files = data.get("files")
        if (data.keys() != {"manifest_digest", "candidate_digest", "candidate", "files"}
                or data["manifest_digest"] != job["manifest_digest"] or not digest(candidate)
                or not isinstance(files, dict) or not files
                or candidate != contract.candidate_digest(job["manifest_digest"], files)):
            raise Refusal("invalid-attempt")
    elif stage != "writer" or candidate_file is not None:
        raise Refusal("invalid-attempt")
    row = binding(job, stage, attempt, candidate)
    slot.mkdir(mode=0o700)
    immutable(slot / "attempt.json", encode(row))
    return stored_status("attempt-registered", row)


def read_attempt(path: Path, job: dict, stage: str, attempt: str) -> tuple[Path, dict]:
    slot = attempt_location(path, stage, attempt)
    try:
        directory(slot, private=True)
        row = json_object(read_bytes(slot / "attempt.json", RECORD, immutable=True), canonical=True)
        candidate = row.get("candidate_digest")
        if (type(row.get("version")) is not int or row != binding(job, stage, attempt, candidate)
                or (stage == "writer" and candidate is not None) or (stage == "reviewer" and not digest(candidate))):
            raise ValueError("invalid attempt")
    except (OSError, Refusal, ValueError, RecursionError) as exc:
        raise Refusal("invalid-attempt") from exc
    return slot, row


def check_receipt(row: dict, outcome: str, report: bytes) -> None:
    try:
        receipt = json_object(report)
        if (type(receipt.get("version")) is int and receipt["version"] == 1
                and receipt.get("manifest_digest") == row["manifest_digest"]
                and receipt.get("candidate_digest") == row["candidate_digest"] and receipt.get("verdict") == outcome):
            return
    except (ValueError, RecursionError):
        pass
    raise Refusal("receipt-mismatch")


def present(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def publish(raw: str, stage: str, attempt: str, outcome: str, report_file: str, evidence_file: str) -> dict:
    path, job = registration(raw)
    slot, row = read_attempt(path, job, stage, attempt)
    if outcome not in STAGES[stage]:
        raise Refusal("invalid-attempt")
    records = slot / "records"
    if present(records) or present(slot / "event.json"):
        raise Refusal("record-exists")
    report = source(report_file, PAYLOAD, "invalid-payload")
    evidence = source(evidence_file, PAYLOAD, "invalid-payload")
    if stage == "reviewer":
        check_receipt(row, outcome, report)
    fresh(job["expires_ms"])
    terminal = dict(row, outcome=outcome, report_sha256=contract.sha256_bytes(report),
                    evidence_sha256=contract.sha256_bytes(evidence))
    # mkdir reserves the attempt's one publication. Interruption leaves a partial
    # attempt, never a visible terminal event with half-written payloads.
    records.mkdir(mode=0o700)
    immutable(records / "report", report)
    immutable(records / "evidence", evidence)
    immutable(slot / "event.json", encode(terminal))
    return stored_status("published", terminal)


def inspect(raw: str, stage: str | None, attempt: str | None) -> dict:
    path, job = registration(raw)
    if stage is None and attempt is None:
        return stored_status("registered", job)
    if stage is None or attempt is None:
        raise Refusal("invalid-attempt")
    slot, row = read_attempt(path, job, stage, attempt)
    event_path = slot / "event.json"
    if not present(event_path):
        return stored_status("attempt-registered", row)
    try:
        event = json_object(read_bytes(event_path, RECORD, immutable=True), canonical=True)
        if (event.keys() != EVENT_KEYS or type(event["version"]) is not int
                or any(event[key] != row[key] for key in BINDINGS) or event["outcome"] not in STAGES[stage]):
            raise ValueError("invalid event")
        records = slot / "records"
        directory(records, private=True)
        report = read_bytes(records / "report", PAYLOAD, immutable=True)
        evidence = read_bytes(records / "evidence", PAYLOAD, immutable=True)
        if (contract.sha256_bytes(report) != event["report_sha256"]
                or contract.sha256_bytes(evidence) != event["evidence_sha256"]):
            raise ValueError("payload digest mismatch")
    except (OSError, Refusal, ValueError, RecursionError) as exc:
        raise Refusal("invalid-event") from exc
    if stage == "reviewer":
        check_receipt(row, event["outcome"], report)
    return stored_status("published", event)