"""Structural, fingerprint and read-only checks in disposable package copies."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_factory_job import Fixture, clean_env, contract

PACKAGE = Path(__file__).resolve().parent.parent
FINGERPRINT_PATH = Path("references/factory-alignment.json")
COORDINATOR = Path("factory/COORDINATOR.md")


class AlignmentCase(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="factory-align-")
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.root = self.tmp / "relocated kit"
        for entry in json.loads((PACKAGE / FINGERPRINT_PATH).read_bytes())["entries"]:
            relative = Path(entry["path"])
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PACKAGE / relative, target)
        self.fingerprints = self.root / FINGERPRINT_PATH
        shutil.copyfile(PACKAGE / FINGERPRINT_PATH, self.fingerprints)

    def run_cli(self, *args: str, script: str = "factory-alignment.py") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(self.root / "scripts" / script), *args],
            cwd=self.tmp, env=clean_env(self.home), capture_output=True, text=True, check=False,
        )

    def assert_alignment(self, reason: str = "") -> dict:
        before = self.fingerprints.read_bytes() if self.fingerprints.exists() else None
        result = self.run_cli("--json")
        self.assertEqual(result.returncode, 1 if reason else 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["ok"], not reason)
        if reason:
            self.assertIn(reason, " | ".join(payload["errors"]))
        after = self.fingerprints.read_bytes() if self.fingerprints.exists() else None
        self.assertEqual(before, after, "alignment must not rewrite the recorded fingerprints")
        return payload

    def test_intact_package_and_print_only(self) -> None:
        payload = self.assert_alignment()
        self.assertIn("semantic alignment", " ".join(payload["limitations"]))
        self.assertGreaterEqual(payload["duration_ms"], 0)
        before = self.fingerprints.read_bytes()
        printed = self.run_cli("--print-fingerprints")
        self.assertEqual(printed.returncode, 0, printed.stderr)
        self.assertEqual(json.loads(printed.stdout)["entries"], json.loads(before)["entries"])
        self.assertEqual(self.fingerprints.read_bytes(), before)

    def test_rule_prose_drift_fails_closed(self) -> None:
        self.assert_alignment()
        file = self.root / COORDINATOR
        original = file.read_text(encoding="utf-8")
        changed = original.replace("Map every approved decision reference", "Map a few approved decisions")
        self.assertNotEqual(changed, original)
        file.write_text(changed, encoding="utf-8")
        self.assert_alignment("factory/COORDINATOR.md changed since review")

    def test_missing_rule_fails_even_after_refresh(self) -> None:
        file = self.root / COORDINATOR
        text = file.read_text(encoding="utf-8")
        file.write_text(text.replace("**A6 Decision traceability.", "**Decision traceability."), encoding="utf-8")
        printed = self.run_cli("--print-fingerprints")
        self.assertEqual(printed.returncode, 0, printed.stderr)
        self.fingerprints.write_text(printed.stdout, encoding="utf-8")
        self.assert_alignment("missing rule IDs: A6")

    def test_missing_required_file_fails(self) -> None:
        self.assert_alignment()
        for relative in ("tests/test_factory_job.py", "factory/WORKER.md", "templates/pi/APPEND_SYSTEM.md", "docs/scope.md"):
            with self.subTest(relative):
                target = self.root / relative
                content = target.read_bytes()
                target.unlink()
                self.assert_alignment(f"{relative} is missing")
                target.write_bytes(content)

    def test_preflight_blocks_when_package_resource_is_missing(self) -> None:
        fixture = Fixture(self.tmp / "fixture")
        example = self.run_cli("example", script="factory-job.py")
        self.assertEqual(example.returncode, 0, example.stderr)
        data = json.loads(example.stdout) | {"repo": str(fixture.repo), "base": fixture.baseline()}
        manifest = self.tmp / "job.json"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        target = fixture.target_state()
        fingerprint = self.fingerprints.read_bytes()
        valid = self.run_cli("preflight", str(manifest), "--json", script="factory-job.py")
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        (self.root / "factory/REVIEWER.md").unlink()
        rejected = self.run_cli("preflight", str(manifest), "--json", script="factory-job.py")
        self.assertEqual(rejected.returncode, 1, rejected.stdout + rejected.stderr)
        self.assertEqual(json.loads(rejected.stdout)["errors"], ["alignment: fingerprint_drift: factory/REVIEWER.md is missing"])
        self.assertEqual(fingerprint, self.fingerprints.read_bytes())
        self.assertEqual(target, fixture.target_state())

    def test_external_symlink_is_not_a_package_resource(self) -> None:
        target = self.root / "factory/WORKER.md"
        external = self.tmp / "external worker instructions.md"
        target.rename(external)
        target.symlink_to(external)
        self.assert_alignment("alignment resource must not be a symlink: factory/WORKER.md")

    def test_probe_failure_fails_alignment(self) -> None:
        with patch.object(contract, "_probe_alignment", return_value=[("probe.forced", "bool budget accepted")]):
            result = contract.alignment_check(self.root)
        self.assertFalse(result["ok"])
        self.assertIn("probe.forced: bool budget accepted", result["errors"])

    def test_missing_fingerprint_file_fails(self) -> None:
        self.fingerprints.unlink()
        self.assert_alignment("references/factory-alignment.json is missing")

    def test_wrong_or_malformed_fingerprint_fails(self) -> None:
        original = self.fingerprints.read_bytes()
        for value, reason in (("0" * 64, "changed since review"), ({}, "malformed entry")):
            with self.subTest(value=value):
                payload = json.loads(original)
                payload["entries"][0]["sha256"] = value
                self.fingerprints.write_text(json.dumps(payload), encoding="utf-8")
                self.assert_alignment(reason)
        self.fingerprints.write_text("{", encoding="utf-8")
        self.assert_alignment("not valid JSON")
        payload = json.loads(original)
        payload["entries"].append(payload["entries"][0])
        self.fingerprints.write_text(json.dumps(payload), encoding="utf-8")
        self.assert_alignment("unexpected or duplicate entry")


if __name__ == "__main__":
    unittest.main(verbosity=2)
