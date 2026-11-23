"""Real Git, Pi 1.4.0 and Herdr 0.9.1 fixtures for the coordinator-invoked loop.

Deterministic providers emit fixed text only; the fixture applies the benign
candidate edit after dispatch. Listener readiness uses the shipped extension's
persisted enabled-state schema; the manual fixture path is a separate approved
exception. No service, credential or real user data is used.
"""

from __future__ import annotations

import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path

from test_factory_inbox import evidence_dir

KIT = Path(__file__).resolve().parents[1]
PI_EXE = os.environ.get("DCC_PI_EXECUTABLE", "")
HERDR_EXE = os.environ.get("DCC_HERDR_EXECUTABLE", "")
SESSION = "fixture-session"
STATE = "dcc-handoff-state-v1"


def packed(row) -> bytes:
    return (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def put(path: Path, data, mode: int = 0o600) -> Path:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
        handle.write(packed(data) if isinstance(data, dict) else data)
    path.chmod(mode)
    return path


def rewrite(path: Path, data, mode: int = 0o644) -> Path:
    path.write_bytes(packed(data) if isinstance(data, dict) else data)
    path.chmod(mode)
    return path


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {result.stderr}")
    return result.stdout


def wait_for(predicate, label, seconds=20):
    stop = time.monotonic() + seconds
    while time.monotonic() < stop:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(label)


class LoopFixture:
    def __init__(self, test: unittest.TestCase, *, staged: bool = False):
        self.test = test
        self.staged = staged
        self.root = evidence_dir("factory-run-")
        self.xdg = Path(tempfile.mkdtemp(prefix="dccr-", dir="/tmp"))
        self.inbox = self.root / "inbox"
        self.repo = self.root / "repo"
        self.home = self.root / "home"
        self.agent = self.root / "agent"
        self.agent_env = self.root / "agent-decoy"
        self.sessions = self.root / "sessions"
        self.workspace = self.root / "workspace"
        self.state_dir = self.root / "state"
        for path in (self.inbox, self.repo, self.home, self.agent, self.agent_env, self.sessions,
                     self.workspace, self.state_dir):
            path.mkdir(mode=0o700)
        (self.xdg / "herdr").mkdir(parents=True)
        rewrite(self.xdg / "herdr" / "config.toml",
                b"onboarding = false\n[update]\nversion_check = false\nmanifest_check = false\n")
        for name, value in (("settings.json", {"retry": {"enabled": False, "provider": {"maxRetries": 0}},
                                               "compaction": {"enabled": False}, "cacheWarming": "off",
                                               "lastChangelogVersion": "1.4.0"}),
                            ("auth.json", {}), ("trust.json", {})):
            put(self.agent / name, value)
            put(self.agent_env / name, value)
        self.env = {key: os.environ[key] for key in ("PATH", "LANG") if key in os.environ}
        self.env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.xdg),
                        PI_CODING_AGENT_DIR=str(self.agent_env), DCC_RUN_FIXTURE=str(self.root),
                        PI_OFFLINE="1", PI_TELEMETRY="0", PI_SKIP_VERSION_CHECK="1",
                        PYTHONDONTWRITEBYTECODE="1", TERM="xterm-256color", TMPDIR=str(self.root))
        for key in ("HERDR_SOCKET_PATH", "HERDR_ENV", "HERDR_PANE_ID", "HERDR_TAB_ID", "HERDR_WORKSPACE_ID"):
            self.env.pop(key, None)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "fixture@example.invalid")
        git(self.repo, "config", "user.name", "Fixture")
        put(self.repo / "file.txt", b"base\n")
        put(self.repo / "AGENTS.md", b"fixture target rules\n")
        git(self.repo, "add", "file.txt", "AGENTS.md")
        git(self.repo, "commit", "-qm", "base")
        if staged:
            rewrite(self.repo / "file.txt", b"staged baseline bytes\n", 0o755)
            put(self.repo / "baseline-marker.txt", b"approved staged marker\n")
            rewrite(self.repo / "AGENTS.md", b"fixture target rules\nstaged target instruction\n")
            git(self.repo, "add", "file.txt", "baseline-marker.txt", "AGENTS.md")
        self.session_file = put(self.sessions / "fixture.jsonl",
                                {"type": "session", "version": 3, "id": SESSION, "cwd": str(self.workspace)})
        self.plan = self.state_dir / "plan.json"
        self.state = self.state_dir / "state.json"
        self.writer = self.root / "writer"
        self.reviewer = self.root / "reviewer"
        self.manifest_file = self.root / "manifest.json"
        self.brief = self.root / "brief.md"
        self.manifest = self.make_manifest()
        self.registration = self.inbox / "registration.json"
        self.expires = int(time.time() * 1000) + 600_000
        self.server: subprocess.Popen | None = None
        self.herdr_session = ""

    def make_manifest(self) -> dict:
        base = json.loads(self.cli("scripts/factory-job.py", "example", check=True).stdout)
        base.update(
            task={"id": "FIXTURE-B4", "goal": "Synthetic benign edit reviewed then staged exactly"},
            repo=str(self.repo), allowed_paths=["file.txt", "new.txt", "baseline-marker.txt"], frozen={},
            tier={"id": "B", "reason": "runtime loop"},
            verification=[f"git -C {self.repo} rev-parse HEAD"],
            evidence="fixture evidence", out_of_scope=["anything outside the allowlist"],
            budgets={"writer": {"minutes": 30, "calls": 20}, "reviewer": {"minutes": 30, "calls": 20}},
            writer={"worktree": str(self.writer), "model": "deepseek/deepseek-flash"})
        base["decisions"] = [{"id": "D1", "source": "fixture approved decision"}]
        base["acceptance"] = [{"id": "C1", "source": "D1", "input": "fixture", "action": "launch",
                               "expected": "exact staged handoff", "observation": "git index and bytes"}]
        base["guards"] = [{"id": "G1", "decisions": ["D1"], "command": f"git -C {self.repo} rev-parse HEAD",
                           "boundary": "real Git index", "mutation": "unapproved dispatch",
                           "expected_failure": "refused", "limits": "local sequential operator"}]
        sys.path.insert(0, str(KIT / "scripts/lib"))
        import factory_contract as contract
        base["base"] = contract.capture_baseline(self.repo)
        put(self.manifest_file, base)
        rewrite(self.brief, self.cli("scripts/factory-job.py", "render", self.manifest_file, check=True).stdout.encode())
        return base

    def cli(self, script: str, *args: object, check: bool = False, timeout: int = 240):
        argv = [sys.executable, "-B", str(KIT / script), *map(str, args)]
        result = subprocess.run(argv, cwd=self.workspace, env=self.env, capture_output=True,
                                text=True, timeout=timeout, check=False)
        if check and result.returncode != 0:
            raise AssertionError(f"{script} {' '.join(map(str, args))}: {result.stderr}{result.stdout}")
        return result

    def loop(self, *args: object, check: bool = False):
        return self.cli("scripts/factory-run.py", *args, check=check)

    def register(self) -> None:
        self.cli("scripts/factory-inbox.py", "register", "job", self.inbox, "--manifest", self.manifest_file,
                 "--session", self.session_file, "--expires-ms", self.expires, "--approve", check=True)
        self.enable_listener()

    def enable_listener(self) -> None:
        row = {"type": "custom", "customType": STATE,
               "data": {"session": SESSION, "file": str(self.session_file), "registration": str(self.registration),
                        "hash": sha_bytes(self.registration.read_bytes()), "enabled": True}}
        with self.session_file.open("ab") as handle:
            handle.write(packed(row))
        self.session_file.chmod(0o600)

    def disable_listener(self) -> None:
        rewrite(self.session_file, {"type": "session", "version": 3, "id": SESSION, "cwd": str(self.workspace)}, 0o600)

    def duplicate_inbox(self) -> Path:
        other = self.root / "inbox-duplicate"
        other.mkdir(mode=0o700)
        row = {"version": 1, "job": "FIXTURE-B4", "session": SESSION, "session_file": str(self.session_file),
               "expires_ms": self.expires, "manifest_digest": sha_manifest(self.manifest)}
        put(other / "registration.json", row, 0o400)
        return other

    def append_state(self, enabled: bool) -> None:
        row = {"type": "custom", "customType": STATE,
               "data": {"session": SESSION, "file": str(self.session_file), "registration": str(self.registration),
                        "hash": sha_bytes(self.registration.read_bytes()), "enabled": enabled}}
        with self.session_file.open("ab") as handle:
            handle.write(packed(row))
        self.session_file.chmod(0o600)

    def register_job_only(self) -> None:
        self.cli("scripts/factory-inbox.py", "register", "job", self.inbox, "--manifest", self.manifest_file,
                 "--session", self.session_file, "--expires-ms", self.expires, "--approve", check=True)

    def preview(self, *extra: object, check: bool = True, manual: bool = False):
        args = ["preview", self.manifest_file, "--registration", self.registration,
                "--writer-worktree", self.writer, "--reviewer-worktree", self.reviewer,
                "--plan-out", self.plan, "--brief", self.brief, "--herdr", HERDR_EXE, "--pi", PI_EXE,
                "--session-dir", self.sessions, "--agent-dir", self.agent,
                "--extension", KIT / "tests/fixtures/factory-run-provider.ts",
                "--pi-arg=--no-tools", "--pi-arg=--no-context-files", *extra]
        if manual:
            args.append("--manual-fixture")
        return self.cli("scripts/factory-run.py", *args, check=check)

    def start_herdr(self) -> None:
        self.herdr_session = json.loads(self.plan.read_text())["herdr_session"]
        self.server = subprocess.Popen([HERDR_EXE, "--session", self.herdr_session, "server"],
                                       env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       start_new_session=True)
        socket = self.xdg / "herdr" / "sessions" / self.herdr_session / "herdr.sock"
        wait_for(lambda: socket.exists(), "herdr test server did not start", 30)

    def herdr(self, *args: str) -> dict:
        result = subprocess.run([HERDR_EXE, "--session", self.herdr_session, *args], env=self.env,
                                capture_output=True, text=True, timeout=60, check=False)
        self.test.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["result"]

    def trace(self) -> list[dict]:
        path = self.root / "provider.jsonl"
        return [json.loads(row) for row in path.read_text().splitlines()] if path.exists() else []

    def requests(self) -> list[dict]:
        return [row for row in self.trace() if row["event"] == "provider-start"]

    def dispatch_count(self, role: str) -> int:
        return sum(1 for row in self.requests() if row.get("role") == role)

    def transcript_rows(self, path: Path | None = None) -> list[dict]:
        target = path or self.session_file
        return [json.loads(row) for row in target.read_text().splitlines() if row.strip()]

    def state_row(self) -> dict:
        return json.loads(self.state.read_text())

    def attempt_path(self, role: str, attempt: str) -> Path:
        return self.inbox / f"{role}.{attempt}" / "attempt.json"

    def transcript(self, session_id: str) -> Path | None:
        return next(iter(self.sessions.rglob(f"*_{session_id}.jsonl")), None)

    def prompt(self, role: str, attempt: str) -> str:
        return Path(self.state_row()["prompts"][f"{role}.{attempt}"]["path"]).read_text()

    def publish(self, stage: str, attempt: str, outcome: str) -> None:
        report, evidence = self.root / f"{stage}.{attempt}.report", self.root / f"{stage}.{attempt}.evidence"
        if stage == "reviewer":
            candidate = json.loads((self.inbox / "candidate.json").read_text())
            receipt = {"version": 1, "manifest_digest": candidate["manifest_digest"],
                       "candidate_digest": candidate["candidate_digest"], "verdict": outcome,
                       "reviewer": {"model": "openai/gpt-6.1-sol", "worktree": candidate["candidate"]},
                       "findings": [{"id": "F1", "severity": "low", "status": "closed",
                                     "description": "fixture finding needs repair"}],
                       "verification": [{"command": f"git -C {self.repo} rev-parse HEAD", "status": "pass",
                                         "evidence": "fixture observed exit 0", "skipped": []}],
                       "mutations": [{"guard": "G1", "result": "failed-as-expected", "evidence": "fixture guard failed"}],
                       "not_verified": ["synthetic provider does not establish model quality"]}
            put(report, receipt, 0o400)
        else:
            put(report, f"synthetic {stage} {attempt} report\n".encode(), 0o400)
        put(evidence, b"synthetic local evidence\n", 0o400)
        args = ["publish", self.registration, stage, attempt]
        if stage == "writer":
            args.append(outcome)
        args.extend(["--report", report, "--evidence", evidence, "--approve"])
        self.cli("scripts/factory-inbox.py", *args, check=True)

    def close(self) -> None:
        if self.server and self.server.poll() is None:
            self.server.send_signal(signal.SIGTERM)
            try:
                self.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=5)

    def target_status(self) -> list[str]:
        return [row for row in git(self.repo, "status", "--porcelain").splitlines() if row]

    def protected(self) -> dict:
        def snap(path: Path) -> dict:
            return {str(item.relative_to(path)): (stat.S_IMODE(item.lstat().st_mode),
                                                   item.read_bytes() if item.is_file() and not item.is_symlink() else None)
                    for item in (path, *path.rglob("*"))}
        return {"repo": snap(self.repo), "agent": snap(self.agent), "home": snap(self.home), "inbox": snap(self.inbox)}


