#!/usr/bin/env python3
"""Inspect and, with explicit approval, configure a personal DCC workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from knowledge_hub import readiness as knowledge_readiness

KIT = Path(__file__).resolve().parents[1]
SKILLS = ("setup", "factory", "grilling")
SHADOW = (
    "A trusted project APPEND_SYSTEM shadows rather than combines with user APPEND_SYSTEM. "
    "Preserving bytes does not preserve effective instructions."
)


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def json_object(data: bytes, path: Path) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def invalid_constant(_: str) -> None:
        raise ValueError("invalid constant")

    try:
        value = json.loads(data, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, RecursionError) as error:
        raise ValueError(f"malformed JSON: {path}") from error
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return value


def local_path(value: str) -> Path:
    if not value or any(ord(char) < 32 for char in value):
        raise ValueError("expected a nonempty local path without control characters")
    path = Path(value).expanduser()
    if ".." in path.parts:
        raise ValueError("use a path without '..' (use pwd -P for the physical directory)")
    return path.absolute()


class Inspection:
    """Remember the file identities needed to reject a changed inspection, never their contents."""

    def __init__(self) -> None:
        self.states: dict[str, Any] = {}

    def stat_path(self, path: Path) -> os.stat_result | None:
        # Validate every component, including broken symlinks, before reading a leaf.
        for parent in reversed(path.parents):
            try:
                info = parent.lstat()
            except FileNotFoundError:
                return None
            if stat.S_ISLNK(info.st_mode):
                raise ValueError(f"symlink not allowed: {parent}")
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"expected directory: {parent}")
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"symlink not allowed: {path}")
        return info

    def directory(self, path: Path, *, required: bool = False) -> bool:
        info = self.stat_path(path)
        if info is None:
            self.states[str(path)] = None
            if required:
                raise ValueError(f"directory does not exist: {path}")
            return False
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"expected directory: {path}")
        self.states[str(path)] = [info.st_dev, info.st_ino, info.st_mode]
        return True

    def file(self, path: Path, *, required: bool = False) -> bytes | None:
        info = self.stat_path(path)
        if info is None:
            self.states[str(path)] = None
            if required:
                raise ValueError(f"missing required file: {path}")
            return None
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"expected regular file: {path}")
        data = path.read_bytes()
        self.states[str(path)] = [
            info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns, hashlib.sha256(data).hexdigest(),
        ]
        return data


def mappings(entries: list[str], stored: bytes | None, path: Path) -> dict[str, str]:
    result = {}
    if not entries and stored is not None:
        recorded = json_object(stored, path).get("repositories")
        if isinstance(recorded, dict) and all(isinstance(value, str) for value in recorded.values()):
            entries = [f"{name}={value}" for name, value in recorded.items()]
        else:
            raise ValueError(f"malformed repository mappings: {path}")
    if not entries:
        raise ValueError("missing named local Git target mapping; supply --repo NAME=PATH")
    for entry in entries:
        name, separator, value = entry.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or name in result:
            raise ValueError("expected unique --repo NAME=PATH mappings")
        result[name] = str(local_path(value))
    return result


def command(name: str, *args: str) -> dict[str, Any]:
    exe = shutil.which(name)
    if exe is None:
        return {"status": "blocked", "reason": f"{name} executable missing"}
    argv = [exe, *args]
    # Neither a version read nor rev-parse needs provider credentials or ambient Git overrides.
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR") if key in os.environ}
    env.update(PI_OFFLINE="1", GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    try:
        child = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False, env=env)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return {"status": "blocked", "argv": argv, "reason": f"{name} local command could not be observed"}
    result = {"argv": argv, "exit": child.returncode, "stdout": child.stdout.strip()}
    if child.returncode != 0 or not child.stdout.strip():
        return result | {"status": "blocked", "reason": f"{name} local command did not produce a successful result"}
    return result | {"status": "working", "scope": "local command only"}


def check_skill_conflicts(check: Inspection, root: Path) -> None:
    if not check.directory(root):
        return
    for child in sorted(root.iterdir()):
        if child.name.startswith(".") or child.name == "node_modules":
            continue
        info = check.stat_path(child)
        if info is None:
            raise ValueError(f"skill discovery changed during inspection: {child}")
        if stat.S_ISDIR(info.st_mode):
            check_skill_conflicts(check, child)
        elif child.suffix == ".md":
            data = check.file(child, required=True)
            assert data is not None
            lines = data.decode("utf-8-sig").splitlines()
            if not lines or not lines[0].startswith("---"):
                continue
            end = next((i for i, line in enumerate(lines[1:], 1) if line.startswith("---")), None)
            if end is None:
                continue
            # Do not implement a second YAML parser. Accept only an unambiguous, simple top-level name
            # and block constructs that could change the mapping (quoted keys, merges, flow YAML, etc.).
            keys = [line for line in lines[1:end] if line and not line[0].isspace() and not line.startswith("#")]
            names = [line for line in keys if re.match(r"name\s*:", line)]
            name = re.fullmatch(r"name\s*:\s*(['\"]?)([a-z0-9-]+)\1(?:\s+#.*)?\s*", names[0]) if len(names) == 1 else None
            if not name or any(not re.match(r"[a-zA-Z][a-zA-Z0-9-]*\s*:", line) for line in keys):
                raise ValueError(f"cannot establish the skill name safely: {child}")
            # Pi falls back to the parent directory when YAML types the name as a non-string.
            label = name[2]
            if not name[1] and (not label[0].isalpha() or label in {"null", "true", "false"}):
                label = child.parent.name
            if label in SKILLS:
                raise ValueError(f"conflicting skill name {label}: {child}")


def guarded_environment(check: Inspection, workspace: Path) -> None:
    home = local_path(str(Path.home()))
    agent = local_path(os.environ.get("PI_CODING_AGENT_DIR") or str(home / ".pi/agent"))
    if workspace == home or any(
        workspace.is_relative_to(path) or path.is_relative_to(workspace) for path in (agent, home / ".agents")
    ):
        raise ValueError("use a personal workspace separate from HOME and the Pi user configuration")
    check.directory(agent)
    user_settings = agent / "settings.json"
    data = check.file(user_settings)
    if data is not None:
        settings = json_object(data, user_settings)
        for key in ("packages", "skills", "extensions"):
            if key in settings and settings[key] != []:
                raise ValueError(f"cannot rule out Pi resource conflicts with user {key} configured in {user_settings}")
    check.file(agent / "APPEND_SYSTEM.md")
    # Executable extensions can supply resources dynamically. Setup never evaluates them.
    for directory in (agent / "extensions", workspace / ".pi/extensions"):
        if check.directory(directory) and any(directory.iterdir()):
            raise ValueError(f"cannot rule out Pi resource conflicts with existing extensions: {directory}")
    for directory in (agent / "skills", home / ".agents/skills", workspace / ".pi/skills",
                      *(parent / ".agents/skills" for parent in (workspace, *workspace.parents))):
        check_skill_conflicts(check, directory)


def inspect(workspace: Path, entries: list[str]) -> tuple[dict, dict[Path, bytes], dict]:
    check = Inspection()
    check.directory(workspace, required=True)
    if workspace.is_relative_to(KIT) or KIT.is_relative_to(workspace):
        raise ValueError("workspace must be separate from the kit directory")
    for parent in (workspace, *workspace.parents):
        if check.stat_path(parent / ".git") is not None:
            raise ValueError(f"workspace is inside a Git checkout: {parent}")
    check.directory(workspace / ".pi")
    check.directory(workspace / ".dcc")
    saved = workspace / ".dcc/workspace.json"
    current = check.file(saved)
    repos = mappings(entries, current, saved)
    repo_results = {}
    for name, value in repos.items():
        repo = Path(value)
        check.directory(repo, required=True)
        if workspace.is_relative_to(repo):
            raise ValueError(f"workspace is inside mapped target {name}: {repo}")
        outcome = command("git", "--no-optional-locks", "-C", value, "rev-parse", "--show-toplevel")
        if outcome.get("status") != "working" or outcome.get("stdout") != value:
            raise ValueError(f"Git read blocked for {name}: {outcome.get('reason', 'supply the Git checkout root')}")
        repo_results[name] = outcome
    guarded_environment(check, workspace)
    skill_paths = [KIT / "skills" / name / "SKILL.md" for name in SKILLS]
    for path in skill_paths:
        check.file(path, required=True)
    template = check.file(KIT / "templates/pi/APPEND_SYSTEM.md", required=True)
    assert template is not None
    desired = {
        workspace / ".pi/settings.json": json_bytes({"skills": [str(path) for path in skill_paths]}),
        workspace / ".pi/APPEND_SYSTEM.md": template,
        saved: json_bytes({"version": 1, "workspace": str(workspace), "kit": str(KIT), "repositories": repos}),
    }
    actions = {}
    for path, content in desired.items():
        on_disk = check.file(path)
        if on_disk is not None:
            if path.suffix == ".json":
                json_object(on_disk, path)
            if on_disk != content:
                raise ValueError(f"conflict: existing {path} is not an identical kit resource; no merge or overwrite")
        actions[str(path.relative_to(workspace))] = {
            "action": "unchanged" if on_disk is not None else "create", "sha256": hashlib.sha256(content).hexdigest(),
        }
    plan = {"version": 1, "workspace": str(workspace), "repositories": repos,
            "instruction_precedence": SHADOW, "actions": actions, "preconditions": check.states}
    readiness = {
        "workspace_configuration": "configured" if all(item["action"] == "unchanged" for item in actions.values()) else "planned",
        "local_checks": {"pi": command("pi", "--version"), "herdr": command("herdr", "--version"), "repositories": repo_results},
        "capabilities": {
            "knowledge_integration": knowledge_readiness(workspace, (KIT, *(Path(path) for path in repos.values()))),
            "shared_meeting_notes": "not established; deferred",
            "fathom": "optional; NOT VERIFIED",
            "clickup": "standalone read-only reader available; authentication not checked",
            "context_retrieval": "selected-task preparation available locally; no task assessment observed by setup",
            "live_factory": "unsupported: not implemented",
            "provider_fallback": "unsupported: not implemented",
            "full_task_start": "blocked: OpenSpec drafting and live factory launch are unsupported",
        },
        "workflow": "blocked; registration is not overall workflow readiness or launch permission",
        "verification": {
            "platform": sys.platform, "scope": "local setup checks only; no Pi loading observed by setup",
            "fresh_macos_v9_prepared_exercise": "NOT VERIFIED", "full_macos_v10": "NOT VERIFIED",
            "windows_follow_up": "NOT VERIFIED", "authenticated_integrations": "NOT VERIFIED",
        },
    }
    return plan, desired, readiness


def apply(plan: dict, desired: dict[Path, bytes]) -> None:
    # Preflight all names and bytes before creating any directory. Exclusive creation is deliberate:
    # never replace, even if another process changes a file after the last precondition check.
    workspace = Path(plan["workspace"])
    for path in desired:
        if plan["actions"][str(path.relative_to(workspace))]["action"] == "create":
            parent = workspace if plan["preconditions"][str(path.parent)] is None else path.parent
            if not os.access(parent, os.W_OK | os.X_OK):
                raise ValueError(f"setup destination is not writable: {parent}")
    for directory in (workspace / ".pi", workspace / ".dcc"):
        if plan["preconditions"][str(directory)] is None:
            directory.mkdir(mode=0o700)
    for path, content in desired.items():
        if plan["actions"][str(path.relative_to(workspace))]["action"] == "create":
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    preview = sub.add_parser("inspect", help="print a read-only JSON plan and local observations")
    preview.add_argument("--workspace", required=True)
    preview.add_argument("--repo", action="append", default=[], metavar="NAME=PATH")
    install = sub.add_parser("apply", help="create only the missing resources in a still-current plan")
    install.add_argument("--plan", required=True, type=Path, help="JSON output saved from inspect")
    install.add_argument("--approve", action="store_true")
    install.add_argument("--acknowledge-instruction-shadow", action="store_true", help=SHADOW)
    args = parser.parse_args()
    try:
        if args.mode == "inspect":
            preview_plan, _, readiness = inspect(local_path(args.workspace), args.repo)
            print(json_bytes({"ok": True, "plan": preview_plan, "readiness": readiness}).decode(), end="")
            return 0
        if not args.approve:
            raise ValueError("apply requires explicit --approve after inspecting the plan")
        if not args.acknowledge_instruction_shadow:
            raise ValueError(f"apply requires explicit --acknowledge-instruction-shadow. {SHADOW}")
        plan_path = local_path(str(args.plan))
        data = Inspection().file(plan_path, required=True)
        assert data is not None
        plan = json_object(data, plan_path).get("plan")
        if not isinstance(plan, dict) or not isinstance(plan.get("workspace"), str) or not isinstance(plan.get("repositories"), dict):
            raise TypeError("invalid setup plan: expected JSON output from inspect")
        repos = plan["repositories"]
        if not all(isinstance(path, str) for path in repos.values()):
            raise ValueError("invalid setup plan: expected local repository paths")
        try:
            observed, desired, readiness = inspect(local_path(plan["workspace"]), [f"{name}={path}" for name, path in repos.items()])
        except (OSError, ValueError, TypeError) as error:
            raise ValueError(f"stale or invalid setup plan; inspect again: {error}") from error
        if json_bytes(observed) != json_bytes(plan):
            raise ValueError("stale setup plan; inspect again before applying")
        apply(observed, desired)
        readiness["workspace_configuration"] = "configured"
        print(json_bytes({"ok": True, "applied": observed["actions"], "readiness": readiness}).decode(), end="")
    except (OSError, ValueError, RuntimeError, TypeError) as error:
        print(f"setup blocked: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
