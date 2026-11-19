#!/usr/bin/env python3
"""
Offline tests for scripts/validate-brief.py.

The legacy checker is advisory now, so these tests pin that it still catches
empty or missing contract fields, requires every authorisation line separately,
accepts a historical short SHA only with an honest warning, and never presents
itself as the authorising gate.

Run: python -B -m unittest discover -s tests -p 'test_validate_brief.py' -v
     python -B tests/test_validate_brief.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
SCRIPT = PACKAGE / "scripts" / "validate-brief.py"

VALID = """You are a legacy worker agent.

BEFORE ANYTHING ELSE: read AGENTS.md at the repository root.

Authorisation: do not hand off. Do not spawn sub-agents. Do not create worktrees or panes. Do not commit. Do not push. Do not use the network.

TASK DEMO-01. Add one check.

Base commit: {base}
Allowed paths: scripts/demo.sh. Everything else is out of scope.
Out of scope: no runtime change.

Required outcome: the script exits nonzero on a missing argument.
Review tier: A, test-only change with no runtime code.
Acceptance examples: no argument -> exit 2 -> observed by running it.
Risk cases: an empty string argument.
Boundaries: real shell, nothing mocked.
Defect demonstration: remove the argument check; the assertion must fail.
What each guard does not prove: a call from another script.

Evidence you must produce: command output and exit codes.
Verification commands: bash scripts/demo.sh.
Budget: 15 minutes, 30 tool calls.
Stopping point: stop at the limit and report.

FINISH: report outcome, commands, and anything NOT VERIFIED.
"""

SHA = "6ed6526"


def brief(**overrides: str) -> str:
    values = {"base": SHA}
    values.update(overrides)
    return VALID.format(**values)


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class ValidateBriefTest(unittest.TestCase):
    def write(self, text: str) -> str:
        temp = tempfile.TemporaryDirectory(prefix="factory-brief-")
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "brief.md"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_compliant_brief_passes_as_advisory(self) -> None:
        result = run(self.write(brief()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ADVISORY OK", result.stdout)
        self.assertIn("not the authorising gate", result.stdout)

    def test_missing_fields_are_named(self) -> None:
        text = brief().replace("What each guard does not prove: a call from another script.\n", "")
        text = text.replace("Out of scope: no runtime change.\n", "")
        result = run(self.write(text))
        self.assertEqual(result.returncode, 1)
        self.assertIn("what each guard does not prove", result.stdout)
        self.assertIn("explicit out of scope", result.stdout)

    def test_empty_labels_fail(self) -> None:
        text = brief().replace("Risk cases: an empty string argument.", "Risk cases:").replace(
            "Required outcome: the script exits nonzero on a missing argument.",
            "Required outcome:",
        )
        result = run(self.write(text))
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing or empty field: risk cases", result.stdout)
        self.assertIn("acceptance criteria", result.stdout)

    def test_each_authorisation_line_is_required(self) -> None:
        text = brief().replace("Do not push. ", "").replace("Do not use the network.", "")
        text = text.replace("read AGENTS.md at the repository root", "read the repository rules")
        with_handoffs = brief().replace("Do not spawn sub-agents. ", "")
        result = run(self.write(text))
        self.assertEqual(result.returncode, 1)
        self.assertIn("no pushes", result.stdout)
        self.assertIn("no network", result.stdout)
        self.assertIn("AGENTS.md", result.stdout)
        result = run(self.write(with_handoffs))
        self.assertEqual(result.returncode, 1)
        self.assertIn("no sub-agents", result.stdout)

    def test_base_commit_is_format_checked_only_without_repo(self) -> None:
        result = run(self.write(brief(base="master")))
        self.assertEqual(result.returncode, 1)
        self.assertIn("base commit", result.stdout)

        short = run(self.write(brief()))
        self.assertEqual(short.returncode, 0, short.stdout)
        self.assertIn("format checked only", short.stdout)

    def test_repo_option_verifies_the_commit(self) -> None:
        result = run(self.write(brief(base="a" * 40)), "--repo", str(PACKAGE))
        self.assertEqual(result.returncode, 1)
        self.assertIn("commit does not exist", result.stdout)

    def test_budget_needs_both_limits(self) -> None:
        without_calls = brief().replace("Budget: 15 minutes, 30 tool calls.", "Budget: 15 minutes.")
        result = run(self.write(without_calls))
        self.assertEqual(result.returncode, 1)
        self.assertIn("tool-call limit", result.stdout)

        without_minutes = brief().replace("Budget: 15 minutes, 30 tool calls.", "Budget: 30 tool calls.")
        result = run(self.write(without_minutes))
        self.assertEqual(result.returncode, 1)
        self.assertIn("wall-clock limit", result.stdout)

    def test_review_tier_must_be_a_or_b(self) -> None:
        result = run(self.write(brief().replace("Review tier: A,", "Review tier: C,")))
        self.assertEqual(result.returncode, 1)
        self.assertIn("review tier must be A or B", result.stdout)

    def test_placeholder_warns_then_fails_under_strict(self) -> None:
        text = brief().replace("report outcome, commands, and anything NOT VERIFIED.", "report outcome under <N> lines.")
        path = self.write(text)
        lenient = run(path)
        self.assertEqual(lenient.returncode, 0, lenient.stdout)
        self.assertIn("WARN", lenient.stdout)

        strict = run(path, "--strict")
        self.assertEqual(strict.returncode, 1)

    def test_unreadable_file_is_a_tool_error(self) -> None:
        result = run("/nonexistent/brief.md")
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot read", result.stderr)

    def test_json_output_is_machine_readable(self) -> None:
        path = self.write(brief())
        result = run(path, "--json")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["advisory"])
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["brief"], path)

    def test_example_template_is_printed(self) -> None:
        result = run("--example")
        self.assertEqual(result.returncode, 0)
        for field in ("Acceptance examples:", "What each guard does not prove:", "Verification commands:"):
            self.assertIn(field, result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