def sha_manifest(manifest: dict) -> str:
    sys.path.insert(0, str(KIT / "scripts/lib"))
    import factory_contract as contract
    return contract.manifest_digest(manifest)


@unittest.skipUnless(PI_EXE and os.path.isabs(PI_EXE) and HERDR_EXE and os.path.isabs(HERDR_EXE),
                     "DCC_PI_EXECUTABLE and DCC_HERDR_EXECUTABLE are required")
class FactoryRunE2E(unittest.TestCase):
    def fixture(self, **kwargs) -> LoopFixture:
        fixture = LoopFixture(self, **kwargs)
        self.addCleanup(fixture.close)
        return fixture

    def test_preview_decline_unverified_duplicate_and_unapproved_launch(self):
        r = self.fixture()
        r.register()
        r.append_state(False)
        self.assertEqual(r.preview(check=False).returncode, 1, "latest disabled state must not be ready")
        r.append_state(True)
        before = r.protected()
        result = r.preview()
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(r.plan.read_text())
        self.assertEqual(plan["listener"]["mode"], "enabled-listener")
        self.assertEqual((plan["routes"]["writer"]["model"], plan["routes"]["reviewer"]["model"]),
                         ("deepseek-flash", "gpt-6.1-sol"))
        self.assertFalse(r.writer.exists() or r.reviewer.exists())
        self.assertEqual(r.protected(), before)
        self.assertEqual(r.loop("launch", r.plan, "--state", r.state).returncode, 1)
        self.assertFalse(r.writer.exists())
        r.disable_listener()
        refused = r.loop("launch", r.plan, "--state", r.state, "--approve")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("unverified-listener", refused.stderr)
        self.assertFalse(r.writer.exists())
        r.enable_listener()
        r.duplicate_inbox()
        duplicate = r.preview(check=False)
        self.assertEqual(duplicate.returncode, 1)
        self.assertIn("duplicate-listener", duplicate.stderr)

    def test_approved_launch_complete_assignment_review_repair_and_handoff(self):
        r = self.fixture()
        r.register()
        self.assertEqual(r.preview("--alternate-writer", "openai/gpt-6.2-sol").returncode, 0)
        r.start_herdr()
        launched = r.loop("launch", r.plan, "--state", r.state, "--approve", check=True)
        self.assertEqual(json.loads(launched.stdout)["status"], "writer-dispatched")
        self.assertEqual(git(r.writer, "rev-parse", "HEAD").strip(), r.manifest["base"]["commit"])
        wait_for(lambda: r.dispatch_count("writer") == 1, "writer role request missing")
        self.assertEqual([(row["role"], row["provider"], row["model"]) for row in r.requests()],
                         [("writer", "deepseek", "deepseek-flash")])
        self.assertEqual(r.requests()[0]["agent_dir"], str(r.agent))
        writer_prompt = r.prompt("writer", "a1")
        for token in (r.state_row()["brief_sha256"], "factory/WORKER.md", str(r.repo / "AGENTS.md"),
                      str(r.registration), "factory-inbox.py", "writer.a1.report.md", "writer.a1.evidence.md"):
            self.assertIn(token, writer_prompt)
        put(r.writer / "new.txt", b"reviewed candidate\n")
        before = r.target_status()
        self.assertEqual(r.loop("advance", r.state).returncode, 1, "idle state must not be completion")
        r.publish("writer", "a1", "reported")
        self.assertEqual(json.loads(r.loop("advance", r.state, check=True).stdout)["status"], "review-dispatched")
        candidate = json.loads((r.inbox / "candidate.json").read_text())
        self.assertNotEqual(Path(candidate["candidate"]), r.writer)
        wait_for(lambda: r.dispatch_count("reviewer") == 1, "reviewer role request missing")
        self.assertEqual([(row["role"], row["model"]) for row in r.requests()],
                         [("writer", "deepseek-flash"), ("reviewer", "gpt-6.1-sol")])
        self.assertEqual(r.requests()[-1]["agent_dir"], str(r.agent))
        reviewer_session = next(session for session, row in r.state_row()["sessions"].items()
                                if row["role"] == "reviewer")
        self.assertIn("--thinking", r.state_row()["sessions"][reviewer_session]["argv"])
        self.assertIn("high", r.state_row()["sessions"][reviewer_session]["argv"])
        transcript = r.transcript(reviewer_session)
        assert transcript is not None
        text = transcript.read_text()
        levels = re.findall(r'"(?:thinkingLevel|thinking_level)"\s*:\s*"([^"]+)"', text)
        self.assertTrue(all(level == "high" for level in levels), levels)
        reviewer_prompt = r.prompt("reviewer", "a1")
        self.assertIn("factory/REVIEWER.md", reviewer_prompt)
        self.assertIn(str(Path(candidate["candidate"])), reviewer_prompt)
        self.assertIn("python3 -B", reviewer_prompt)
        self.assertNotIn("/tmp/dcc-a14-tools", writer_prompt + reviewer_prompt)
        self.assertEqual(r.target_status(), before, "review dispatch changed the target")

        r.publish("reviewer", "a1", "changes_requested")
        repaired = json.loads(r.loop("advance", r.state, check=True).stdout)
        self.assertEqual((repaired["status"], repaired["attempt"]), ("repair-dispatched", "a2"))
        self.assertIn("fixture finding needs repair", r.prompt("writer", "a2"))
        wait_for(lambda: r.dispatch_count("writer") == 2, "repair writer request missing")
        self.assertEqual(r.target_status(), before, "changes_requested applied target bytes")
        rewrite(r.writer / "new.txt", b"reviewed candidate\nrepaired\n")
        r.publish("writer", "a2", "reported")
        self.assertEqual(json.loads(r.loop("advance", r.state, check=True).stdout)["status"], "review-dispatched")
        r.publish("reviewer", "a2", "approved")
        ready = json.loads(r.loop("advance", r.state, check=True).stdout)
        self.assertEqual((ready["status"], ready["launched"]), ("ready-to-handoff", False))
        self.assertEqual(r.target_status(), before)
        self.assertEqual(r.loop("handoff", r.state).returncode, 1)
        staged = json.loads(r.loop("handoff", r.state, "--approve", check=True).stdout)
        self.assertEqual((staged["staged_only"], staged["committed"]), (True, False))
        self.assertEqual(git(r.repo, "rev-parse", "HEAD").strip(), r.manifest["base"]["commit"])
        self.assertEqual((r.repo / "new.txt").read_bytes(), b"reviewed candidate\nrepaired\n")
        self.assertEqual(r.target_status(), ["A  new.txt"])

    def test_staged_baseline_is_transferred_before_dispatch(self):
        r = self.fixture(staged=True)
        r.register()
        self.assertEqual(r.preview().returncode, 0)
        r.start_herdr()
        r.loop("launch", r.plan, "--state", r.state, "--approve", check=True)
        self.assertEqual((r.writer / "file.txt").read_bytes(), b"staged baseline bytes\n")
        self.assertEqual(stat.S_IMODE((r.writer / "file.txt").stat().st_mode), 0o755)
        self.assertEqual((r.writer / "baseline-marker.txt").read_bytes(), b"approved staged marker\n")
        self.assertIn(b"staged target instruction", (r.writer / "AGENTS.md").read_bytes())
        self.assertEqual(r.writer.joinpath("file.txt").read_bytes(), (r.repo / "file.txt").read_bytes())

    def test_manual_fixture_exception_and_shared_exhaustion(self):
        r = self.fixture()
        r.register()
        r.disable_listener()
        self.assertEqual(r.preview(check=False).returncode, 1, "header-only listener must not preview")
        self.assertEqual(r.preview(manual=True, check=False).returncode, 0)
        r.start_herdr()
        r.loop("launch", r.plan, "--state", r.state, "--approve", check=True)
        self.assertEqual(r.state_row()["listener"]["mode"], "manual-approved-fixture")
        r.publish("writer", "a1", "reported")
        self.assertEqual(r.loop("advance", r.state).returncode, 1, "manual path needs its explicit exception")
        self.assertEqual(json.loads(r.loop("advance", r.state, "--manual", check=True).stdout)["status"],
                         "review-dispatched")
        wait_for(lambda: r.dispatch_count("reviewer") == 1, "manual reviewer request missing")

    def test_default_cumulative_history_does_not_cap_and_new_attempts_get_own_allowance(self):
        r = self.fixture()
        r.register()
        self.assertEqual(r.preview("--used-writer", "146:40", "--used-reviewer", "117:29").returncode, 0)
        r.start_herdr()
        r.loop("launch", r.plan, "--state", r.state, "--approve", check=True)
        state = r.state_row()
        self.assertEqual(state["attempt_allocations"]["writer.a1"], {"calls": 60, "minutes": 25})
        self.assertEqual(state["usage"]["writer"], {"calls": 146, "minutes": 40})
        put(r.writer / "new.txt", b"candidate\n")
        r.publish("writer", "a1", "reported")
        r.loop("advance", r.state, check=True)
        state = r.state_row()
        self.assertEqual(state["attempt_allocations"]["reviewer.a1"], {"calls": 60, "minutes": 25})
        r.publish("reviewer", "a1", "changes_requested")
        r.loop("advance", r.state, check=True)
        state = r.state_row()
        self.assertEqual(state["attempt_allocations"]["writer.a2"], {"calls": 30, "minutes": 15})
        self.assertEqual(state["attempt_usage"]["writer.a2"], {"calls": 0, "minutes": 0})
        self.assertEqual(state["usage"]["writer"]["calls"], 146, "cumulative role history must persist")

    def test_same_attempt_spend_is_conserved_and_attempt_exhaustion_pauses(self):
        r = self.fixture()
        r.register()
        self.assertEqual(r.preview().returncode, 0)
        r.start_herdr()
        r.loop("launch", r.plan, "--state", r.state, "--approve", check=True)
        self.assertEqual(r.loop("advance", r.state, "--spend", "writer.a1:60:25").returncode, 1)
        state = r.state_row()
        self.assertEqual(state["attempt_usage"]["writer.a1"], {"calls": 60, "minutes": 25})
        self.assertEqual(state["usage"]["shared"]["calls"], 60)
        self.assertEqual(r.loop("advance", r.state, "--spend", "writer.a1:1:1").returncode, 1)
        state = r.state_row()
        self.assertEqual(state["attempt_usage"]["writer.a1"]["calls"], 61, "same-ID spend must be conserved")
        put(r.writer / "new.txt", b"candidate\n")
        r.publish("writer", "a1", "reported")
        self.assertEqual(json.loads(r.loop("advance", r.state, check=True).stdout)["status"], "review-dispatched")
        self.assertEqual(r.loop("advance", r.state, "--spend", "reviewer.a1:60:25").returncode, 1)
        r.publish("reviewer", "a1", "changes_requested")
        r.loop("advance", r.state, check=True)
        state = r.state_row()
        self.assertEqual(state["attempt_allocations"]["writer.a2"], {"calls": 30, "minutes": 15})
        self.assertEqual(state["attempt_usage"]["writer.a2"], {"calls": 0, "minutes": 0})
        status = json.loads(r.loop("status", r.state, check=True).stdout)
        self.assertEqual(status["attempt_remaining"]["reviewer.a1"]["calls"], 0)
        self.assertEqual(state["usage"]["reviewer"]["calls"], 60)

    def test_optional_overall_ceiling_old_f7_and_initial_use_coherence(self):
        r = self.fixture()
        r.register()
        inconsistent = r.preview("--overall-limit", "3:3", "--used-writer", "3:3", "--used-shared", "0:0",
                                 check=False)
        self.assertEqual(inconsistent.returncode, 1)
        self.assertIn("invalid-budget", inconsistent.stderr)
        derived = r.preview("--overall-limit", "3:3", "--used-writer", "3:3")
        self.assertEqual(derived.returncode, 0)
        launched = r.loop("launch", r.plan, "--state", r.state, "--approve")
        self.assertFalse(r.writer.exists(), "an exhausted selected overall ceiling must not create a worktree")
        self.assertEqual(launched.returncode, 1)
        self.assertIn("budget-exhausted", launched.stderr)
        self.assertEqual(r.state_row()["blocked"]["scope"], "overall")

    def test_old_budget_state_is_refused_without_reset(self):
        r = self.fixture()
        r.register()
        old = r.state_dir / "old-state.json"
        put(old, {"version": 1, "plan_digest": "a" * 64, "phase": "dispatched"}, 0o400)
        refused = r.loop("advance", old)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("stale-state", refused.stderr)
        self.assertEqual(json.loads(old.read_text())["phase"], "dispatched", "old state must not be rewritten")

    def test_third_repair_and_refusal_restart_are_denied(self):
        sys.path.insert(0, str(KIT / "scripts/lib"))
        import factory_run as loop
        state = {"policy": loop.POLICY, "attempts": [{"role": "writer", "attempt": "a1"}] * 1,
                 "attempt_limits": {"writer.repair": {"calls": 30, "minutes": 15}},
                 "attempt_allocations": {}, "attempt_usage": {}, "attempt_kinds": {}, "events": [],
                 "repairs": 2, "blocked": None, "usage": {}}
        with self.assertRaises(loop.RunError) as caught:
            loop.dispatch_repair(state, {})
        self.assertEqual(getattr(caught.exception, "code", None), "repair-limit")

    def test_switch_eligibility_refusals_and_approved_alternate(self):
        r = self.fixture()
        r.register()
        self.assertEqual(r.preview("--alternate-writer", "openai/gpt-6.2-sol").returncode, 0)
        r.start_herdr()
        r.loop("launch", r.plan, "--state", r.state, "--approve", check=True)
        active = r.loop("switch-writer", r.state, "--to", "openai/gpt-6.2-sol", "--reason", "still active",
                        "--approve")
        self.assertEqual(active.returncode, 1)
        self.assertIn("writer-active", active.stderr)
        r.publish("writer", "a1", "blocked")
        r.loop("stop", r.state, "--reason", "writer-unavailable", "--role", "writer", check=True)
        switched = json.loads(r.loop("switch-writer", r.state, "--to", "openai/gpt-6.2-sol",
                                     "--reason", "approved alternate", "--approve", check=True).stdout)
        self.assertEqual((switched["writer"], switched["reviewer"]), ("openai/gpt-6.2-sol", "openai/gpt-6.1-sol"))
        r.loop("stop", r.state, "--reason", "provider-refusal", "--role", "writer", check=True)
        refused = r.loop("switch-writer", r.state, "--to", "openai/gpt-6.2-sol", "--reason", "bypass",
                         "--approve")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("blocked-state", refused.stderr)
        self.assertEqual(r.loop("advance", r.state).returncode, 1)

    def test_composed_busy_coordinator_reviewer_callback_with_real_listener(self):
        import errno
        import fcntl
        import pty
        import struct
        import threading
        r = self.fixture()
        r.session_file.unlink()
        r.session_file = r.sessions / "coordinator.jsonl"
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 200, 0, 0))
        env = dict(r.env, DCC_OFFLINE_FIXTURE=str(r.root))
        args = [PI_EXE, "--offline", "--no-extensions", "--no-tools", "--no-mcp", "--no-skills",
                "--no-prompt-templates", "--no-themes", "--no-context-files", "--no-approve",
                "--tui-mode", "regular", "--model", "dcc-offline-fixture/deterministic",
                "--session-dir", str(r.sessions), "--session-id", "coordinator",
                "-e", str(KIT / "tests/fixtures/factory-inbox-provider.ts"),
                "-e", str(KIT / "extensions/factory-inbox.ts")]
        proc = subprocess.Popen(args, cwd=r.workspace, env=env, stdin=slave, stdout=slave, stderr=slave,
                                start_new_session=True, umask=0o077)
        os.close(slave)
        screen = bytearray()
        def drain():
            while True:
                try:
                    part = os.read(master, 8192)
                except OSError as exc:
                    if exc.errno in (errno.EBADF, errno.EIO):
                        break
                    raise
                if not part:
                    break
                screen.extend(part)
        threading.Thread(target=drain, daemon=True).start()
        def send(line):
            os.write(master, line.encode() + b"\r")
        try:
            wait_for(lambda: b"factory-inbox-provider.ts" in screen, "coordinator TUI did not start", 30)
            send("Establish the disposable coordinator conversation.")
            wait_for(lambda: b"OFFLINE_PLANNING_REPLY" in screen and any(r.sessions.rglob("*_coordinator.jsonl")),
                     "coordinator session not persisted")
            r.session_file = next(r.sessions.rglob("*_coordinator.jsonl"))
            r.register_job_only()
            send("/dcc-handoff enable " + str(r.registration))
            wait_for(lambda: b"enabled (notification-only)" in screen, "real listener was not enabled")
            self.assertEqual(r.preview().returncode, 0)
            r.start_herdr()
            r.loop("launch", r.plan, "--state", r.state, "--approve", check=True)
            put(r.writer / "new.txt", b"candidate\n")
            r.publish("writer", "a1", "reported")
            r.loop("advance", r.state, check=True)
            before_hold = len([row for row in r.transcript_rows(r.session_file) if row.get("type") == "custom_message"])
            callbacks_before = sum(1 for row in r.trace() if row["event"] == "provider-start" and row.get("callback"))
            send("HOLD_THIS_PLANNING_TURN")
            wait_for(lambda: any(row["event"] == "provider-start" and row.get("hold")
                                 for row in r.trace()), "coordinator hold not active")
            r.publish("reviewer", "a1", "approved")
            time.sleep(1.2)
            notices = [row for row in r.transcript_rows(r.session_file) if row.get("type") == "custom_message"]
            self.assertEqual(len(notices), before_hold, "reviewer notice delivered while coordinator was busy")
            self.assertEqual(sum(1 for row in r.trace() if row["event"] == "provider-start"
                                 and row.get("callback")), callbacks_before)
            put(r.root / "release", b"release\n")
            wait_for(lambda: len([row for row in r.transcript_rows(r.session_file)
                                  if row.get("type") == "custom_message"]) > before_hold,
                     "post-settlement callback missing")
            notices = [row for row in r.transcript_rows(r.session_file) if row.get("type") == "custom_message"]
            self.assertEqual(len(notices), before_hold + 1)
            candidate = json.loads((r.inbox / "candidate.json").read_text())
            self.assertEqual(notices[-1]["details"]["candidate_digest"], candidate["candidate_digest"])
            self.assertEqual(notices[-1]["details"]["outcome"], "approved")
            wait_for(lambda: sum(1 for row in r.trace() if row["event"] == "provider-start"
                                 and row.get("callback")) == callbacks_before + 1, "bound callback turn missing")
            trace = [row["event"] for row in r.trace()]
            self.assertLess(trace.index("provider-reply"), len(trace) - 1)
            os.write(master, b"\x04")
            proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
            os.close(master)

    def test_selected_smaller_allowances_appear_in_actual_role_assignments(self):
        r = self.fixture()
        r.register()
        self.assertEqual(r.preview("--writer-attempt-limit", "8:7", "--reviewer-attempt-limit", "3:2").returncode, 0)
        r.start_herdr()
        r.loop("launch", r.plan, "--state", r.state, "--approve", check=True)
        writer_prompt = r.prompt("writer", "a1")
        self.assertIn("8 calls / 7 active minutes", writer_prompt)
        self.assertIn("remaining 8 calls / 7 minutes", writer_prompt)
        put(r.writer / "new.txt", b"candidate\n")
        r.publish("writer", "a1", "reported")
        r.loop("advance", r.state, check=True)
        reviewer_prompt = r.prompt("reviewer", "a1")
        self.assertIn("3 calls / 2 active minutes", reviewer_prompt)
        self.assertIn("remaining 3 calls / 2 minutes", reviewer_prompt)

    def test_pi_arguments_cannot_override_approved_role_identity(self):
        for args in (("--pi-arg=--provider", "--pi-arg=deepseek"),
                     ("--pi-arg=--provider=deepseek",),
                     ("--pi-arg=--model", "--pi-arg=deepseek/deepseek-flash"),
                     ("--pi-arg=--model=deepseek/deepseek-flash",),
                     ("--pi-arg=-mdeepseek/deepseek-flash",),
                     ("--pi-arg=--models=deepseek/*",),
                     ("--pi-arg=--thinking", "--pi-arg=low")):
            r = self.fixture()
            r.register()
            refused = r.preview(*args, check=False)
            self.assertEqual(refused.returncode, 1)
            self.assertIn("invalid-route", refused.stderr)
            self.assertFalse(r.writer.exists())
            self.assertFalse(r.state.exists())
            self.assertFalse((r.root / "provider.jsonl").exists(), "refused plan must send no provider request")

    def test_valid_plan_with_identity_override_refuses_before_side_effects(self):
        r = self.fixture()
        r.register()
        self.assertEqual(r.preview().returncode, 0)
        plan = json.loads(r.plan.read_text())
        plan["tools"]["pi_args"] = [*plan["tools"]["pi_args"], "--provider", "deepseek"]
        plan.pop("plan_digest")
        import hashlib
        plan["plan_digest"] = hashlib.sha256((json.dumps(plan, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()
        forged = r.state_dir / "forged-plan.json"
        put(forged, plan, 0o400)
        refused = r.loop("launch", forged, "--state", r.state, "--approve")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("invalid-route", refused.stderr)
        self.assertFalse(r.writer.exists())
        self.assertFalse(r.state.exists())
        self.assertFalse((r.root / "provider.jsonl").exists())

    def test_legacy_valid_plan_is_refused_explicitly_before_dispatch(self):
        r = self.fixture()
        r.register()
        self.assertEqual(r.preview().returncode, 0)
        plan = json.loads(r.plan.read_text())
        plan.pop("policy")
        plan.pop("plan_digest")
        import hashlib
        plan["plan_digest"] = hashlib.sha256((json.dumps(plan, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()
        legacy = r.state_dir / "legacy-plan.json"
        put(legacy, plan, 0o400)
        refused = r.loop("launch", legacy, "--state", r.state, "--approve")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("stale-plan", refused.stderr)
        self.assertFalse(r.writer.exists())
        self.assertFalse(r.state.exists())

    def test_third_switch_and_third_ordinary_repair_are_both_denied(self):
        sys.path.insert(0, str(KIT / "scripts/lib"))
        import factory_run as loop
        r = self.fixture()
        r.register()
        self.assertEqual(r.preview("--alternate-writer", "openai/gpt-6.2-sol",
                                   "--alternate-writer", "deepseek/deepseek-flash").returncode, 0)
        r.start_herdr()
        r.loop("launch", r.plan, "--state", r.state, "--approve", check=True)
        wait_for(lambda: r.dispatch_count("writer") == 1, "initial writer request missing")
        before = sum(1 for row in r.requests() if row.get("role") == "writer")
        # Switch path: two approved switches consume both repair allowances.
        for index in range(2):
            attempts = [row for row in r.state_row()["attempts"] if row["role"] == "writer"]
            r.publish("writer", attempts[-1]["attempt"], "blocked")
            r.loop("stop", r.state, "--reason", "writer-unavailable", "--role", "writer", check=True)
            route = "openai/gpt-6.2-sol" if index == 0 else "deepseek/deepseek-flash"
            r.loop("switch-writer", r.state, "--to", route, "--reason", f"repair {index}",
                   "--approve", check=True)
        attempts = [row for row in r.state_row()["attempts"] if row["role"] == "writer"]
        r.publish("writer", attempts[-1]["attempt"], "blocked")
        r.loop("stop", r.state, "--reason", "writer-unavailable", "--role", "writer", check=True)
        third = r.loop("switch-writer", r.state, "--to", "openai/gpt-6.2-sol", "--reason", "third", "--approve")
        self.assertEqual(third.returncode, 1)
        self.assertIn("repair-limit", third.stderr)
        after = sum(1 for row in r.requests() if row.get("role") == "writer")
        self.assertEqual(after, before + 2, "the denied third switch must not dispatch")
        state = r.state_row()
        self.assertEqual(state["repairs"], loop.REPAIR_LIMIT)

    def test_complete_third_repair_refuses_without_dispatch(self):
        r = self.fixture()
        r.register()
        self.assertEqual(r.preview().returncode, 0)
        r.start_herdr()
        r.loop("launch", r.plan, "--state", r.state, "--approve", check=True)
        for cycle in range(3):
            put(r.writer / "new.txt", f"candidate {cycle}\n".encode(), 0o644) if cycle == 0 else rewrite(r.writer / "new.txt", f"candidate {cycle}\n".encode())
            writers = [row for row in r.state_row()["attempts"] if row["role"] == "writer"]
            r.publish("writer", writers[-1]["attempt"], "reported")
            r.loop("advance", r.state, check=True)
            reviewers = [row for row in r.state_row()["attempts"] if row["role"] == "reviewer"]
            r.publish("reviewer", reviewers[-1]["attempt"], "changes_requested")
            result = r.loop("advance", r.state)
            if cycle < 2:
                self.assertEqual(result.returncode, 0, result.stderr)
            else:
                self.assertEqual(result.returncode, 1)
                self.assertIn("repair-limit", result.stderr)
        writers = [row for row in r.state_row()["attempts"] if row["role"] == "writer"]
        self.assertEqual(len(writers), 3)
        self.assertEqual(sum(1 for row in r.requests() if row.get("role") == "writer"), 3)

    def test_alternate_equal_to_reviewer_is_rejected_and_routes_are_bound(self):
        sys.path.insert(0, str(KIT / "scripts/lib"))
        import factory_run as loop
        r = self.fixture()
        r.register()
        refused = r.preview("--alternate-writer", "openai/gpt-6.1-sol", check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("invalid-route", refused.stderr)
        with self.assertRaises(loop.RunError):
            loop.validate_routes({"coordinator": loop.COORDINATOR, "writer": loop.WRITER,
                                  "reviewer": loop.WRITER})
        loop.validate_routes(loop.ROUTES)


if __name__ == "__main__":
    unittest.main()
