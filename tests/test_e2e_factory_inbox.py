"""Actual Pi 1.4.0 PTY and independent local producers, with no real provider calls."""

from __future__ import annotations

import array
import ctypes
import errno
import fcntl
import json
import os
import pty
import re
import stat
import struct
import subprocess
import sys
import termios
import threading
import time
import unittest
from contextlib import ExitStack, contextmanager

from test_factory_inbox import (
    EXISTS,
    EXPIRED,
    INVALID_ATTEMPT,
    INVALID_EVENT,
    INVALID_OUTCOME,
    INVALID_REG,
    INVALID_REQUEST,
    KIT,
    MISSING,
    OUTCOME_CONFLICT,
    RECEIPT,
    SALT,
    UNSAFE,
    Records,
    evidence_dir,
    inbox_origin_window,
    packed,
    plant_inbox_origin_probes,
    put,
    sha,
)

TYPE = "dcc-handoff-v1"
STATE = "dcc-handoff-state-v1"
WRITER = "DCC factory handoff (notification-only): writer reported a candidate. This is not independent acceptance or launch or integration approval."
BLOCKED = "DCC factory handoff (notification-only): writer reported a blocker. This is not independent acceptance or launch or integration approval."
REVIEW = "DCC factory handoff (notification-only): reviewer reported {}. This is not launch, repair or integration approval."
UNSUPPORTED = "unsupported-session: Use an established persistent Pi TUI conversation."
CONFLICT = "conflicting-registration: This conversation is bound to a different registration."
WRONG = "wrong-session: Registration belongs to another conversation."
USAGE = "Use /dcc-handoff enable <absolute-registration>, status, or disable."
INACTIVE = "inactive (notification-only)."
ENABLED = "enabled (notification-only)."
DISABLED = "disabled (notification-only)."
# Allow a complete periodic scan plus margin without using a toast as a clock.
OBSERVATION_SECONDS = 0.75


def until(fn, label, seconds=10):
    stop = time.monotonic() + seconds
    while time.monotonic() < stop:
        value = fn()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError(label)


def rows(path):
    if not path.exists():
        return []
    return [json.loads(row) for row in path.read_bytes().split(b"\n")[:-1] if row]


def snapshot(root):
    """Compare a complete private fixture tree without opening FIFOs or following links."""
    result = {}
    for path in (root, *root.rglob("*")):
        mode = path.lstat().st_mode
        data = path.read_bytes() if stat.S_ISREG(mode) else os.readlink(path) if stat.S_ISLNK(mode) else None
        result[str(path.relative_to(root))] = (mode, data)
    return result


@contextmanager
def filled_fifo(path, payload):
    # Keep a writer open so a faulty nonblocking reader sees the complete payload.
    os.mkfifo(path, 0o600)
    keeper = os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        assert os.write(keeper, payload) == len(payload)
        path.chmod(0o400)

        def queued():
            count = array.array("i", [0])
            fcntl.ioctl(keeper, termios.FIONREAD, count, True)
            return count[0]

        yield queued
    finally:
        os.close(keeper)


@contextmanager
def opened(path):
    """Linux observation of actual open events on a known regular file."""
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "inotify_init1")
    try:
        if libc.inotify_add_watch(fd, os.fsencode(path), 0x20) < 0:  # IN_OPEN
            raise OSError(ctypes.get_errno(), "inotify_add_watch")

        def take():
            try:
                return os.read(fd, 16384)
            except BlockingIOError:
                return b""
        yield take
    finally:
        os.close(fd)


class Terminal:
    def __init__(self, proc, master, screen, before_enable=None):
        self.proc, self.master, self.screen = proc, master, screen
        self.before_enable = before_enable

    def send(self, line):
        offset = len(self.screen)
        os.write(self.master, line.encode() + b"\r")
        return offset

    def detail(self, text, after=0, before=None):
        line = re.compile(rb"(?:^|\r|\n) *(?:Error: |Warning: )?DCC handoff: " + re.escape(text.encode()) + rb" *(?:\r|\n|$)")

        def rendered():
            data = re.sub(rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*\x07)", b"", self.screen[after:before])
            return line.search(data)
        until(rendered, f"missing terminal line {text!r}; pid={self.proc.pid}")

    def barrier(self):
        offset = self.send("/fixture-clear-output")
        until(lambda: b"Fixture diagnostic barrier." in self.screen[offset:], "fixture diagnostic barrier did not repaint")

    def action(self, args):
        self.barrier()
        if self.before_enable and args.startswith("enable "):
            self.before_enable()
            self.before_enable = None
        return self.send(("/dcc-handoff " + args).rstrip())

    def command(self, args, expected):
        self.detail(expected, self.action(args))

    def children(self):
        from pathlib import Path

        return [child for th in Path(f"/proc/{self.proc.pid}/task").glob("*")
                for child in (th / "children").read_text().split()]


