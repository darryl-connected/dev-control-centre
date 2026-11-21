"""Independent expected wire records and diagnostics exercised by the shipped CLI."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import runpy
import stat
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
CLI = "scripts/factory-inbox.py"
SALT = "Synthetic report prose: RUN_NO_SUCH_COMMAND; not for callback context."
MANIFEST_ERROR = "invalid-manifest: Expected a bounded valid factory manifest and job ID."
NO_APPROVAL = "approval-required: Runtime writes require explicit --approve."
MISSING = "missing-registration: No job registration at the specified path."
INVALID_REG = "invalid-registration: Expected a private version 1 job registration."
EXPIRED = "expired-registration: The job registration has expired."
UNSAFE = "unsafe-path: Use an absolute, canonical path with safe directory ancestry."
INVALID_ATTEMPT = "invalid-attempt: Expected a registered role and attempt with matching identity."
INVALID_REQUEST = "invalid-request: Check route arguments with --help."
INVALID_OUTCOME = "invalid-outcome: Expected a supported reviewer verdict."
OUTCOME_CONFLICT = "outcome-conflict: Explicit reviewer outcome differs from the receipt verdict."
RECEIPT = "receipt-mismatch: Reviewer receipt does not match the registered candidate and verdict."
INVALID_EVENT = "invalid-event: Published event or its bound records do not match."
EXISTS = "record-exists: An immutable runtime record already exists."
INVALID_PAYLOAD = "invalid-payload: Expected bounded private report and evidence files."


def packed(row):
    return (json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def put(path, data, mode=0o600):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
        handle.write(packed(data) if isinstance(data, dict) else data)
    path.chmod(mode)
    return path


def tree(root):
    return {str(p.relative_to(root)): (stat.S_IMODE(p.stat().st_mode), p.read_bytes() if p.is_file() else None)
            for p in root.rglob("*")}


def evidence_dir(prefix):
    return Path(tempfile.mkdtemp(prefix=prefix, dir=os.environ.get("DCC_EVIDENCE"))).resolve()


def plant_inbox_origin_probes(inbox):
    """Data canaries outside the relocated kit, never loaded by the test runner."""
    put(inbox / "external-helper.js", b"process.getBuiltinModule('node:fs').writeFileSync("
        b"process.env.DCC_OFFLINE_FIXTURE + '/external-helper-executed', 'PRIVATE_HELPER_EXECUTED\\n');\n", 0o400)
    put(inbox / "external-helper.py", b"from pathlib import Path\nimport os\n"
        b"(Path(os.environ['DCC_OFFLINE_FIXTURE']) / 'python-helper-executed').write_text('PRIVATE_PYTHON_HELPER_EXECUTED\\n')\n", 0o400)


@contextmanager
def inbox_origin_window(test, inbox, phase, *, allowed, required=(), producer=False):
    """Audit successful file opens and data access in the existing inbox directories.

    Use only around an isolated runtime interval. The observer enumerates dirs before
    installing watches and does not open any inbox file or marker before draining.
    This is not a PID-attributing tracer or recursive monitoring of new directories.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    directories = [inbox, *(p for p in inbox.rglob("*") if p.is_dir() and not p.is_symlink())]
    access, opened, overflow, isdir = 0x1, 0x20, 0x4000, 0x40000000
    header = struct.Struct("iIII")
    fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "inotify_init1")
    observed = set()
    try:
        watches = {}
        for directory in directories:
            wd = libc.inotify_add_watch(fd, os.fsencode(directory), access | opened)
            if wd < 0:
                raise OSError(ctypes.get_errno(), "inotify_add_watch")
            watches[wd] = directory
        yield
        while True:
            try:
                data = os.read(fd, 65536)
            except OSError as error:
                if error.errno != errno.EAGAIN:
                    raise
                break
            offset = 0
            while offset < len(data):
                wd, mask, _, length = header.unpack_from(data, offset)
                offset += header.size
                name = os.fsdecode(data[offset:offset + length].split(b"\0", 1)[0])
                offset += length
                test.assertFalse(mask & overflow, "relocated inbox origin audit overflowed")
                if name and not mask & isdir:
                    relative = (watches[wd] / name).relative_to(inbox).as_posix()
                    if mask & opened:
                        observed.add((relative, "open"))
                    if mask & access:
                        observed.add((relative, "access"))
    finally:
        os.close(fd)
    # Collect the execution effects only after closing the observation window.
    markers = {name: (inbox.parent / name).read_text() for name in ("external-helper-executed", "python-helper-executed")
               if (inbox.parent / name).exists()}
    unexpected = [(p, event) for p, event in sorted(observed) if p not in allowed
                  and not (producer and event == "open" and Path(p).name.startswith(".pending-"))]
    journal = inbox.parent / "inbox-origins.jsonl"
    with journal.open("ab") as out:
        out.write(packed({"phase": phase, "observed": sorted(observed), "unexpected": unexpected, "execution_markers": markers,
                          "directories": sorted(p.relative_to(inbox).as_posix() for p in directories)}))
    test.assertEqual((unexpected, markers), ([], {}), f"G6 {phase}: relocated inbox permitted data only, not helper reads or evaluation")
    test.assertLessEqual({(p, "access") for p in required}, observed, f"G6 {phase}: audit missed expected protocol reads")


