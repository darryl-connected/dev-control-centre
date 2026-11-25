"""Real local Pi/inbox protocol, without claiming Linux isolation or file-open tracing."""

import unittest

from test_e2e_factory_inbox import (
    DISABLED,
    EXISTS,
    INVALID_EVENT,
    REVIEW,
    WRITER,
    WRONG,
    PiFixture,
    snapshot,
    until,
)
from test_factory_inbox import evidence_dir, put, sha


class LocalPiFixture(PiFixture):
    def execution_prefix(self):
        # The separate Linux suite still uses unshare and its original probes.
        return []


class NativeInboxTest(unittest.TestCase):
    def fixture(self):
        return LocalPiFixture(self, evidence_dir("handoff-native-"))

    def enable(self, r, tty):
        offset = tty.action("enable " + str(r.registration))
        # A pending event may replace the enabled toast within the same repaint.
        # Require the exact persistent opt-in binding rather than that transient toast.
        state = {"session": r.session, "file": str(r.transcript()), "registration": str(r.registration),
                 "hash": sha(r.registration.read_bytes()), "enabled": True}
        until(lambda: r.states() and r.states()[-1] == state, "opt-in state was not persisted with the exact binding")
        return offset

    def test_opt_in_disable_resume_and_once_only_delivery(self):
        r = self.fixture()
        with r.terminal("initial") as tty:
            transcript = r.establish(tty)
            r.register(transcript)
            r.attempt("writer", "a1")
            expected = r.publish("writer", "a1", "reported")
            before = snapshot(r.inbox)
            stable = r.protected()
            r.assert_no_delivery(0, "unapproved inbox delivered a notice")
            self.assertEqual(r.states(), [])
            self.enable(r, tty)
            r.observe_notice(expected, WRITER, 1)
            tty.command("disable", DISABLED)
            self.assertEqual([s["enabled"] for s in r.states()], [True, False])
            self.assertEqual(snapshot(r.inbox), before)
            self.assertEqual(r.protected(), stable)
        r.attempt("reviewer", "a1")
        reviewed = r.publish("reviewer", "a1", "changes_requested", derive=True)
        before = snapshot(r.inbox)
        with r.terminal("disabled-resume", resume=transcript) as tty:
            tty.command("status", DISABLED)
            r.assert_no_delivery(1, "disabled resume delivered pending review")
            self.enable(r, tty)
            r.observe_notice(reviewed, REVIEW.format("changes_requested"), 2)
        with r.terminal("enabled-resume", resume=transcript) as tty:
            tty.detail("duplicate.")
            r.assert_no_delivery(2, "retained records delivered again after restart")
        self.assertEqual(snapshot(r.inbox), before)
        self.assertEqual(r.protected(), stable)
        r.assert_offline_effects()

    def test_wrong_session_refuses_pending_registered_event(self):
        r = self.fixture()
        with r.terminal("owner") as tty:
            transcript = r.establish(tty)
            r.register(transcript)
            r.attempt("writer", "a1")
            expected = r.publish("writer", "a1", "reported")
        before = snapshot(r.inbox)
        with r.terminal("unrelated", session="unrelated") as tty:
            r.establish(tty, "unrelated")
            tty.command("enable " + str(r.registration), WRONG)
            r.assert_no_delivery(0, "the wrong conversation requested a callback")
            self.assertEqual(r.states(), [])
        self.assertEqual(snapshot(r.inbox), before)
        with r.terminal("resumed-owner", resume=transcript) as tty:
            self.enable(r, tty)
            r.observe_notice(expected, WRITER, 1)
        r.assert_offline_effects()

    def test_invalid_event_binding_delivers_nothing_then_valid_record_delivers_once(self):
        r = self.fixture()
        with r.terminal("invalid-binding") as tty:
            transcript = r.establish(tty)
            r.register(transcript)
            slot = r.attempt("reviewer", "a1")
            expected = r.publish("reviewer", "a1", "approved", derive=True)
            before = snapshot(r.inbox)
            # Exercise the real publisher's immutability boundary first.
            alternate = put(r.root / "alternate.receipt", r.receipt("a1", "blocked"))
            r.cli(*r.publish_args("reviewer", "a1", "blocked", report=alternate), "--approve", error=EXISTS)
            self.assertEqual(snapshot(r.inbox), before)
            # Change only the candidate binding in a disposable wire record.
            event = slot / "event.json"
            retained = event.rename(r.root / "correct-event.json")
            put(event, expected | {"candidate_digest": "0" * 64}, 0o400)
            invalid = snapshot(r.inbox)
            offset = self.enable(r, tty)
            r.assert_no_delivery(0, "unbound event reached the real Pi consumer")
            tty.detail(INVALID_EVENT, offset)
            self.assertEqual(snapshot(r.inbox), invalid)
            retained.replace(event)
            r.observe_notice(expected, REVIEW.format("approved"), 1)
            r.assert_no_delivery(1, "restored valid event delivered more than once")
            self.assertEqual(snapshot(r.inbox), before)
        r.assert_offline_effects()


if __name__ == "__main__":
    unittest.main()
