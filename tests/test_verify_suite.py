"""Real subprocess tests for scripts/verify-suite.py at the CLI/discovery boundary.

Each fixture package is a disposable copy of the CLI plus small test modules that
record every import-to-run invocation. The fixtures prove the shipping command
checks prerequisites in the same interpreter and environment before discovery,
runs the suite once, keeps the packaged suite relative to the command and passes
the child status through. They do not prove real test behaviour.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_factory_job import clean_env

PACKAGE = Path(__file__).resolve().parent.parent
CLI = PACKAGE / "scripts" / "verify-suite.py"
REQUIRED_VARIABLES = (
    "DCC_PI_EXECUTABLE",
    "DCC_HERDR_EXECUTABLE",
    "DCC_PI_SDK_MODULE",
    "DCC_B3_NODE",
    "DCC_B3_OPENSPEC",
)
CANARY = "synthetic-canary-token-not-for-output"
# Fixed at the approved base commit: the new guard may only add test modules.
BASELINE_TEST_MODULES = {
    "test_clickup.py", "test_draft.py", "test_e2e_clickup.py", "test_e2e_draft.py",
    "test_e2e_factory.py", "test_e2e_factory_inbox.py", "test_e2e_factory_run.py",
    "test_e2e_knowledge.py", "test_e2e_pi_setup.py", "test_e2e_prepare.py",
    "test_factory_alignment.py", "test_factory_inbox.py", "test_factory_job.py",
    "test_factory_run.py", "test_instruction_packaging.py", "test_knowledge.py",
    "test_prepare.py", "test_setup.py", "test_validate_brief.py", "test_workspace_policy.py",
}

PASSING_MODULE = '''"""Disposable fixture: records every invocation, asserts nothing else."""
import os
import sys
import unittest
from pathlib import Path


class {name}(unittest.TestCase):
    def test_{name}_runs_once(self) -> None:
        record = Path(os.environ["DCC_TEST_VERIFY_RECORD"])
        with record.open("a", encoding="utf-8") as handle:
            handle.write(
                "|".join((Path(__file__).resolve().as_posix(), sys.executable,
                          os.environ.get("DCC_TEST_VERIFY_CANARY", ""))) + "\\n"
            )
'''

FAILING_MODULE = '''"""Disposable fixture: fails after recording its single invocation."""
import os
import unittest
from pathlib import Path


class Failure(unittest.TestCase):
    def test_fails(self) -> None:
        Path(os.environ["DCC_TEST_VERIFY_RECORD"]).write_text("ran\\n", encoding="utf-8")
        self.fail("fixture failure")
'''


class SuiteFixture:
    """Disposable relocated package: CLI, fixture tests, record file and empty home."""

    def __init__(self, root: Path) -> None:
        self.root = root
        scripts = root / "scripts"
        scripts.mkdir(parents=True)
        self.cli = scripts / "verify-suite.py"
        shutil.copyfile(CLI, self.cli)
        self.cli.chmod(0o755)
        self.tests = root / "tests"
        self.tests.mkdir()
        self.record = root / "invocations.txt"
        self.cwd = root / "unrelated cwd"
        self.cwd.mkdir()
        self.home = root / "empty home"
        self.home.mkdir()

    def add_test(self, module: str, source: str) -> None:
        (self.tests / module).write_text(source, encoding="utf-8")

    def complete_environment(self) -> dict[str, str]:
        tools = self.root / "tools"
        tools.mkdir(exist_ok=True)
        values: dict[str, str] = {}
        for name, executable in (
            ("DCC_PI_EXECUTABLE", True),
            ("DCC_HERDR_EXECUTABLE", True),
            ("DCC_PI_SDK_MODULE", False),
            ("DCC_B3_NODE", True),
            ("DCC_B3_OPENSPEC", False),
        ):
            path = tools / f"{name.lower()}{'.bin' if executable else '.js'}"
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755 if executable else 0o644)
            values[name] = str(path)
        return values

    def environment(self, **overrides: str | None) -> dict[str, str]:
        env = clean_env(self.home) | {
            "DCC_TEST_VERIFY_RECORD": str(self.record),
            "DCC_TEST_VERIFY_CANARY": CANARY,
            "CLICKUP_TOKEN": CANARY,
        }
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def run(self, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(self.cli), *args],
            cwd=str(self.cwd), env=env, capture_output=True, text=True, check=False, timeout=120,
        )

    def records(self) -> list[list[str]]:
        if not self.record.exists():
            return []
        return [line.split("|") for line in self.record.read_text(encoding="utf-8").splitlines()]


class PrerequisiteBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="dcc-verify-suite-")
        self.addCleanup(temp.cleanup)
        self.fx = SuiteFixture(Path(temp.name))
        self.fx.add_test("test_marker_a.py", PASSING_MODULE.format(name="MarkerA"))

    def test_missing_prerequisites_stop_before_any_discovery(self) -> None:
        result = self.fx.run(self.fx.environment())
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, output)
        self.assertEqual(self.fx.records(), [], "the suite reached a test module")
        self.assertIn("no test was discovered, imported or started", result.stderr)
        for name in REQUIRED_VARIABLES:
            self.assertEqual(result.stderr.count(f"FAIL  {name}:"), 1, result.stderr)
        self.assertNotIn(CANARY, output, "the command printed an environment value")
        self.assertFalse(any(self.fx.tests.rglob("__pycache__")), "importing happened")

    def test_invalid_paths_are_reported_together_before_discovery(self) -> None:
        tools = self.fx.root / "tools"
        tools.mkdir()
        non_executable = tools / "not-executable"
        non_executable.write_text("#!/bin/sh\n", encoding="utf-8")
        non_executable.chmod(0o644)
        a_directory = tools / "directory"
        a_directory.mkdir()
        result = self.fx.run(self.fx.environment(
            DCC_PI_EXECUTABLE=str(non_executable),
            DCC_HERDR_EXECUTABLE=str(tools / "missing-herdr"),
            DCC_PI_SDK_MODULE=str(a_directory),
            DCC_B3_NODE="relative/node",
            DCC_B3_OPENSPEC="",
        ))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(self.fx.records(), [])
        for name in REQUIRED_VARIABLES:
            self.assertEqual(result.stderr.count(f"FAIL  {name}:"), 1, result.stderr)
        self.assertIn("not executable", result.stderr)
        self.assertIn("does not name an existing file", result.stderr)
        self.assertIn("is not an absolute path", result.stderr)
        self.assertIn("is not set", result.stderr)
        self.assertNotIn(CANARY, result.stdout + result.stderr)

    def test_check_mode_never_runs_discovery(self) -> None:
        complete = self.fx.run(self.fx.environment(**self.fx.complete_environment()), "--check")
        self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)
        self.assertIn("PASS  DCC_PI_EXECUTABLE", complete.stdout)
        self.assertIn("prerequisite check only", complete.stdout)
        self.assertEqual(self.fx.records(), [], "--check discovered a test")
        bare = self.fx.run(self.fx.environment(), "--check")
        self.assertEqual(bare.returncode, 2, bare.stdout + bare.stderr)
        self.assertEqual(self.fx.records(), [], "--check discovered a test")


class SuiteInvocationTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="dcc-verify-suite-")
        self.addCleanup(temp.cleanup)
        self.fx = SuiteFixture(Path(temp.name))

    def test_complete_environment_runs_the_packaged_suite_once(self) -> None:
        self.fx.add_test("test_marker_a.py", PASSING_MODULE.format(name="MarkerA"))
        self.fx.add_test("test_marker_b.py", PASSING_MODULE.format(name="MarkerB"))
        result = self.fx.run(self.fx.environment(**self.fx.complete_environment()))
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        records = self.fx.records()
        self.assertEqual(len(records), 2, f"expected one run per module, got {records}")
        markers = sorted(record[0] for record in records)
        self.assertEqual(
            markers,
            sorted((self.fx.tests / name).resolve().as_posix() for name in ("test_marker_a.py", "test_marker_b.py")),
        )
        for record in records:
            self.assertEqual(Path(record[1]).resolve(), Path(sys.executable).resolve())
            self.assertEqual(record[2], CANARY, "the child did not inherit the role environment")
        self.assertIn("Ran 2 tests", output)
        self.assertEqual(list(self.fx.cwd.iterdir()), [], "the command wrote into its current directory")
        self.assertFalse(any((PACKAGE / "tests").glob("test_marker_*.py")))

    def test_failing_suite_status_is_passed_through(self) -> None:
        self.fx.add_test("test_marker_fail.py", FAILING_MODULE)
        result = self.fx.run(self.fx.environment(**self.fx.complete_environment()))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.fx.records(), [["ran"]])
        self.assertIn("FAILED", result.stderr)
        self.assertIn("fixture failure", result.stderr)

    def test_missing_suite_is_refused_without_discovery(self) -> None:
        shutil.rmtree(self.fx.tests)
        result = self.fx.run(self.fx.environment(**self.fx.complete_environment()))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("FAIL  suite:", result.stderr)
        self.assertNotIn("ran 0 tests", result.stdout.lower())


class ShipmentCoverageTest(unittest.TestCase):
    def test_existing_test_modules_are_still_packaged(self) -> None:
        present = {path.name for path in (PACKAGE / "tests").glob("test_*.py")} - {"test_verify_suite.py"}
        self.assertEqual(present, BASELINE_TEST_MODULES, "an existing test module was dropped or renamed")


if __name__ == "__main__":
    unittest.main()