def confined_exec(args):
    """Linux-only archive test launcher: deny file reads and execution elsewhere."""
    index = args.index("--")
    fixture, relocated, forbidden_file, forbidden_executable, *runtime = map(Path, args[:index])
    command = args[index + 1:]
    libc = ctypes.CDLL(None, use_errno=True)

    def checked(result, operation):
        if result < 0:
            raise OSError(ctypes.get_errno(), operation)
        return result

    execute, read_file, read_dir = 1, 4, 8  # landlock_access_fs
    # Stable Linux syscall numbers on the acceptance host (and Linux arm64).
    create_ruleset, add_rule, restrict_self = 444, 445, 446
    checked(libc.syscall(create_ruleset, None, 0, 1), "Landlock ABI query")
    attrs = ctypes.create_string_buffer(struct.pack("=Q", execute | read_file | read_dir))
    ruleset = checked(libc.syscall(create_ruleset, ctypes.byref(attrs), 8, 0), "Landlock create")
    try:
        for path, rights in [
            (fixture, read_file | read_dir), (relocated, read_file | read_dir),
            (Path("/usr"), read_file | read_dir), (Path("/usr/lib"), execute),
            (Path("/etc"), read_file | read_dir), (Path("/proc"), read_file | read_dir),
            (Path("/dev"), read_file | read_dir), (Path("/sys"), read_file | read_dir),
            *((p, read_file | (read_dir if p.is_dir() else execute)) for p in runtime),
        ]:
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = ctypes.create_string_buffer(struct.pack("=Qi", rights, fd))
                checked(libc.syscall(add_rule, ruleset, 1, ctypes.byref(rule), 0), "Landlock path policy")
            finally:
                os.close(fd)
        checked(libc.prctl(38, 1, 0, 0, 0), "no_new_privs")
        checked(libc.syscall(restrict_self, ruleset, 0), "Landlock restrict")
    finally:
        os.close(ruleset)
    # Active negative controls: both real syscalls must refuse otherwise usable paths.
    try:
        forbidden_file.read_bytes()
    except PermissionError:
        pass
    else:
        raise AssertionError("original source read was not denied")
    try:
        subprocess.run([str(forbidden_executable)], check=True, capture_output=True)
    except PermissionError:
        pass
    else:
        raise AssertionError("outside executable was not denied")
    os.execv(command[0], command)


def observe_publication(args):
    """Observe the real producer's last-link boundary, without replacing its filesystem calls."""
    journal, script, *argv = args

    def audit(event, details):
        if event != "os.link":
            return
        destination = Path(details[1])
        if destination.name == "event.json":
            records = destination.parent / "records"
            existing = {p.name: sha(p.read_bytes()) for p in records.iterdir() if p.name in {"report", "evidence"}} if records.is_dir() else {}
            with open(journal, "ab") as handle:
                handle.write(packed({"event_exists": destination.exists(), "complete": existing}))

    sys.addaudithook(audit)
    sys.argv = [script, *argv]
    runpy.run_path(script, run_name="__main__")


