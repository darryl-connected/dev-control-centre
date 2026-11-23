"""Offline archive build and relocated CLI tests. No live harness or provider."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from test_e2e_factory_inbox import ENABLED, WRITER, PiFixture, opened
from test_factory_inbox import CLI, evidence_dir, put, tree
from test_factory_job import BASE_CONTENTS, Fixture, clean_env, digest, json_digest

PACKAGE = Path(__file__).resolve().parent.parent
ARCHIVE = "dev-control-centre.tar.gz"
SCOPE_SHA256 = "deaf692dd0d407c1f7606698224fc48d80cedfde48acc0c4e6d3dceee2ce89d8"
# Distribution expectation fixed here, not imported from the builder.
EXPECTED_MEMBERS = {
    "AGENTS.md", "LICENSE", "README.md", "docs/scope.md", "requirements-dev.txt",
    "factory/COORDINATOR.md", "factory/WORKER.md", "factory/REVIEWER.md", "templates/pi/APPEND_SYSTEM.md",
    "references/factory-contract.md", "references/factory-alignment.json", "scripts/build.py",
    "scripts/factory-job.py", "scripts/factory-alignment.py", "scripts/lib/factory_contract.py", "scripts/validate-brief.py",
    "scripts/verify-suite.py", "tests/test_verify_suite.py",
    "tests/test_factory_job.py", "tests/test_factory_alignment.py", "tests/test_validate_brief.py",
    "tests/test_instruction_packaging.py", "tests/test_e2e_factory.py",
    "docs/pi-setup.md", "scripts/setup.py", "scripts/verify-pi-resources.mjs",
    "skills/setup/SKILL.md", "skills/factory/SKILL.md", "skills/grilling/SKILL.md",
    "tests/test_setup.py", "tests/test_e2e_pi_setup.py",
    "docs/knowledge-hub.md", "scripts/knowledge.py", "scripts/lib/knowledge_hub.py",
    "tests/test_knowledge.py", "tests/test_e2e_knowledge.py",
    "docs/factory-handoff.md", "extensions/factory-inbox.ts", "scripts/factory-inbox.py",
    "scripts/lib/factory_inbox.py", "tests/test_factory_inbox.py", "tests/test_e2e_factory_inbox.py",
    "tests/fixtures/factory-inbox-provider.ts",
    "docs/clickup.md", "references/clickup-api.md", "scripts/clickup.py", "scripts/lib/clickup_reader.py",
    "tests/test_clickup.py", "tests/test_e2e_clickup.py",
    "docs/task-preparation.md", "scripts/prepare.py", "scripts/lib/task_preparation.py",
    "tests/test_prepare.py", "tests/test_e2e_prepare.py",
    "scripts/draft.py", "scripts/lib/openspec_draft.py", "tests/test_draft.py", "tests/test_e2e_draft.py",
    "scripts/factory-run.py", "scripts/lib/factory_run.py", "tests/fixtures/factory-run-provider.ts",
    "tests/test_factory_run.py", "tests/test_e2e_factory_run.py",
}
EXPECTED_EXECUTABLES = {
    "scripts/build.py", "scripts/factory-alignment.py", "scripts/factory-inbox.py", "scripts/factory-job.py",
    "scripts/clickup.py", "scripts/knowledge.py", "scripts/prepare.py", "scripts/draft.py", "scripts/setup.py",
    "scripts/factory-run.py",
    "scripts/validate-brief.py", "scripts/verify-suite.py", "tests/test_factory_job.py",
    "tests/test_validate_brief.py",
}


def regular_files(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class DistributionTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="dcc-offline-")
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.cwd = self.tmp / "unrelated cwd"
        self.cwd.mkdir()
        self.home = self.tmp / "empty-home"
        self.home.mkdir()

    def run_cli(self, script: Path, *args: str, exit_code: int = 0, home: Path | None = None) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [sys.executable, "-B", str(script), *args], cwd=self.cwd,
            env=clean_env(home or self.home), capture_output=True, text=True, check=False, timeout=30,
        )
        self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)
        return result

    def build(self, source: Path, *, home: Path | None = None) -> Path:
        output = self.tmp / "requested output"
        result = self.run_cli(source / "scripts/build.py", "--output", str(output), home=home)
        path = output / ARCHIVE
        self.assertEqual(result.stdout.strip(), str(path))
        self.assertEqual(set(output.iterdir()), {path})
        return path

    def extract(self, artifact: Path) -> Path:
        relocated = self.tmp / "relocated distribution"
        relocated.mkdir()
        with tarfile.open(artifact, "r:gz") as archive:
            for member in archive.getmembers():
                path = relocated / member.name
                self.assertTrue(member.isfile() and path.resolve().is_relative_to(relocated), member.name)
                handle = archive.extractfile(member)
                assert handle is not None
                path.parent.mkdir(parents=True, exist_ok=True)
                with handle:
                    path.write_bytes(handle.read())
                path.chmod(member.mode)
        return relocated

    def test_relocated_cli_snapshots_renders_and_preflights(self) -> None:
        source_before = {path: digest((PACKAGE / path).read_bytes()) for path in EXPECTED_MEMBERS}
        root = self.extract(self.build(PACKAGE))
        self.assertEqual(set(regular_files(root)), EXPECTED_MEMBERS)
        job = root / "scripts/factory-job.py"
        aligned = json.loads(self.run_cli(root / "scripts/factory-alignment.py", "--json").stdout)
        self.assertTrue(aligned["ok"])
        fixture = Fixture(self.tmp / "target fixture")
        link = "src/relocated.ref"
        (fixture.repo / link).symlink_to("../docs/./readme.md")
        commit = fixture.commit("track a link in the relocated fixture")
        target_before = fixture.target_state()
        expected_files = {
            path: {"sha256": digest(contents.encode()), "mode": "100644"}
            for path, contents in BASE_CONTENTS.items()
        } | {link: fixture.git_link_entry(link)}
        expected_base = {
            "commit": commit, "status": [],
            "index_digest": digest(fixture._git("ls-files", "--stage", "-z").stdout.encode()),
            "files": expected_files,
        }
        skeleton = json.loads(self.run_cli(job, "example").stdout)
        self.assertEqual(skeleton["version"], 1)
        self.assertEqual(skeleton["base"], {"commit": "", "status": [], "index_digest": "", "files": {}})
        skeleton["repo"] = str(fixture.repo)
        skeleton["writer"] = {"worktree": str(self.tmp / "writer"), "model": "openai-codex/gpt-6.2-sol"}
        skeleton["task"] = {"id": "OFFLINE-1", "goal": "Demonstrate a relocated gate"}
        skeleton["acceptance"][0]["expected"] = "fixture result is accepted"
        skeleton["budgets"]["writer"] = {"minutes": 17, "calls": 23}
        skeleton["out_of_scope"] = ["production changes"]
        command = f"touch '{self.tmp / 'not-run'}'"
        skeleton["verification"] = [command]
        draft = self.tmp / "draft.json"
        draft.write_text(json.dumps(skeleton), encoding="utf-8")
        before = draft.read_bytes()
        captured = json.loads(self.run_cli(job, "snapshot", str(draft)).stdout)
        self.assertEqual(captured, skeleton | {"base": expected_base})
        self.assertEqual(json_digest(captured["base"]["files"]), json_digest(expected_files))
        self.assertEqual(draft.read_bytes(), before)
        manifest = self.tmp / "manifest.json"
        manifest.write_text(json.dumps(captured), encoding="utf-8")

        brief = self.run_cli(job, "render", str(manifest)).stdout
        for line in (
            "TASK OFFLINE-1. Demonstrate a relocated gate", f"Base commit: {commit}",
            "C1 (from D1): fixture result is accepted", "Allowed paths: src/example.py.",
            "Budget: per-attempt declared allowances", "initial writer up to 23 calls or 17 active minutes", "initial reviewer up to 90 calls or 45 active minutes", "- production changes", "Do not hand off.",
            "Do not spawn sub-agents.", "Do not create worktrees or panes.", "Do not commit.",
            "Do not push.", "Do not use the network.", "Leave your change uncommitted.",
        ):
            self.assertIn(line, brief)
        passed = json.loads(self.run_cli(job, "preflight", str(manifest), "--json").stdout)
        self.assertTrue(passed["ok"] and passed["alignment"]["ok"])
        self.assertGreaterEqual(passed["duration_ms"], 0)
        self.assertFalse((self.tmp / "not-run").exists())

        # Only one manifest field changes per invalid case.
        for changed, reason in (
            (captured | {"task": {"id": "OFFLINE-1"}}, "task.goal: must be a non-empty string"),
            (captured | {"repo": str(self.tmp / "missing-target")}, "repository path does not exist"),
        ):
            manifest.write_text(json.dumps(changed), encoding="utf-8")
            rejected = self.run_cli(job, "preflight", str(manifest), "--json", exit_code=1)
            payload = json.loads(rejected.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(len(payload["errors"]), 1, payload["errors"])
            self.assertIn(reason, payload["errors"][0])
            self.assertEqual(target_before, fixture.target_state())
        self.assertEqual(target_before, fixture.target_state())
        self.assertEqual({path: digest((PACKAGE / path).read_bytes()) for path in EXPECTED_MEMBERS}, source_before)
        self.assertEqual(list(self.home.iterdir()), [], "relocated CLI must not create user settings")
        self.assertEqual(list(self.cwd.iterdir()), [], "CLI must not write into its current directory")

    def test_archive_members_and_contents_and_read_only_build(self) -> None:
        source = self.tmp / "candidate copy"
        for relative in EXPECTED_MEMBERS:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PACKAGE / relative, path)
        private_sentinels = {}
        for relative in (
            ".git/HEAD", "auth.json", ".pi/agent/auth.json", "scratch/live.json", ".venv/bin/python",
            ".ruff_cache/sentinel", "scripts/__pycache__/factory.pyc", "original-kit/README.md",
            ".pi/settings.json", ".pi/APPEND_SYSTEM.md", ".pi/agent/trust.json", ".dcc/workspace.json",
            ".dcc/knowledge.json", "external-evidence/session.json", "synthetic-private-source/context/private.md",
            "registration.json", "writer.a1/attempt.json", "reviewer.a2/event.json", "reviewer.a2/records/evidence",
        ):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            private_sentinels[relative] = f"DCC_EXCLUDED_SENTINEL:{relative}\n".encode()
            path.write_bytes(private_sentinels[relative])
        settings = self.home / ".pi/agent/APPEND_SYSTEM.md"
        settings.parent.mkdir(parents=True)
        settings.write_text("leave existing developer settings unchanged\n", encoding="utf-8")
        before_source = regular_files(source)
        before_home = regular_files(self.home)
        artifact = self.build(source)
        self.assertEqual(before_source, regular_files(source))
        self.assertEqual(before_home, regular_files(self.home))
        self.assertEqual(list(self.cwd.iterdir()), [])
        with tarfile.open(artifact, "r:gz") as archive:
            self.assertCountEqual(archive.getnames(), EXPECTED_MEMBERS)
            for member in archive.getmembers():
                self.assertEqual(member.mode, 0o755 if member.name in EXPECTED_EXECUTABLES else 0o644, member.name)
        root = self.extract(artifact)
        extracted = regular_files(root)
        self.assertEqual(extracted, {path: before_source[path] for path in EXPECTED_MEMBERS})
        for sentinel_path, marker in private_sentinels.items():
            self.assertNotIn(sentinel_path, extracted)
            self.assertFalse(any(marker in contents for contents in extracted.values()), sentinel_path)
        self.assertEqual(digest((root / "docs/scope.md").read_bytes()), SCOPE_SHA256)
        license_text = (root / "LICENSE").read_text(encoding="utf-8")
        for phrase in (
            "MIT License", "Copyright (c) 2026 Nate Herk", "Copyright (c) 2026 Darryl Lim", "AIS-OS",
            "Permission is hereby granted", "THE SOFTWARE IS PROVIDED \"AS IS\"",
        ):
            self.assertIn(phrase, license_text)


class RelocatedHandoffTest(unittest.TestCase):
    def test_relocated_adapter_and_publisher_read_shipped_code_with_original_denied(self) -> None:
        evidence = evidence_dir("handoff-relocation-")
        output = evidence / "dist"
        result = subprocess.run([sys.executable, "-B", str(PACKAGE / "scripts/build.py"), "--output", str(output)],
                                check=False, capture_output=True, text=True, timeout=20, env=clean_env(evidence))
        self.assertEqual(result.returncode, 0, result.stderr)
        relocated = evidence / "relocated kit"
        with tarfile.open(output / ARCHIVE, "r:gz") as archive:
            self.assertCountEqual(archive.getnames(), EXPECTED_MEMBERS)
            for member in archive.getmembers():
                self.assertTrue(member.isfile(), member.name)
                path = relocated / member.name
                path.parent.mkdir(parents=True, exist_ok=True)
                handle = archive.extractfile(member)
                assert handle is not None
                put(path, handle.read(), member.mode)
        data = evidence / "fixture-data"
        data.mkdir(mode=0o700)
        outside = evidence / "unrelocated-source"
        outside.mkdir(mode=0o700)
        blocked_exe = put(outside / "helper", b"#!/bin/sh\nprintf 'outside helper ran\\n'\n", 0o700)
        probe = subprocess.run([str(blocked_exe)], check=True, capture_output=True, text=True, timeout=5)
        self.assertEqual(probe.stdout, "outside helper ran\n")
        original = PACKAGE / "extensions/factory-inbox.ts"
        self.assertEqual(original.read_bytes(), (relocated / "extensions/factory-inbox.ts").read_bytes())
        self.assertTrue((PACKAGE / CLI).is_file())
        native = Path(os.environ["DCC_PI_EXECUTABLE"]).resolve()
        python = Path(sys.executable).resolve()
        launcher = (sys.executable, "-B", str(relocated / "tests/test_factory_inbox.py"), "--confined-exec",
                    str(data), str(relocated), str(original), str(blocked_exe),
                    str(native), str(native.parent), str(python), sys.base_prefix, sys.prefix, "--")
        r = PiFixture(self, data, relocated, launcher)
        before = tree(relocated)
        external_before = tree(outside)
        with opened(relocated / "extensions/factory-inbox.ts") as extension_reads, r.terminal("relocated") as tty:
            transcript = r.establish(tty)
            self.assertTrue(extension_reads(), "Pi never opened the dist's extension")
            with opened(relocated / CLI) as cli_reads, opened(relocated / "scripts/lib/factory_inbox.py") as lib_reads:
                r.register(transcript)
                r.attempt("writer", "a1")
                expected = r.publish("writer", "a1", "reported")
                self.assertTrue(cli_reads(), "Producer never opened the dist's CLI")
                self.assertTrue(lib_reads(), "Producer never opened the dist's protocol library")
            tty.command("enable " + str(r.registration), ENABLED)
            r.observe_notice(expected, WRITER, 1)
            self.assertEqual(tty.children(), [])
        self.assertEqual(tree(relocated), before)
        self.assertEqual(tree(outside), external_before)
        r.assert_offline_effects()


if __name__ == "__main__":
    unittest.main()
