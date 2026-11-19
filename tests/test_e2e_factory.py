"""Offline archive build and relocated CLI tests. No live harness or provider."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from test_factory_job import BASE_CONTENTS, Fixture, clean_env, digest

PACKAGE = Path(__file__).resolve().parent.parent
ARCHIVE = "dev-control-centre.tar.gz"
SCOPE_SHA256 = "e76d9d5a4234710274d929cf12083a106d3755c8102ef08cc1e9dc1a6972711c"
# Distribution expectation fixed here, not imported from the builder.
EXPECTED_MEMBERS = {
    "AGENTS.md", "LICENSE", "README.md", "docs/scope.md", "requirements-dev.txt",
    "factory/COORDINATOR.md", "factory/WORKER.md", "factory/REVIEWER.md", "templates/pi/APPEND_SYSTEM.md",
    "references/factory-contract.md", "references/factory-alignment.json", "scripts/build.py",
    "scripts/factory-job.py", "scripts/factory-alignment.py", "scripts/lib/factory_contract.py", "scripts/validate-brief.py",
    "tests/test_factory_job.py", "tests/test_factory_alignment.py", "tests/test_validate_brief.py",
    "tests/test_instruction_packaging.py", "tests/test_e2e_factory.py",
    "docs/pi-setup.md", "scripts/setup.py", "scripts/verify-pi-resources.mjs",
    "skills/setup/SKILL.md", "skills/factory/SKILL.md", "skills/grilling/SKILL.md",
    "tests/test_setup.py", "tests/test_e2e_pi_setup.py",
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
        return relocated

    def test_relocated_cli_snapshots_renders_and_preflights(self) -> None:
        root = self.extract(self.build(PACKAGE))
        job = root / "scripts/factory-job.py"
        fixture = Fixture(self.tmp / "target fixture")
        target_before = fixture.target_state()
        expected_base = {
            "commit": fixture.base_commit, "status": [],
            "index_digest": digest(fixture._git("ls-files", "--stage", "-z").stdout.encode()),
            "files": {
                path: {"sha256": digest(contents.encode()), "mode": "100644"}
                for path, contents in BASE_CONTENTS.items()
            },
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
        self.assertEqual(draft.read_bytes(), before)
        manifest = self.tmp / "manifest.json"
        manifest.write_text(json.dumps(captured), encoding="utf-8")

        brief = self.run_cli(job, "render", str(manifest)).stdout
        for line in (
            "TASK OFFLINE-1. Demonstrate a relocated gate", f"Base commit: {fixture.base_commit}",
            "C1 (from D1): fixture result is accepted", "Allowed paths: src/example.py.",
            "Budget: writer 17 minutes and 23 tool calls", "- production changes", "Do not hand off.",
            "Do not spawn sub-agents.", "Do not create worktrees or panes.", "Do not commit.",
            "Do not push.", "Do not use the network.", "Leave your change uncommitted.",
        ):
            self.assertIn(line, brief)
        aligned = json.loads(self.run_cli(root / "scripts/factory-alignment.py", "--json").stdout)
        self.assertTrue(aligned["ok"])
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
        self.assertEqual(list(self.home.iterdir()), [], "relocated CLI must not create user settings")
        self.assertEqual(list(self.cwd.iterdir()), [], "CLI must not write into its current directory")

    def test_archive_members_and_contents_and_read_only_build(self) -> None:
        source = self.tmp / "candidate copy"
        for relative in EXPECTED_MEMBERS:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PACKAGE / relative, path)
        for relative in (
            ".git/HEAD", "auth.json", ".pi/agent/auth.json", "scratch/live.json", ".venv/bin/python",
            ".ruff_cache/sentinel", "scripts/__pycache__/factory.pyc", "original-kit/README.md",
            ".pi/settings.json", ".pi/APPEND_SYSTEM.md", ".pi/agent/trust.json", ".dcc/workspace.json",
        ):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("dummy sentinel, never distribute\n", encoding="utf-8")
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
        root = self.extract(artifact)
        self.assertEqual(regular_files(root), {path: before_source[path] for path in EXPECTED_MEMBERS})
        self.assertEqual(digest((root / "docs/scope.md").read_bytes()), SCOPE_SHA256)
        license_text = (root / "LICENSE").read_text(encoding="utf-8")
        for phrase in (
            "MIT License", "Copyright (c) 2026 Nate Herk", "Copyright (c) 2026 Darryl Lim", "AIS-OS",
            "Permission is hereby granted", "THE SOFTWARE IS PROVIDED \"AS IS\"",
        ):
            self.assertIn(phrase, license_text)


if __name__ == "__main__":
    unittest.main()