class Records:
    def __init__(self, test, root, kit=KIT, launcher=(), *, example=None):
        self.test = test
        self.root = root
        self.kit = kit
        self.launcher = launcher
        self.workspace = root / "workspace"
        self.home = root / "home"
        self.target = root / "target"
        self.inbox = root / "inbox"
        for path in (self.workspace, self.home, self.target, self.inbox):
            path.mkdir(mode=0o700)
        self.env = {k: os.environ[k] for k in ("PATH", "LANG") if k in os.environ}
        self.env.update(HOME=str(self.home), TMPDIR=str(root), PI_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1")
        self.registration = self.inbox / "registration.json"
        self.session = "fixture-conversation"
        self.expires = int(time.time() * 1000) + 120_000
        self.job = "FIXTURE-1"
        if example is None:
            example = self.run("scripts/factory-job.py", "example").stdout
        self.manifest = json.loads(example)
        files = {"src/example.py": {"sha256": sha(b"synthetic baseline"), "mode": "100644"}}
        self.manifest.update(task={"id": self.job, "goal": "Synthetic notification test"}, repo=str(self.target),
                             base={"commit": "1" * 40, "index_digest": "2" * 64, "status": [], "files": files})
        self.manifest["writer"]["worktree"] = str(root / "not-created-writer")
        self.manifest_file = put(root / "manifest.json", self.manifest)
        self.manifest_id = sha(packed(self.manifest)[:-1])
        self.candidate_file = put(root / "candidate.json", self.candidate(files))
        self.prose = put(root / "writer-report", SALT.encode())
        self.evidence = put(root / "evidence-file", b"synthetic local evidence\n")

    def run(self, script, *args):
        argv = [*self.launcher, sys.executable, "-B", str(self.kit / script), *map(str, args)]
        origin: AbstractContextManager[None] = nullcontext()
        if self.launcher and script == CLI:
            stage = " ".join(map(str, args[:2])) if args[0] == "register" else str(args[0])
            reads = {"registration.json"} if stage != "register job" else set()
            if stage == "publish":
                reads.add(f"{args[2]}.{args[3]}/attempt.json")
            origin = inbox_origin_window(self.test, self.inbox, f"CLI {stage}", allowed=reads, required=reads, producer=True)
        with (
            (self.root / "producer-processes.jsonl").open("ab") as log,
            origin,
            subprocess.Popen(argv, cwd=self.workspace, env=self.env, umask=0o077,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc,
        ):
            out, err = proc.communicate(timeout=10)
            log.write(packed({"pid": proc.pid, "exit": proc.returncode, "argv": argv, "stdout": out, "stderr": err,
                              "at_ns": time.time_ns()}))
            return subprocess.CompletedProcess(argv, proc.returncode, out, err)

    def cli(self, *args, error=None, exit_code=1, status=None):
        result = self.run(CLI, *args)
        if error:
            self.test.assertEqual((result.returncode, result.stdout, result.stderr), (exit_code, "", error + "\n"))
            return None
        self.test.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        if status:
            row = json.loads(result.stdout)
            self.test.assertEqual(set(row), {"status", "authority", "record"})
            self.test.assertEqual((row["status"], row["authority"]), (status, "notification-only"))
            return row["record"]
        return result.stdout

    def candidate(self, files):
        candidate_digest = sha(packed({"manifest": self.manifest_id, "files": files})[:-1])
        return {"manifest_digest": self.manifest_id, "files": files,
                "candidate": str(self.root / "not-created-writer"), "candidate_digest": candidate_digest}

    def job_record(self, session_file):
        return {"version": 1, "job": self.job, "session": self.session, "session_file": str(session_file),
                "manifest_digest": self.manifest_id, "expires_ms": self.expires}

    def job_args(self, session_file):
        return ("register", "job", self.inbox, "--manifest", self.manifest_file,
                "--session", session_file, "--expires-ms", self.expires)

    def register(self, session_file):
        row = self.cli(*self.job_args(session_file), "--approve", status="registered")
        self.test.assertEqual(row, self.job_record(session_file))
        self.test.assertEqual(self.registration.read_bytes(), packed(row))

    def binding(self, stage, attempt):
        return {"version": 1, "job": self.job, "session": self.session, "manifest_digest": self.manifest_id,
                "stage": stage, "attempt": attempt, "candidate_digest": (
                    json.loads(self.candidate_file.read_bytes())["candidate_digest"] if stage == "reviewer" else None)}

    def attempt_args(self, stage, attempt):
        options = ("--candidate", self.candidate_file) if stage == "reviewer" else ()
        return ("register", "attempt", self.registration, stage, attempt, *options)

    def attempt(self, stage, attempt):
        row = self.cli(*self.attempt_args(stage, attempt), "--approve", status="attempt-registered")
        self.test.assertEqual(row, self.binding(stage, attempt))
        return self.inbox / f"{stage}.{attempt}"

    def receipt(self, attempt, outcome, **changes):
        binding = self.binding("reviewer", attempt)
        receipt = {"version": 1, "manifest_digest": binding["manifest_digest"], "candidate_digest": binding["candidate_digest"],
                   "verdict": outcome, "reviewer": {"model": "fixture-only", "worktree": str(self.root / "no-reviewer")},
                   "findings": [], "verification": [], "mutations": [], "not_verified": [SALT]}
        return packed(receipt | changes)

    def publish_args(self, stage, attempt, outcome=None, *, report=None, evidence=None):
        explicit = () if outcome is None else (outcome,)
        return ("publish", self.registration, stage, attempt, *explicit, "--report", report or self.prose,
                "--evidence", evidence or self.evidence)

    def publish(self, stage, attempt, outcome, *, derive=False, report=None):
        slot = self.inbox / f"{stage}.{attempt}"
        if report is None:
            report = (put(self.root / f"{slot.name}.receipt", self.receipt(attempt, outcome))
                      if stage == "reviewer" else self.prose)
        report_bytes, evidence_bytes = report.read_bytes(), self.evidence.read_bytes()
        binding = self.binding(stage, attempt)
        expected = dict(binding, outcome=outcome, report_sha256=sha(report_bytes), evidence_sha256=sha(evidence_bytes))
        actual = self.cli(*self.publish_args(stage, attempt, None if derive else outcome, report=report),
                          "--approve", status="published")
        self.test.assertEqual(actual, expected)
        for name, payload in (("attempt.json", packed(binding)), ("event.json", packed(expected))):
            path = slot / name
            self.test.assertEqual((stat.S_IMODE(path.stat().st_mode), path.read_bytes()), (0o400, payload), name)
        records = slot / "records"
        self.test.assertEqual(stat.S_IMODE(records.stat().st_mode), 0o700)
        self.test.assertEqual(tree(records), {"report": (0o400, report_bytes), "evidence": (0o400, evidence_bytes)})
        self.test.assertEqual((report.read_bytes(), self.evidence.read_bytes()), (report_bytes, evidence_bytes))
        return expected


class PublisherTest(unittest.TestCase):
    def setUp(self):
        self.r = Records(self, evidence_dir("handoff-cli-"))
        self.session_file = put(self.r.root / "conversation.jsonl", {"type": "session", "version": 3, "id": self.r.session,
                                "cwd": str(self.r.workspace), "timestamp": "2026-01-01T00:00:00Z"})

    def test_cli_help_syntax_and_approval_routes(self):
        r = self.r
        for route, tokens in (
            ((), ("{inspect,register,publish}", "notification only")),
            (("inspect",), ("registration", "stage", "attempt")),
            (("register",), ("{job,attempt}",)),
            (("register", "job"), ("--manifest", "--session", "--expires-ms", "--approve")),
            (("register", "attempt"), ("--candidate", "--approve", "{writer,reviewer}")),
            (("publish",), ("--report", "--evidence", "--approve", "outcome")),
        ):
            with self.subTest(route=route):
                text = " ".join(r.cli(*route, "--help").split())
                for token in tokens:
                    self.assertIn(token, text)
        for args in ((), ("nonexistent",), ("inspect",), ("register",), ("register", "job"),
                     ("register", "attempt"), ("publish",)):
            with self.subTest(invalid_request=args):
                r.cli(*args, error=INVALID_REQUEST, exit_code=2)
        before = tree(r.inbox)
        for args in (r.job_args(self.session_file), r.attempt_args("writer", "a1"), r.publish_args("writer", "a1", "reported")):
            with self.subTest(route=args[:2]):
                r.cli(*args, error=NO_APPROVAL)
                self.assertEqual(tree(r.inbox), before)

    def test_missing_registration_details_on_each_real_route(self):
        r = self.r
        for args in (("inspect", r.registration), (*r.attempt_args("writer", "a1"), "--approve"),
                     (*r.publish_args("writer", "a1", "reported"), "--approve")):
            with self.subTest(route=args[:2]):
                r.cli(*args, error=MISSING)
        self.assertEqual(tree(r.inbox), {})

    def test_registration_refusals_and_immutable_records(self):
        r = self.r
        r.cli("inspect", "relative/registration.json", error=UNSAFE)
        bad_header = put(r.root / "bad-header.jsonl", {"type": "message", "version": 3, "id": r.session,
                                                       "cwd": str(r.workspace)})
        for path in (r.root / "missing", bad_header):
            r.cli(*r.job_args(path), "--approve", error="invalid-session: Expected an established persistent Pi session file.")
        r.manifest_file.write_bytes(b"{\"version\":1")
        r.cli(*r.job_args(self.session_file), "--approve", error=MANIFEST_ERROR)
        r.manifest_file.write_bytes(packed(r.manifest | {"task": r.manifest["task"] | {"id": "wrong id"}}))
        r.cli(*r.job_args(self.session_file), "--approve", error=MANIFEST_ERROR)
        r.manifest_file.write_bytes(packed(r.manifest))
        expires = r.expires
        r.expires = 1
        r.cli(*r.job_args(self.session_file), "--approve", error=EXPIRED)
        put(r.registration, r.job_record(self.session_file), 0o400)
        r.cli("inspect", r.registration, error=EXPIRED)
        r.registration.unlink()
        r.expires = expires
        put(r.registration, b"{", 0o400)
        r.cli("inspect", r.registration, error=INVALID_REG)
        r.registration.unlink()
        r.inbox.chmod(0o755)
        r.cli(*r.job_args(self.session_file), "--approve", error=UNSAFE)
        r.inbox.chmod(0o700)
        r.register(self.session_file)
        r.registration.chmod(0o644)
        r.cli("inspect", r.registration, error=INVALID_REG)
        r.registration.chmod(0o400)
        before = tree(r.inbox)
        r.cli(*r.job_args(self.session_file), "--approve", error=EXISTS)
        self.assertEqual(r.cli("inspect", r.registration, status="registered"), r.job_record(self.session_file))
        self.assertEqual(tree(r.inbox), before)

    def test_invalid_attempt_details_and_valid_later_publication(self):
        r = self.r
        r.register(self.session_file)
        before = tree(r.inbox)
        r.cli("inspect", r.registration, "writer", error=INVALID_ATTEMPT)
        r.cli("inspect", r.registration, "writer", "unknown", error=INVALID_ATTEMPT)
        r.cli(*r.publish_args("writer", "unknown", "reported"), "--approve", error=INVALID_ATTEMPT)
        r.cli(*r.attempt_args("writer", "../escape"), "--approve", error=INVALID_ATTEMPT)
        r.cli(*r.attempt_args("bad-role", "a1"), "--approve", error=INVALID_ATTEMPT)
        r.cli("register", "attempt", r.registration, "reviewer", "a1", "--approve", error=INVALID_ATTEMPT)
        saved = r.candidate_file.read_bytes()
        r.candidate_file.write_bytes(packed(json.loads(saved) | {"candidate_digest": "1" * 64}))
        r.cli(*r.attempt_args("reviewer", "a1"), "--approve", error=INVALID_ATTEMPT)
        r.candidate_file.write_bytes(saved)
        self.assertEqual(tree(r.inbox), before)
        slot = r.attempt("writer", "a1")
        r.cli(*r.attempt_args("writer", "a1"), "--approve", error=EXISTS)
        r.cli(*r.publish_args("writer", "a1", "approved"), "--approve", error=INVALID_ATTEMPT)
        self.assertEqual(r.cli("inspect", r.registration, "writer", "a1", status="attempt-registered"), r.binding("writer", "a1"))
        expected = r.publish("writer", "a1", "reported")
        before = tree(r.inbox)
        r.cli(*r.publish_args("writer", "a1", "reported"), "--approve", error=EXISTS)
        self.assertEqual(r.cli("inspect", r.registration, "writer", "a1", status="published"), expected)
        self.assertEqual(tree(r.inbox), before)
        for path in (r.registration, slot / "attempt.json", slot / "event.json", slot / "records/report", slot / "records/evidence"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o400, path)

    def test_writer_outcome_is_required_and_both_explicit_forms_still_publish(self):
        r = self.r
        r.register(self.session_file)
        for outcome in ("reported", "blocked"):
            with self.subTest(outcome=outcome):
                r.attempt("writer", outcome)
                before = tree(r.inbox)
                r.cli(*r.publish_args("writer", outcome), "--approve", error=INVALID_REQUEST, exit_code=2)
                self.assertEqual(tree(r.inbox), before)
                r.publish("writer", outcome, outcome)

    def test_reviewer_refusals_preserve_input_and_allow_matching_explicit_call(self):
        r = self.r
        r.register(self.session_file)
        cases = (
            ("writer-only", "reported", {}, INVALID_OUTCOME),
            ("unsupported", None, {"verdict": "reported"}, INVALID_OUTCOME),
            ("wrong-verdict-type", None, {"verdict": ["approved"]}, INVALID_OUTCOME),
            ("conflict", "changes_requested", {}, OUTCOME_CONFLICT),
            ("candidate", None, {"candidate_digest": "a" * 64}, RECEIPT),
            ("manifest", "approved", {"manifest_digest": "b" * 64}, RECEIPT),
            ("version", None, {"version": True}, RECEIPT),
            ("malformed", None, None, RECEIPT),
        )
        for attempt, explicit, changes, error in cases:
            with self.subTest(attempt=attempt):
                r.attempt("reviewer", attempt)
                report_bytes = b'{"version":1' if changes is None else r.receipt(attempt, "approved", **changes)
                report = put(r.root / f"{attempt}.refused", report_bytes)
                evidence = r.evidence.read_bytes()
                before = tree(r.inbox)
                r.cli(*r.publish_args("reviewer", attempt, explicit, report=report), "--approve", error=error)
                self.assertEqual(tree(r.inbox), before)
                self.assertEqual((report.read_bytes(), r.evidence.read_bytes()), (report_bytes, evidence))
                r.publish("reviewer", attempt, "approved", report=report if changes == {} else None)

    def test_reviewer_requires_registered_attempt_even_when_deriving(self):
        r = self.r
        r.register(self.session_file)
        report = put(r.root / "unknown.receipt", r.receipt("unknown", "approved"))
        before = tree(r.inbox)
        r.cli(*r.publish_args("reviewer", "unknown", report=report), "--approve", error=INVALID_ATTEMPT)
        self.assertEqual(tree(r.inbox), before)
        r.attempt("reviewer", "unknown")
        r.publish("reviewer", "unknown", "approved", derive=True, report=report)

    def test_reviewer_duplicate_preserves_publication_and_inspect_checks_records(self):
        r = self.r
        r.register(self.session_file)
        slot = r.attempt("reviewer", "a1")
        expected = r.publish("reviewer", "a1", "approved", derive=True)
        before = tree(r.inbox)
        alternate = put(r.root / "alternate.receipt", r.receipt("a1", "blocked"))
        evidence = put(r.root / "alternate.evidence", b"different evidence\n")
        r.cli(*r.publish_args("reviewer", "a1", "blocked", report=alternate, evidence=evidence), "--approve", error=EXISTS)
        self.assertEqual(tree(r.inbox), before)
        self.assertEqual(r.cli("inspect", r.registration, "reviewer", "a1", status="published"), expected)
        terminal = slot / "event.json"
        original = terminal.rename(slot / "valid-event")
        put(terminal, b'{"version":1', 0o400)
        r.cli("inspect", r.registration, "reviewer", "a1", error=INVALID_EVENT)
        original.replace(terminal)
        artifact = slot / "records/evidence"
        artifact.unlink()
        r.cli("inspect", r.registration, "reviewer", "a1", error=INVALID_EVENT)

    def test_inspect_receipt_mismatch_with_matching_payload_hash(self):
        r = self.r
        r.register(self.session_file)
        slot = r.attempt("reviewer", "inspect-receipt")
        report = r.receipt("inspect-receipt", "approved", candidate_digest="e" * 64)
        records = slot / "records"
        records.mkdir(mode=0o700)
        put(records / "report", report, 0o400)
        put(records / "evidence", r.evidence.read_bytes(), 0o400)
        terminal = dict(r.binding("reviewer", "inspect-receipt"), outcome="approved", report_sha256=sha(report),
                        evidence_sha256=sha(r.evidence.read_bytes()))
        put(slot / "event.json", terminal, 0o400)
        before = tree(r.inbox)
        r.cli("inspect", r.registration, "reviewer", "inspect-receipt", error=RECEIPT)
        self.assertEqual(tree(r.inbox), before)

    def test_actual_write_failure_preserves_existing_records_and_reports_exact_detail(self):
        self.assertNotEqual(os.geteuid(), 0, "This acceptance check requires a non-root owner for the real permission denial")
        r = self.r
        r.register(self.session_file)
        r.attempt("writer", "retained")
        r.publish("writer", "retained", "reported")
        before = tree(r.inbox)
        protected = (tree(r.workspace), tree(r.home), tree(r.target))
        self.assertEqual(stat.S_IMODE(r.inbox.stat().st_mode), 0o700)
        r.inbox.chmod(0o500)
        try:
            self.assertFalse(os.access(r.inbox, os.W_OK), "actual OS write denial was not active")
            result = r.run(CLI, *r.attempt_args("writer", "a1"), "--approve")
            self.assertEqual(tree(r.inbox), before, "failed attempt creation changed existing records or created a slot")
            self.assertEqual(stat.S_IMODE(r.inbox.stat().st_mode), 0o500)
            self.assertEqual((tree(r.workspace), tree(r.home), tree(r.target)), protected)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (1, "", "write-failed: Could not create the private runtime records.\n"),
                             "actual record-creation failure must return the exact technical detail")
        finally:
            r.inbox.chmod(0o700)
        r.attempt("writer", "a1")  # The same request succeeds once the test fixture is writable.

    def test_bounded_private_inputs_and_no_ancestry_escape(self):
        r = self.r
        r.register(self.session_file)
        r.attempt("writer", "a1")
        before = tree(r.inbox)
        sentinel = put(r.root / "outside-sentinel", b"synthetic outside source")
        symlink = r.root / "link"
        symlink.symlink_to(sentinel)
        fifo = r.root / "fifo"
        os.mkfifo(fifo, 0o600)
        for path in (symlink, fifo, put(r.root / "oversize", b"x" * 131_073), put(r.root / "public", b"x", 0o644),
                     put(r.root / "empty", b""), r.root / "missing-report"):
            with self.subTest(path=path.name):
                r.cli(*r.publish_args("writer", "a1", "reported", report=path), "--approve", error=INVALID_PAYLOAD)
                self.assertEqual(tree(r.inbox), before)
        link_dir = r.root / "inbox-link"
        link_dir.symlink_to(r.inbox, target_is_directory=True)
        r.cli("inspect", link_dir / "registration.json", error=UNSAFE)
        self.assertEqual(sentinel.read_bytes(), b"synthetic outside source")
        r.publish("writer", "a1", "reported")

    def test_terminal_link_follows_complete_records_in_real_producer(self):
        r = self.r
        r.register(self.session_file)
        r.attempt("writer", "a1")
        audit = r.root / "publication-order.jsonl"
        result = subprocess.run([sys.executable, "-B", __file__, "--observe-publication", str(audit), str(KIT / CLI),
                                 *map(str, r.publish_args("writer", "a1", "reported")), "--approve"],
                                cwd=r.workspace, env=r.env, umask=0o077, capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = {"event_exists": False, "complete": {"report": sha(r.prose.read_bytes()),
                                                         "evidence": sha(r.evidence.read_bytes())}}
        self.assertEqual(audit.read_bytes(), packed(expected), "event link preceded complete report/evidence")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--confined-exec"]:
        confined_exec(sys.argv[2:])
    elif sys.argv[1:2] == ["--observe-publication"]:
        observe_publication(sys.argv[2:])
    else:
        unittest.main()