class PiFixture(Records):
    def __init__(self, test, root, kit=KIT, launcher=(), **options):
        super().__init__(test, root, kit, launcher, **options)
        self.audit_pi_inbox = False
        if launcher:
            plant_inbox_origin_probes(self.inbox)
        self.agent = root / "agent"
        self.agent.mkdir(mode=0o700)
        self.sessions = root / "sessions"
        self.sessions.mkdir(mode=0o700)
        self.env.update(PI_CODING_AGENT_DIR=str(self.agent), DCC_OFFLINE_FIXTURE=str(root),
                        TERM="xterm-256color", PI_TELEMETRY="0", PI_SKIP_VERSION_CHECK="1")
        # Start from an existing profile that has already seen this Pi version's changelog.
        put(self.agent / "settings.json", {"retry": {"enabled": False, "provider": {"maxRetries": 0}},
                                          "compaction": {"enabled": False}, "cacheWarming": "off", "lastChangelogVersion": "1.4.0"})
        put(self.agent / "auth.json", {})
        put(self.agent / "trust.json", {})
        put(self.agent / "APPEND_SYSTEM.md", b"SYNTHETIC_EXISTING_INSTRUCTIONS\n")
        for parent, files in ((self.workspace / ".dcc", ("workspace.json", "knowledge.json")),
                              (self.workspace / ".pi", ("settings.json", "APPEND_SYSTEM.md"))):
            parent.mkdir()
            for name in files:
                put(parent / name, b"{}\n")
        put(self.target / "source.txt", b"fixture target must not change\n")
        self.phase_log = root / "terminals.jsonl"

    def audit(self, event):
        with self.phase_log.open("ab") as out:
            out.write(packed(dict(event, at_ns=time.time_ns())))

    def transcript(self, session=None):
        return next(iter(self.sessions.rglob(f"*_{session or self.session}.jsonl")), None)

    def transcript_rows(self):
        path = self.transcript()
        return rows(path) if path else []

    def notices(self):
        return [r for r in self.transcript_rows() if r.get("type") == "custom_message" and r.get("customType") == TYPE]

    def states(self):
        return [r["data"] for r in self.transcript_rows() if r.get("type") == "custom" and r.get("customType") == STATE]

    def replies(self):
        return [block["text"] for row in self.transcript_rows() if row.get("type") == "message"
                and row["message"]["role"] == "assistant" for block in row["message"]["content"] if block["type"] == "text"]

    def provider(self):
        return rows(self.root / "provider.jsonl")

    def requests(self):
        return [r for r in self.provider() if r["event"] == "requested" and r["type"] == "custom"]

    def observe_notice(self, expected, text, i):
        until(lambda: len(self.notices()) >= i and len(self.requests()) >= i,
              f"notice/request {i} did not arrive in {self.root}")
        note = self.notices()[i - 1]
        assert note["display"] is True
        self.test.assertEqual(note["content"], text, "delivered notice must use fixed text, never report prose")
        details = {k: v for k, v in expected.items() if k != "report_sha256"}
        self.test.assertEqual(note["details"], dict(details, event=f"{expected['stage']}.{expected['attempt']}",
                              registration=sha(self.registration.read_bytes()), action="notification-only"))
        self.test.assertEqual([r["text"] for r in self.requests()], [r["content"] for r in self.notices()])
        self.test.assertNotIn(SALT, self.transcript().read_text())
        # The fake provider labels its reply from the actual notice content.
        until(lambda: self.replies().count("OFFLINE_CALLBACK_REPLY") >= i, f"callback {i} did not finish in {self.root}")
        return note

    def assert_no_delivery(self, i, reason):
        time.sleep(OBSERVATION_SECONDS)
        self.test.assertEqual((len(self.notices()), len(self.requests())), (i, i), reason)

    def execution_prefix(self):
        return ["unshare", "-Urn", "--", *self.launcher]

    def start_args(self):
        exe = os.environ.get("DCC_PI_EXECUTABLE")
        if not exe or not os.path.isabs(exe):
            raise AssertionError("absolute DCC_PI_EXECUTABLE is required for the actual TUI check")
        return [*self.execution_prefix(), exe, "--offline", "--no-extensions", "--no-tools",
                "--no-mcp", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files", "--no-approve",
                "--tui-mode", "regular", "--model", "dcc-offline-fixture/deterministic", "--session-dir", str(self.sessions),
                "-e", str(self.kit / "tests/fixtures/factory-inbox-provider.ts"), "-e", str(self.kit / "extensions/factory-inbox.ts")]

    def run(self, script, *args):
        if getattr(self, "audit_pi_inbox", False):
            raise AssertionError("Producer and Pi inbox origin observation windows must not overlap")
        return super().run(script, *args)

    @contextmanager
    def terminal(self, phase, *, session=None, resume=None, ephemeral=False):
        args = self.start_args()
        if ephemeral:
            args.append("--no-session")
        elif resume:
            args.extend(("--session", str(resume)))
        else:
            args.extend(("--session-id", session or self.session))
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 200, 0, 0))
        proc = subprocess.Popen(args, cwd=self.workspace, env=self.env, stdin=slave, stdout=slave, stderr=slave,
                                start_new_session=True, umask=0o077)
        os.close(slave)
        screen = bytearray()
        self.audit({"event": "launch", "phase": phase, "pid": proc.pid, "argv": args})

        def drain():
            with (self.root / f"{phase}.ansi").open("xb", buffering=0) as log:
                while True:
                    try:
                        part = os.read(master, 8192)
                    except OSError as exc:
                        if exc.errno not in (errno.EBADF, errno.EIO):
                            raise
                        break
                    if not part:
                        break
                    log.write(part)
                    screen.extend(part)

        thread = threading.Thread(target=drain, daemon=True)
        thread.start()
        try:
            until(lambda: b"factory-inbox-provider.ts" in screen, f"Pi TUI didn't start: {phase}, {self.root}")
            with ExitStack() as origin:
                def before_enable():
                    # The archive scenario has finished production. Through shutdown,
                    # the parent reads only registration metadata for its notice assertion.
                    protocol = {"registration.json", "writer.a1/attempt.json", "writer.a1/event.json",
                                "writer.a1/records/report", "writer.a1/records/evidence"}
                    origin.enter_context(inbox_origin_window(self.test, self.inbox, "Pi enable through shutdown",
                                                             allowed=protocol, required=protocol - {"registration.json"}))
                    self.audit_pi_inbox = True

                yield Terminal(proc, master, screen, before_enable if self.launcher else None)
                os.write(master, b"\x04")
                rc = proc.wait(timeout=6)
                self.audit({"event": "clean-exit", "phase": phase, "pid": proc.pid, "exit": rc})
                self.test.assertEqual(rc, 0, bytes(screen[-2000:]))
        finally:
            self.audit_pi_inbox = False
            if proc.poll() is None:
                # Only the fixture process this test created, after a failed assertion.
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
            thread.join(timeout=2)
            os.close(master)

    def establish(self, tty, session=None):
        offset = tty.send("Establish the disposable conversation.")
        until(lambda: b"OFFLINE_PLANNING_REPLY" in tty.screen[offset:] and self.transcript(session),
              f"session was not persisted in {self.root}")
        return self.transcript(session)

    def protected(self):
        return {name: snapshot(getattr(self, name)) for name in ("workspace", "home", "target", "agent")}

    def assert_preserving_disable(self, tty, expected, worker):
        tty.barrier()
        records, protected = snapshot(self.inbox), self.protected()
        offset = tty.send("/dcc-handoff disable")
        time.sleep(OBSERVATION_SECONDS)
        self.test.assertEqual(snapshot(self.inbox), records, "disable changed the pre-disable record tree")
        self.test.assertEqual(self.protected(), protected, "disable changed protected files or added new paths")
        self.test.assertIsNone(worker.poll(), "disable stopped the independently started harmless worker")
        if expected == DISABLED:
            self.test.assertIs(self.states()[-1]["enabled"], False, "disable did not persist disabled state")
        else:
            self.test.assertEqual(self.states(), [], "inactive disable persisted an opt-in record")
        tty.detail(expected, offset)
        return records

    def assert_offline_effects(self):
        starts = [r for r in self.provider() if r["event"] == "provider-start"]
        self.test.assertTrue(starts)
        self.test.assertEqual({(r["provider"], r["model"]) for r in starts}, {("dcc-offline-fixture", "deterministic")})
        self.test.assertNotIn("unexpected-tool", {r["event"] for r in self.provider()})
        self.test.assertFalse(any(r.get("message", {}).get("role") == "toolResult" for r in self.transcript_rows()))


