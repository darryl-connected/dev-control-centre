#!/usr/bin/env python3
"""Coordinator-invoked Pi + Herdr factory loop. Preview, dispatch, review, handoff."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import factory_contract as contract
import factory_run as loop


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, f"invalid-request: {message}\n")


def emit(row: dict) -> None:
    print(json.dumps(row, indent=2, sort_keys=True))


def command_preview(args: argparse.Namespace) -> int:
    plan = loop.preview(
        args.manifest, registration=args.registration, writer_worktree=args.writer_worktree,
        reviewer_worktree=args.reviewer_worktree, plan_out=args.plan_out,
        herdr_executable=args.herdr, pi_executable=args.pi, session_dir=args.session_dir,
        agent_dir=args.agent_dir, extension=args.extension, pi_arg=args.pi_arg,
        alternate_writer=args.alternate_writer, brief=args.brief,
        writer_attempt_limit=args.writer_attempt_limit, reviewer_attempt_limit=args.reviewer_attempt_limit,
        repair_writer_limit=args.repair_writer_limit, rereview_limit=args.rereview_limit,
        overall_limit=args.overall_limit, used_shared=args.used_shared, used_writer=args.used_writer,
        used_reviewer=args.used_reviewer, used_coordinator=args.used_coordinator,
        manual_fixture=args.manual_fixture)
    emit({"status": "previewed", "activates_nothing": True, "plan": plan})
    return 0


def verify_plan(plan_path: Path) -> dict:
    plan = loop.read_json(plan_path, "invalid-plan")
    digest = plan.pop("plan_digest", None)
    if not digest or digest != contract.sha256_bytes((contract.canonical_json(plan)).encode()):
        raise loop.RunError("stale-plan", "plan bytes do not match the approved digest")
    plan["plan_digest"] = digest
    if plan.get("policy") != loop.POLICY:
        raise loop.RunError("stale-plan", "legacy budget policy plan; re-preview this job with explicit consent")
    if any(loop.identity_override(arg) for arg in plan.get("tools", {}).get("pi_args", [])):
        raise loop.RunError("invalid-route", "pi arguments cannot override the approved role provider, model or reasoning identity")
    loop.validate_routes(plan["routes"])
    manifest = loop.load_manifest(plan["manifest"])
    if contract.manifest_digest(manifest) != plan["manifest_digest"]:
        raise loop.RunError("stale-plan", "manifest changed since preview")
    brief = Path(plan["brief"])
    if not brief.is_file() or loop.digest_file(brief) != plan["brief_sha256"]:
        raise loop.RunError("stale-plan", "rendered brief changed since preview")
    if brief.read_bytes() != contract.render_brief(manifest).encode():
        raise loop.RunError("invalid-brief", "brief is not the exact rendered brief for this manifest")
    binding = loop.listener_binding(plan["listener"]["registration"], manifest,
                                    manual_fixture=plan.get("manual_fixture", False))
    if binding["registration_sha256"] != plan["listener"]["registration_sha256"]:
        raise loop.RunError("stale-plan", "listener registration changed since preview")
    result = contract.preflight(manifest)
    if not result["ok"]:
        raise loop.RunError("preflight-failed", "; ".join(result["errors"][:6]))
    for role in ("writer", "reviewer"):
        path = Path(plan["worktrees"][role])
        if path.exists():
            raise loop.RunError("worktree-exists", f"{role} worktree already exists")
    return plan


def command_launch(args: argparse.Namespace) -> int:
    if not args.approve:
        raise loop.RunError("approval-required", "launch requires explicit --approve")
    plan_path = loop.canonical(args.plan, "invalid-plan")
    plan = verify_plan(plan_path)
    state_path = loop.canonical(args.state, "unsafe-state")
    loop.private_dir(state_path.parent, "unsafe-state")
    if state_path.exists():
        raise loop.RunError("record-exists", "this plan already has loop state")
    manifest = loop.load_manifest(plan["manifest"])
    early = {"version": 1, "task": plan["task"], "goal": plan["goal"], "manifest": plan["manifest"],
             "manifest_digest": plan["manifest_digest"], "repo": plan["repo"], "base": plan["base"],
             "plan_digest": plan["plan_digest"], "listener": plan["listener"], "routes": plan["routes"],
             "writer_route": plan["routes"]["writer"], "writer_alternates": plan["writer_alternates"],
             "worktrees": plan["worktrees"], "budgets": plan["budgets"], "policy": plan["policy"],
             "attempt_limits": plan["attempt_limits"], "overall_limit": plan["overall_limit"],
             "brief": plan["brief"], "brief_sha256": plan["brief_sha256"],
             "manual_fixture": plan.get("manual_fixture", False), "tools": plan["tools"],
             "state_dir": str(state_path.parent), "state_file": str(state_path), "herdr_session": plan["herdr_session"],
             "usage": {name: dict(value) for name, value in plan["initial_usage"].items()},
             "attempt_allocations": {}, "attempt_usage": {}, "attempt_kinds": {},
             "attempts": [], "events": [], "repairs": 0, "phase": "pre-dispatch"}
    try:
        loop.allocate_attempt(early, "writer", "a1", "initial")
        loop.require_dispatch_allowance(early, "writer", "a1")
    except loop.RunError:
        early["phase"] = "stopped"
        loop.save_state(state_path, early)
        raise
    writer = Path(plan["worktrees"]["writer"])
    branch = "dcc-" + loop.SLUG_RE.sub("-", plan["task"].lower()).strip("-")[:24] + "-writer"
    try:
        result = loop.run(["git", "-C", manifest["repo"], "worktree", "list", "--porcelain"])
        if f"branch refs/heads/{branch}" in result.stdout:
            raise loop.RunError("branch-exists", f"writer branch {branch} already exists")
        loop.git(Path(manifest["repo"]), "worktree", "add", "-b", branch, str(writer), plan["base"]["commit"])
        loop.materialize_baseline(manifest, writer)
    except loop.RunError as exc:
        raise loop.RunError("worktree-refused", exc.detail) from exc
    state: dict = {
        "version": 1, "task": plan["task"], "goal": plan["goal"], "manifest": plan["manifest"],
        "manifest_digest": plan["manifest_digest"], "repo": plan["repo"], "base": plan["base"],
        "plan_digest": plan["plan_digest"], "listener": plan["listener"], "routes": plan["routes"],
        "writer_route": plan["routes"]["writer"], "writer_alternates": plan["writer_alternates"],
        "worktrees": plan["worktrees"], "budgets": plan["budgets"], "policy": plan["policy"],
        "attempt_limits": plan["attempt_limits"], "overall_limit": plan["overall_limit"],
        "brief": plan["brief"], "brief_sha256": plan["brief_sha256"],
        "manual_fixture": plan.get("manual_fixture", False), "tools": plan["tools"],
        "state_dir": str(state_path.parent), "state_file": str(state_path), "herdr_session": plan["herdr_session"],
        "approved_at": loop.now(), "approved": True, "phase": "launching", "attempts": [],
        "usage": {name: dict(value) for name, value in plan["initial_usage"].items()},
        "attempt_allocations": early["attempt_allocations"],
        "attempt_usage": early["attempt_usage"], "attempt_kinds": early["attempt_kinds"],
        "events": early["events"], "repairs": 0,
    }
    loop.event(state, "launch-approved", plan_digest=plan["plan_digest"],
               writer=loop.route_text(plan["routes"]["writer"]),
               coordinator=loop.route_text(plan["routes"]["coordinator"]),
               reviewer=loop.route_text(plan["routes"]["reviewer"]))
    try:
        created = loop.herdr(Path(plan["tools"]["herdr"]), plan["herdr_session"], "workspace", "create",
                             "--cwd", str(writer), "--label", f"dcc {plan['task']} writer", "--no-focus")
    except loop.RunError as exc:
        state["blocked"] = {"reason": "herdr-failed", "detail": exc.detail, "at": loop.now()}
        loop.save_state(state_path, state)
        raise loop.RunError("herdr-failed", "writer worktree exists but no pane was created; state recorded") from exc
    workspace = loop.find_id(created, "workspace_id")
    pane = loop.find_id(created, "pane_id")
    if not workspace or not pane:
        state["blocked"] = {"reason": "herdr-failed", "detail": "workspace create returned no ids", "at": loop.now()}
        loop.save_state(state_path, state)
        raise loop.RunError("herdr-failed", "workspace create returned no pane identity")
    state["herdr"] = {"workspace_id": workspace, "writer_pane": pane}
    loop.event(state, "workspace-created", workspace=workspace, pane=pane)
    try:
        loop.require_dispatch_allowance(state, "writer", "a1")
    except loop.RunError:
        loop.save_state(state_path, state)
        raise
    loop.register_attempt(state, "writer", "a1", "initial")
    loop.safe_dispatch(state, "writer", "a1", "", str(writer))
    loop.save_state(state_path, state)
    emit({"status": "writer-dispatched", "attempt": "a1", "workspace": workspace, "pane": pane,
          "worktree": str(writer), "writer": loop.route_text(state["writer_route"]),
          "coordinator": loop.route_text(state["routes"]["coordinator"]),
          "reviewer": loop.route_text(state["routes"]["reviewer"]), "approved": True})
    return 0


def command_advance(args: argparse.Namespace) -> int:
    emit(loop.advance(args.state, spend_raw=args.spend, manual=args.manual))
    return 0


def command_handoff(args: argparse.Namespace) -> int:
    emit(loop.handoff(args.state, approve=args.approve))
    return 0


def command_switch(args: argparse.Namespace) -> int:
    emit(loop.switch_writer(args.state, model=args.to, approve=args.approve, reason=args.reason))
    return 0


def command_stop(args: argparse.Namespace) -> int:
    emit(loop.stop(args.state, reason=args.reason, role=args.role))
    return 0


def command_status(args: argparse.Namespace) -> int:
    emit(loop.status(args.state))
    return 0


def build_parser() -> Parser:
    parser = Parser(prog="factory-run", description=__doc__, allow_abbrev=False)
    routes = parser.add_subparsers(dest="command", required=True)

    preview = routes.add_parser("preview", help="read-only plan for one approved job", allow_abbrev=False)
    preview.add_argument("manifest")
    preview.add_argument("--registration", required=True)
    preview.add_argument("--writer-worktree", required=True)
    preview.add_argument("--reviewer-worktree", required=True)
    preview.add_argument("--plan-out", required=True)
    preview.add_argument("--herdr", required=True)
    preview.add_argument("--pi", required=True)
    preview.add_argument("--session-dir", required=True)
    preview.add_argument("--agent-dir", required=True)
    preview.add_argument("--brief", required=True)
    preview.add_argument("--writer-attempt-limit", default="")
    preview.add_argument("--reviewer-attempt-limit", default="")
    preview.add_argument("--repair-writer-limit", default="")
    preview.add_argument("--rereview-limit", default="")
    preview.add_argument("--overall-limit", default="")
    preview.add_argument("--used-shared", default="")
    preview.add_argument("--used-writer", default="")
    preview.add_argument("--used-reviewer", default="")
    preview.add_argument("--used-coordinator", default="")
    preview.add_argument("--manual-fixture", action="store_true")
    preview.add_argument("--extension")
    preview.add_argument("--pi-arg", action="append", default=[])
    preview.add_argument("--alternate-writer", action="append", default=[])

    launch = routes.add_parser("launch", help="create the writer worktree/pane and submit one prompt",
                               allow_abbrev=False)
    launch.add_argument("plan")
    launch.add_argument("--state", required=True)
    launch.add_argument("--approve", action="store_true")

    advance = routes.add_parser("advance", help="act only on fixed published records", allow_abbrev=False)
    advance.add_argument("state")
    advance.add_argument("--spend", default="")
    advance.add_argument("--manual", action="store_true")

    handoff = routes.add_parser("handoff", help="stage only the accepted exact candidate", allow_abbrev=False)
    handoff.add_argument("state")
    handoff.add_argument("--approve", action="store_true")

    switch = routes.add_parser("switch-writer", help="approved writer-only provider switch",
                               allow_abbrev=False)
    switch.add_argument("state")
    switch.add_argument("--to", required=True)
    switch.add_argument("--reason", required=True)
    switch.add_argument("--approve", action="store_true")

    stop = routes.add_parser("stop", help="record a resumable stop without dispatch", allow_abbrev=False)
    stop.add_argument("state")
    stop.add_argument("--reason", required=True)
    stop.add_argument("--role", default="")

    state = routes.add_parser("status", help="read-only lifecycle and record state", allow_abbrev=False)
    state.add_argument("state")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    handler = {
        "preview": command_preview, "launch": command_launch, "advance": command_advance,
        "handoff": command_handoff, "switch-writer": command_switch, "stop": command_stop,
        "status": command_status,
    }[args.command]
    try:
        return handler(args)
    except loop.RunError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (contract.ContractError, OSError, ValueError) as error:
        print(f"failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
