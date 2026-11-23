"""Unit-level routing and preview checks for the coordinator-invoked loop."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / "scripts/lib"))
sys.path.insert(0, str(KIT / "tests"))

import factory_run as loop
from test_e2e_factory_run import HERDR_EXE, PI_EXE, LoopFixture, put


class RoutePolicy(unittest.TestCase):
    def test_declared_defaults_and_switch_rules(self):
        loop.validate_routes(loop.ROUTES)
        self.assertEqual(loop.route_text(loop.ROUTES["writer"]), "deepseek/deepseek-flash")
        self.assertEqual(loop.ROUTES["coordinator"]["reasoning"], "high")
        self.assertEqual(loop.ROUTES["reviewer"]["reasoning"], "high")
        self.assertEqual(loop.ROUTES["writer"]["reasoning"], "model-default")

    def test_reviewer_or_coordinator_cannot_take_the_writer_route(self):
        for role in ("reviewer", "coordinator"):
            routes = {name: dict(value) for name, value in loop.ROUTES.items()}
            routes[role] = dict(loop.WRITER)
            with self.subTest(role=role), self.assertRaises(loop.RunError):
                loop.validate_routes(routes)

    def test_reasoning_and_model_identity_are_bound(self):
        routes = {name: dict(value) for name, value in loop.ROUTES.items()}
        routes["reviewer"]["reasoning"] = "low"
        with self.assertRaises(loop.RunError):
            loop.validate_routes(routes)
        with self.assertRaises(loop.RunError):
            loop.parse_route("deepseek", role="writer")
        with self.assertRaises(loop.RunError):
            loop.parse_route("Something Else", role="writer")

    def test_attempt_ids_are_fresh_per_role(self):
        state = {"attempts": [{"role": "writer", "attempt": "a1"}, {"role": "writer", "attempt": "a2"},
                              {"role": "reviewer", "attempt": "a1"}]}
        self.assertEqual(loop.next_attempt(state, "writer"), "a3")
        self.assertEqual(loop.next_attempt(state, "reviewer"), "a2")

    def test_per_attempt_allowance_is_conserved_and_independent(self):
        state: dict = {"policy": loop.POLICY, "attempt_limits": dict(loop.ATTEMPT_ENVELOPES),
                       "attempt_allocations": {}, "attempt_usage": {}, "attempt_kinds": {}, "attempts": [],
                       "usage": {"writer": {"calls": 0, "minutes": 0}, "reviewer": {"calls": 0, "minutes": 0},
                                 "coordinator": {"calls": 0, "minutes": 0}, "shared": {"calls": 0, "minutes": 0}},
                       "events": [], "overall_limit": None}
        loop.allocate_attempt(state, "writer", "a1", "initial")
        loop.spend(state, "writer.a1:60:25")
        self.assertEqual(state["attempt_usage"]["writer.a1"], {"calls": 60, "minutes": 25})
        loop.spend(state, "writer.a1:1:1")
        self.assertEqual(state["attempt_usage"]["writer.a1"]["calls"], 61, "same-ID spending must be conserved")
        self.assertEqual(state["usage"]["shared"]["calls"], 61)
        with self.assertRaises(loop.RunError) as caught:
            loop.require_dispatch_allowance(state, "writer", "a1")
        self.assertEqual(getattr(caught.exception, "code", None), "budget-exhausted")
        loop.allocate_attempt(state, "writer", "a2", "repair")
        self.assertEqual(loop.attempt_remaining(state, "writer.a2"), (15, 30))
        self.assertEqual(state["blocked"]["scope"], "attempt")

    def test_optional_overall_derivation_has_no_double_count(self):
        state: dict = {"policy": loop.POLICY, "attempt_limits": dict(loop.ATTEMPT_ENVELOPES),
                       "attempt_allocations": {}, "attempt_usage": {}, "attempt_kinds": {}, "attempts": [],
                       "usage": {"writer": {"calls": 3, "minutes": 3}, "reviewer": {"calls": 0, "minutes": 0},
                                 "coordinator": {"calls": 1, "minutes": 1}, "shared": {"calls": 4, "minutes": 4}},
                       "events": [], "overall_limit": {"calls": 4, "minutes": 4}}
        self.assertEqual(loop.overall_remaining(state), (0, 0))
        loop.allocate_attempt(state, "writer", "a1", "initial")
        with self.assertRaises(loop.RunError):
            loop.require_dispatch_allowance(state, "writer", "a1")


@unittest.skipUnless(PI_EXE and os.path.isabs(PI_EXE) and HERDR_EXE and os.path.isabs(HERDR_EXE),
                     "DCC_PI_EXECUTABLE and DCC_HERDR_EXECUTABLE are required for preview")
class PreviewBoundary(unittest.TestCase):
    def fixture(self) -> LoopFixture:
        return LoopFixture(self)

    def test_preview_is_read_only_and_bound_to_listener_and_baseline(self):
        r = self.fixture()
        r.register()
        before = r.protected()
        self.assertEqual(r.preview().returncode, 0)
        self.assertTrue(r.plan.is_file())
        self.assertEqual(r.plan.stat().st_mode & 0o777, 0o400)
        self.assertEqual(r.protected(), before)
        self.assertFalse(r.writer.exists() or r.reviewer.exists())
        self.assertEqual(r.preview(check=False).returncode, 1, "a second preview must not replace the plan")
        # Target drift after the preview is refused by launch.
        (r.repo / "file.txt").write_bytes(b"changed after snapshot\n")
        launched = r.loop("launch", r.plan, "--state", r.state, "--approve")
        self.assertEqual(launched.returncode, 1)
        self.assertIn("preflight-failed", launched.stderr)
        self.assertFalse(r.writer.exists())

    def test_missing_and_mismatched_listener_are_refused(self):
        r = self.fixture()
        missing = r.preview(check=False)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("invalid-listener", missing.stderr)
        r.register()
        registration = json.loads(r.registration.read_text())
        registration["manifest_digest"] = "f" * 64
        r.registration.chmod(0o600)
        put(r.registration.with_name("bad.json"), registration, 0o400)
        r.registration.unlink()
        r.registration.with_name("bad.json").rename(r.registration)
        refused = r.preview(check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("unverified-listener", refused.stderr)
        self.assertFalse(r.writer.exists())

    def test_existing_worktree_blocks_new_launch_plan(self):
        r = self.fixture()
        r.register()
        r.writer.mkdir()
        refused = r.preview(check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("worktree-exists", refused.stderr)

    def test_launch_without_approval_has_no_side_effects(self):
        r = self.fixture()
        r.register()
        self.assertEqual(r.preview().returncode, 0)
        before = r.protected()
        refused = r.loop("launch", r.plan, "--state", r.state)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("approval-required", refused.stderr)
        self.assertFalse(r.state.exists() or r.writer.exists())
        self.assertEqual(r.protected(), before)


if __name__ == "__main__":
    unittest.main()