class InboxE2E(unittest.TestCase):
    def fixture(self):
        return PiFixture(self, evidence_dir("handoff-tui-"))

    def test_explicit_opt_in_commands_and_disabled_resume_preserve_worker_and_records(self):
        r = self.fixture()
        before = r.protected()
        with subprocess.Popen([sys.executable, "-B", "-c", "import time; print('worker-alive', flush=True); time.sleep(60)"],
                              cwd=r.target, env=r.env, stdout=subprocess.PIPE, text=True) as worker:
            try:
                assert worker.stdout is not None
                self.assertEqual(worker.stdout.readline(), "worker-alive\n")
                r.audit({"event": "dummy-worker-start", "pid": worker.pid})
                with r.terminal("initial") as tty:
                    tty.command("enable " + str(r.registration), UNSUPPORTED)
                    transcript = r.establish(tty)
                    stable = r.protected()
                    # Pi creates its model registry at startup. The transcript sits in
                    # the separate sessions tree; no protected tree exclusions after startup.
                    expected_agent = before["agent"] | {"models-store.json": (stat.S_IFREG | 0o600, b"{}")}
                    self.assertEqual(stable, before | {"agent": expected_agent})
                    tty.command("help", USAGE)
                    tty.command("", USAGE)
                    tty.command("unknown", USAGE)
                    tty.command("status arg", USAGE)
                    tty.command("disable arg", USAGE)
                    tty.command("enable", USAGE)
                    tty.command("status", INACTIVE)
                    r.assert_preserving_disable(tty, INACTIVE, worker)
                    tty.command("enable relative", UNSAFE)
                    tty.command("enable " + str(r.registration), MISSING)
                    put(r.registration, b"{", 0o400)
                    tty.command("enable " + str(r.registration), INVALID_REG)
                    r.registration.unlink()
                    r.register(transcript)
                    r.attempt("writer", "a1")
                    expected = r.publish("writer", "a1", "reported")
                    initial = snapshot(r.inbox)
                    with opened(r.registration) as access:
                        tty.command("status", INACTIVE)
                        time.sleep(0.65)
                        self.assertFalse(access(), "registration was opened without opt-in")
                    self.assertEqual((r.notices(), r.requests(), r.states(), snapshot(r.inbox)), ([], [], [], initial))
                    self.assertEqual(r.protected(), stable)
                    offset = tty.action("enable " + str(r.registration))
                    r.observe_notice(expected, WRITER, 1)
                    self.assertEqual(r.protected(), stable, "enable/callback changed protected files or added new paths")
                    tty.detail(ENABLED, offset)
                    tty.command("enable " + str(r.registration), ENABLED)
                    tty.command("status", ENABLED)
                    tty.command("enable /different/root/registration.json", CONFLICT)
                    self.assertEqual(r.states(), [{"session": r.session, "file": str(transcript), "registration": str(r.registration),
                                                  "enabled": True, "hash": sha(r.registration.read_bytes())}])
                    saved_a1 = r.assert_preserving_disable(tty, DISABLED, worker)
                    r.attempt("writer", "a2")
                    blocked = r.publish("writer", "a2", "blocked")
                    saved = snapshot(r.inbox)
                    self.assertEqual({name: saved[name] for name in saved_a1}, saved_a1)
                    with opened(r.registration) as access:
                        tty.command("status", DISABLED)
                        time.sleep(0.65)
                        self.assertFalse(access(), "disabled runtime still reads the registration")
                    self.assertEqual((len(r.notices()), len(r.requests()), snapshot(r.inbox)), (1, 1, saved))
                    self.assertEqual([s["enabled"] for s in r.states()], [True, False])
                    self.assertIsNone(worker.poll())
                    self.assertEqual(tty.children(), [])
                with r.terminal("disabled-resume", resume=transcript) as tty, opened(r.registration) as access:
                    offset = tty.action("status")
                    r.assert_no_delivery(1, "disabled resume delivered a pending event")
                    self.assertFalse(access(), "disabled resume read the registration")
                    self.assertEqual(snapshot(r.inbox), saved)
                    self.assertEqual(r.protected(), stable)
                    tty.detail(DISABLED, offset)
                    offset = tty.action("enable " + str(r.registration))
                    r.observe_notice(blocked, BLOCKED, 2)
                    self.assertEqual(r.protected(), stable, "re-enable/callback changed protected files or added new paths")
                    tty.detail(ENABLED, offset)
                    self.assertEqual(r.assert_preserving_disable(tty, DISABLED, worker), saved)
                self.assertIsNone(worker.poll())
                self.assertEqual(snapshot(r.inbox), saved)
                self.assertEqual(r.protected(), stable)
                r.assert_offline_effects()
            finally:
                if worker.poll() is None:
                    worker.terminate()
                    worker.wait(timeout=3)

    def test_receipt_derived_publications_deliver_once_and_refusals_deliver_nothing(self):
        r = self.fixture()
        with r.terminal("receipt-derived") as tty:
            transcript = r.establish(tty)
            r.register(transcript)
            tty.command("enable " + str(r.registration), ENABLED)

            for i, (attempt, verdict) in enumerate((("a1", "approved"), ("a2", "changes_requested"), ("a3", "blocked")), start=1):
                r.attempt("reviewer", attempt)
                expected = r.publish("reviewer", attempt, verdict, derive=True)
                r.observe_notice(expected, REVIEW.format(verdict), i)

            def refuse(stage, attempt, outcome, report, error, *, exit_code=1):
                before = snapshot(r.inbox)
                sources = (report.read_bytes(), r.evidence.read_bytes())
                r.cli(*r.publish_args(stage, attempt, outcome, report=report), "--approve", error=error, exit_code=exit_code)
                r.assert_no_delivery(3, error)
                self.assertEqual(snapshot(r.inbox), before)
                self.assertEqual((report.read_bytes(), r.evidence.read_bytes()), sources)

            r.attempt("writer", "missing-outcome")
            refuse("writer", "missing-outcome", None, r.prose, INVALID_REQUEST, exit_code=2)
            duplicate = put(r.root / "duplicate.receipt", r.receipt("a1", "blocked"))
            refuse("reviewer", "a1", "blocked", duplicate, EXISTS)

            approved = put(r.root / "approved.receipt", r.receipt("a4", "approved"))
            refuse("reviewer", "a4", None, approved, INVALID_ATTEMPT)
            r.attempt("reviewer", "a4")
            refuse("reviewer", "a4", "reported", approved, INVALID_OUTCOME)
            unsupported = put(r.root / "unsupported.receipt", r.receipt("a4", "reported"))
            refuse("reviewer", "a4", None, unsupported, INVALID_OUTCOME)
            refuse("reviewer", "a4", "blocked", approved, OUTCOME_CONFLICT)
            misbound = put(r.root / "misbound.receipt", r.receipt("a4", "approved", candidate_digest="0" * 64))
            refuse("reviewer", "a4", None, misbound, RECEIPT)
            expected = r.publish("reviewer", "a4", "approved", report=approved)
            r.observe_notice(expected, REVIEW.format("approved"), 4)
            r.assert_no_delivery(4, "corrected publication delivered more than once")
            self.assertEqual(r.replies(), ["OFFLINE_PLANNING_REPLY"] + ["OFFLINE_CALLBACK_REPLY"] * 4)
            self.assertEqual(tty.children(), [])
        r.assert_offline_effects()

    def test_held_planning_turn_delivers_writer_and_reviewer_after_settlement(self):
        r = self.fixture()
        with r.terminal("busy") as tty:
            transcript = r.establish(tty)
            r.register(transcript)
            r.attempt("writer", "a1")
            r.attempt("reviewer", "a1")
            tty.command("enable " + str(r.registration), ENABLED)
            tty.barrier()
            start = len(r.provider())
            offset = tty.send("HOLD_THIS_PLANNING_TURN")
            until(lambda: any(row.get("hold") for row in r.provider()[start:]), "provider did not enter barrier")
            review = r.publish("reviewer", "a1", "approved")
            writer = r.publish("writer", "a1", "reported")
            time.sleep(OBSERVATION_SECONDS)
            end = len(tty.screen)
            held = r.provider()[start:]
            activity = (r.notices(), r.requests(), r.replies(), tty.children())
            self.assertEqual([row for row in held if row["event"] == "provider-reply"], [],
                             "held planning provider completed or was interrupted before release")
            self.assertEqual(activity, ([], [], ["OFFLINE_PLANNING_REPLY"], []), "callback activity before planning release")
            r.audit({"event": "release-planning", "phase": "busy"})
            put(r.root / "release", b"finish\n")
            until(lambda: len(r.notices()) >= 2 and len(r.replies()) >= 4,
                  "planning and the two post-release deliveries did not finish")
            result = [(row.get("message", {}).get("role"), row.get("content"),
                       [b.get("text") for b in row.get("message", {}).get("content", []) if isinstance(b, dict)])
                      for row in r.transcript_rows() if row.get("type") == "custom_message"
                      or row.get("message", {}).get("role") == "assistant"]
            self.assertEqual(result, [("assistant", None, ["OFFLINE_PLANNING_REPLY"]),
                                      ("assistant", None, ["OFFLINE_PLANNING_REPLY"]),
                                      (None, REVIEW.format("approved"), []), ("assistant", None, ["OFFLINE_CALLBACK_REPLY"]),
                                      (None, WRITER, []), ("assistant", None, ["OFFLINE_CALLBACK_REPLY"])],
                             "planning must finish before either notice, then callback turns must alternate")
            # before_agent_start traces each new custom turn. A provider reply to
            # a message steered into the planning run is not a new callback turn.
            trace = [row.get("text", row["type"] if "type" in row else row["event"])
                     for row in r.provider()[start:] if row["event"] in {"requested", "provider-reply"}]
            self.assertEqual(trace, ["user", "OFFLINE_PLANNING_REPLY", REVIEW.format("approved"), "OFFLINE_CALLBACK_REPLY",
                                     WRITER, "OFFLINE_CALLBACK_REPLY"], "both callbacks must start distinct post-planning turns")
            r.observe_notice(review, REVIEW.format("approved"), 1)
            r.observe_notice(writer, WRITER, 2)
            self.assertEqual(tty.children(), [])
            tty.detail("deferred-busy.", offset, end)
        self.assertEqual([p["exit"] for p in rows(r.phase_log) if p["event"] == "clean-exit"], [0])
        r.assert_offline_effects()

    def test_clean_resume_retained_replayed_and_offline_backlog(self):
        r = self.fixture()
        with r.terminal("one") as tty:
            transcript = r.establish(tty)
            r.register(transcript)
            first_slot = r.attempt("reviewer", "a1")
            tty.command("enable " + str(r.registration), ENABLED)
            first = r.publish("reviewer", "a1", "approved")
            first_notice = r.observe_notice(first, REVIEW.format("approved"), 1)
        with r.terminal("two", resume=transcript) as tty:
            until(lambda: b"DCC handoff: duplicate." in tty.screen or len(r.notices()) > 1,
                  "resumed adapter did not inspect retained A1")
            self.assertEqual(r.notices(), [first_notice], "retained A1 was delivered a second time on resume")
            tty.detail("duplicate.")
            self.assertEqual(len(r.requests()), 1)
        event = first_slot / "event.json"
        old = event.rename(first_slot / "retained-a1")
        put(event, old.read_bytes(), 0o400)
        self.assertNotEqual(event.stat().st_ino, old.stat().st_ino)
        r.attempt("reviewer", "a2")
        second = r.publish("reviewer", "a2", "changes_requested")
        self.assertEqual(r.notices(), [first_notice])
        with r.terminal("three", resume=transcript) as tty:
            tty.detail("duplicate.")
            second_notice = r.observe_notice(second, REVIEW.format("changes_requested"), 2)
            self.assertEqual(r.notices(), [first_notice, second_notice])
        event = r.inbox / "reviewer.a2/event.json"
        old = event.rename(event.with_name("retained-a2"))
        put(event, old.read_bytes(), 0o400)
        self.assertNotEqual(event.stat().st_ino, old.stat().st_ino)
        with r.terminal("four", resume=transcript) as tty:
            tty.detail("duplicate.")
            time.sleep(0.65)
            self.assertEqual((r.notices(), len(r.requests())), ([first_notice, second_notice], 2))
        launches = rows(r.phase_log)[::2]
        self.assertEqual(len({p["pid"] for p in launches}), 4)
        phases = rows(r.phase_log)
        self.assertEqual([p["exit"] for p in phases if p["event"] == "clean-exit"], [0, 0, 0, 0])
        publish_a2 = next(row for row in rows(r.root / "producer-processes.jsonl") if "publish" in row["argv"] and "a2" in row["argv"])
        self.assertLess(phases[3]["at_ns"], publish_a2["at_ns"])
        self.assertLess(publish_a2["at_ns"], phases[4]["at_ns"])
        self.assertEqual(r.transcript(), transcript)
        r.assert_offline_effects()

    def test_wrong_session_ephemeral_print_and_expired_resume(self):
        r = self.fixture()
        with r.terminal("original") as tty:
            transcript = r.establish(tty)
            r.expires = int(time.time() * 1000) + 2600
            r.register(transcript)
            tty.command("enable " + str(r.registration), ENABLED)
        with r.terminal("unrelated", session="new-conversation") as tty:
            r.establish(tty, "new-conversation")
            tty.command("status", INACTIVE)
            tty.command("enable " + str(r.registration), WRONG)
        with r.terminal("ephemeral", ephemeral=True) as tty:
            for arg in ("enable " + str(r.registration), "status", "disable"):
                tty.command(arg, UNSUPPORTED)
        until(lambda: int(time.time() * 1000) > r.expires, "fixture did not expire")
        with r.terminal("expired", resume=transcript) as tty:
            tty.detail(EXPIRED)
            tty.command("status", EXPIRED)
            tty.command("enable " + str(r.registration), EXPIRED)
        result = subprocess.run([*r.start_args(), "--print", "Offline non-TUI prompt", "--session", str(transcript)],
                                cwd=r.workspace, env=r.env, umask=0o077, capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "OFFLINE_PLANNING_REPLY")
        self.assertEqual((r.notices(), r.requests()), ([], []))
        self.assertEqual([state["enabled"] for state in r.states()], [True])

    def test_context_id_and_transcript_path_independently_gate_opt_in(self):
        for field in ("session", "session_file"):
            with self.subTest(context_field=field):
                r = self.fixture()
                with r.terminal(f"wrong-{field}") as tty:
                    transcript = r.establish(tty)
                    r.register(transcript)
                    slot = r.attempt("writer", "a1")
                    valid = r.publish("writer", "a1", "reported")
                    registration = r.job_record(transcript)
                    records = {r.registration: registration}
                    if field == "session":
                        # Keep the job/attempt/event internally consistent. Only the
                        # session ID comparison against the running Pi context is wrong.
                        value = "another-valid-session"
                        records[slot / "attempt.json"] = r.binding("writer", "a1")
                        records[slot / "event.json"] = valid
                    else:
                        # Same session ID in a second real private transcript path.
                        value = str(put(r.sessions / "other-transcript.jsonl", transcript.read_bytes()))
                    for path, data in records.items():
                        replacement = put(r.root / "replace-record", data | {field: value}, 0o400)
                        replacement.replace(path)
                    before = snapshot(r.inbox)
                    offset = tty.action("enable " + str(r.registration))
                    time.sleep(OBSERVATION_SECONDS)
                    self.assertEqual((r.states(), r.notices(), r.requests()), ([], [], []),
                                     f"actual {field} mismatch activated a pending bound event")
                    self.assertEqual(snapshot(r.inbox), before)
                    tty.detail(WRONG, offset)
                    for path, data in records.items():
                        replacement = put(r.root / "replace-record", data, 0o400)
                        replacement.replace(path)
                    offset = tty.action("enable " + str(r.registration))
                    r.observe_notice(valid, WRITER, 1)
                    self.assertEqual(r.states(), [{"session": r.session, "file": str(transcript),
                                                  "registration": str(r.registration), "enabled": True,
                                                  "hash": sha(packed(registration))}])
                    tty.detail(ENABLED, offset)
                r.assert_offline_effects()

    def test_reload_and_session_replacement_stop_old_reads(self):
        r = self.fixture()
        with r.terminal("reload") as tty:
            transcript = r.establish(tty)
            r.register(transcript)
            tty.command("enable " + str(r.registration), ENABLED)
            tty.send("/reload")
            until(lambda: sum(p["event"] == "session-start" and p["session"] == r.session for p in r.provider()) == 2,
                  "replacement extension runtime never started on reload")
            tty.command("status", ENABLED)
            tty.send("/new")
            until(lambda: any(p["event"] == "session-start" and p["session"] != r.session for p in r.provider()),
                  "session replacement did not complete")
            with opened(r.registration) as access:
                tty.send("Establish replacement session.")
                time.sleep(1.2)
                self.assertFalse(access(), "old session still reads inbox after replacement")
            tty.command("status", INACTIVE)
        self.assertEqual(sum(p["event"] == "session-shutdown" for p in r.provider()), 3)
        self.assertEqual((r.notices(), r.requests()), ([], []))

    def test_replaced_registration_and_bounded_inbox_stop_notifications(self):
        r = self.fixture()
        with r.terminal("registration-conflict") as tty:
            transcript = r.establish(tty)
            r.register(transcript)
            tty.command("enable " + str(r.registration), ENABLED)
            saved = r.registration.rename(r.root / "saved-registration")
            put(r.registration, r.job_record(transcript) | {"expires_ms": r.expires + 20_000}, 0o400)
            tty.command("enable " + str(r.registration), CONFLICT)
            time.sleep(0.6)  # Let the armed scan independently detect the replaced registration.
            tty.command("status", CONFLICT)
            self.assertEqual((r.notices(), r.requests()), ([], []))
            r.registration.unlink()
            saved.rename(r.registration)
            tty.command("enable " + str(r.registration), ENABLED)
            for i in range(256):
                put(r.inbox / f"filler-{i:03}", b"fixture only")
            detail = "invalid-inbox: Cannot scan the private inbox within its limits."
            tty.detail(detail)
            tty.command("status", detail)
            self.assertEqual((r.notices(), r.requests()), ([], []))

    def test_scan_and_status_report_missing_or_invalid_enabled_registration(self):
        r = self.fixture()
        with r.terminal("registration-lost") as tty:
            transcript = r.establish(tty)
            r.register(transcript)
            tty.command("enable " + str(r.registration), ENABLED)
            saved = r.root / "original-registration"
            for detail, invalid in ((MISSING, None), (INVALID_REG, b"{broken")):
                with self.subTest(detail=detail):
                    tty.barrier()
                    offset = len(tty.screen)
                    if invalid is None:
                        r.registration.rename(saved)
                    else:
                        # Replace atomically so the watcher sees malformed input, not an absent file.
                        invalid_file = put(r.root / "malformed-registration", invalid, 0o400)
                        invalid_file.replace(r.registration)
                    tty.detail(detail, offset)
                    tty.command("status", detail)
                    self.assertEqual((r.notices(), r.requests()), ([], []))
                    restored = put(r.root / "restored-registration", saved.read_bytes(), 0o400)
                    restored.replace(r.registration)
                    tty.command("enable " + str(r.registration), ENABLED)
            self.assertEqual(len(r.states()), 1, "recovering the same identity must not create a second opt-in")

    def test_bad_attempt_schema_rejects_then_delivers_same_attempt(self):
        self.check_schema_rejection_then_recovery("attempt.json", INVALID_ATTEMPT)

    def test_bad_event_schema_rejects_then_delivers_same_attempt(self):
        self.check_schema_rejection_then_recovery("event.json", INVALID_EVENT)

    def check_schema_rejection_then_recovery(self, record, detail):
        r = self.fixture()
        with r.terminal(f"schema-{record}") as tty:
            transcript = r.establish(tty)
            r.register(transcript)
            cases = [("version", 2), ("version", "1"), ("version", True), ("missing-version", None),
                     ("extra-field", "fixture-only"), ("job", [r.job]), ("candidate_digest", 0),
                     ("duplicate-version", None), ("array-root", None)]
            if record == "event.json":
                cases.extend([("outcome", ["reported"]), ("evidence_sha256", False)])
            for i, (field, value) in enumerate(cases):
                with self.subTest(record=record, field=field, value=value):
                    self.schema_probe(r, tty, i, record, detail, field, value)
            self.assertEqual(len(r.notices()), len(cases))
            self.assertEqual(len(r.requests()), len(cases))
            self.assertEqual(tty.children(), [])
        r.assert_offline_effects()

    def schema_probe(self, r, tty, i, record, detail, field, value):
        # Publish normally before arming the scan; change exactly one wire record in the fixture.
        attempt = f"schema-{i:02}"
        slot = r.attempt("writer", attempt)
        terminal = r.publish("writer", attempt, "reported")
        path = slot / record
        original = path.rename(slot / "valid-record")
        row = json.loads(original.read_bytes())
        if field == "missing-version":
            del row["version"]
        elif field not in ("duplicate-version", "array-root"):
            row[field] = value
        bad = packed(row)
        if field == "duplicate-version":
            bad = b'{"version":2,' + bad[1:]
        elif field == "array-root":
            bad = b"[" + bad.rstrip(b"\n") + b"]\n"
        put(path, bad, 0o400)
        before = snapshot(r.inbox)
        offset = tty.action("enable " + str(r.registration))
        r.assert_no_delivery(i, f"actual consumer delivered malformed {record} ({field}={value!r})")
        self.assertEqual(snapshot(r.inbox), before)
        tty.detail(ENABLED, offset)
        tty.detail(detail, offset)
        rejected = slot / "rejected-record"
        path.rename(rejected)
        original.rename(path)
        self.assertEqual(rejected.read_bytes(), bad)
        r.observe_notice(terminal, WRITER, i + 1)
        self.assertEqual(r.notices()[-1]["details"]["event"], f"writer.{attempt}")
        tty.command("disable", DISABLED)

    def test_actual_rejected_bindings_files_and_receipt_detail_then_valid_same_attempt(self):
        r = self.fixture()
        with r.terminal("rejections") as tty:
            transcript = r.establish(tty)
            r.register(transcript)
            tty.command("enable " + str(r.registration), ENABLED)
            cases = [("job", "OTHER"), ("session", "elsewhere"), ("stage", "writer"), ("attempt", "other"),
                     ("manifest_digest", "a" * 64), ("candidate_digest", "b" * 64), ("evidence_sha256", "c" * 64),
                     ("report_sha256", "d" * 64), ("command", SALT), ("path", "../no"), ("outcome", "unexpected"),
                     ("receipt", None), ("registration", None), ("missing-records", None), ("partial-event", None),
                     ("fifo", None), ("symlink", None), ("public", None), ("oversize", None), ("ancestor", None)]
            for i, (field, value) in enumerate(cases):
                with self.subTest(field=field):
                    self.reject_then_accept(r, tty, i, field, value)
            self.assertEqual(len(r.notices()), len(cases))
            self.assertEqual(len(r.requests()), len(cases))
            self.assertEqual(tty.children(), [])
        r.assert_offline_effects()

    def reject_then_accept(self, r, tty, i, field, value):
        attempt = f"probe-{i:02}"
        slot = r.attempt("reviewer", attempt)
        binding = r.binding("reviewer", attempt)
        report = r.receipt(attempt, "blocked", **({"candidate_digest": "0" * 64} if field == "receipt" else {}))
        evidence = b"x" * 131_073 if field == "oversize" else r.evidence.read_bytes()
        event = dict(binding, outcome="blocked", report_sha256=sha(report), evidence_sha256=sha(evidence))
        if value is not None:
            event[field] = value
        records = slot / "records"
        records.mkdir(mode=0o700)
        report_path = put(records / "report", report, 0o400)
        sentinel = put(r.root / f"unrelated-{i}", evidence, 0o400)
        evidence_path = records / "evidence"
        if field == "symlink":
            evidence_path.symlink_to(sentinel)
        elif field not in ("missing-records", "fifo"):
            put(evidence_path, evidence, 0o444 if field == "public" else 0o400)
        if field == "registration":
            (slot / "attempt.json").rename(slot / "retained-attempt")
        if field == "ancestor":
            records.rename(slot / "outside")
            records.symlink_to(slot / "outside", target_is_directory=True)
        detail = INVALID_ATTEMPT if field == "registration" else RECEIPT if field == "receipt" else INVALID_EVENT
        tty.barrier()
        with ExitStack() as fixtures:
            access = fixtures.enter_context(opened(sentinel))
            if field == "fifo":
                queued = fixtures.enter_context(filled_fifo(evidence_path, evidence))
                info = evidence_path.lstat()
                self.assertTrue(stat.S_ISFIFO(info.st_mode))
                self.assertEqual((info.st_uid, stat.S_IMODE(info.st_mode), queued(), event["evidence_sha256"]),
                                 (os.getuid(), 0o400, len(evidence), sha(evidence)))
            if field == "oversize":
                info = evidence_path.lstat()
                self.assertTrue(stat.S_ISREG(info.st_mode))
                self.assertEqual((info.st_uid, stat.S_IMODE(info.st_mode), info.st_size, event["evidence_sha256"]),
                                 (os.getuid(), 0o400, 131_073, sha(evidence_path.read_bytes())))
            pending = put(slot / "pending-event", b"{\"version\":1" if field == "partial-event" else event, 0o400)
            before = snapshot(r.inbox)
            before[str((slot / "event.json").relative_to(r.inbox))] = before.pop(str(pending.relative_to(r.inbox)))
            offset = len(tty.screen)
            pending.rename(slot / "event.json")
            r.assert_no_delivery(i, f"actual consumer delivered rejected input: {field}")
            self.assertFalse(access(), "consumer opened the outside sentinel")
            self.assertEqual(snapshot(r.inbox), before, f"consumer modified rejected records: {field}")
            if field == "fifo":
                self.assertEqual(queued(), len(evidence), "rejection drained the valid FIFO bytes")
            tty.detail(detail, offset)
        (slot / "event.json").rename(slot / "rejected-event")
        if field == "registration":
            (slot / "retained-attempt").rename(slot / "attempt.json")
        if field == "ancestor":
            records.unlink()
        else:
            report_path.rename(slot / "rejected-report")
            if field != "missing-records":
                evidence_path.rename(slot / "rejected-evidence")
            records.rmdir()
        valid = r.publish("reviewer", attempt, "blocked")
        r.observe_notice(valid, REVIEW.format("blocked"), i + 1)


if __name__ == "__main__":
    unittest.main()