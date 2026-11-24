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


def skill_name(data: bytes, path: Path) -> str | None:
    """Recognize common static frontmatter without loading Pi or executing packages."""
    lines = data.decode("utf-8-sig").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        raise ValueError("unrecognized skill frontmatter")
    key_pattern = r"(?:[A-Za-z][A-Za-z0-9_-]*|'[A-Za-z][A-Za-z0-9_-]*'|\"[A-Za-z][A-Za-z0-9_-]*\")"
    metadata = {}
    for line in lines[1:end]:
        if not line.strip() or line[0].isspace() or line.startswith("#"):
            continue
        key = re.fullmatch(rf"({key_pattern})\s*:\s*(.*)", line)
        if not key or key[1].strip("'\"") in metadata:
            raise ValueError("unrecognized skill frontmatter")
        metadata[key[1].strip("'\"")] = key[2].strip()
    if "description" not in metadata:
        return None
    raw = metadata.get("name", "")
    if re.fullmatch(r"(?:null|Null|NULL|true|True|TRUE|false|False|FALSE|~|[0-9]+)?(?:\s+#.*)?", raw):
        return path.parent.name
    match = re.fullmatch(r"(['\"]?)([A-Za-z0-9_-]+)\1(?:\s+#.*)?", raw)
    if not match:
        raise ValueError("unrecognized skill name")
    return match[2]


def resources(check: Inspection, workspace: Path, project_settings: dict) -> tuple[Path, bool, dict, list[str]]:
    home = local_path(str(Path.home()))
    agent = local_path(os.environ.get("PI_CODING_AGENT_DIR") or str(home / ".pi/agent"))
    if workspace == home.resolve() or any(
        workspace.is_relative_to(path) or path.is_relative_to(workspace)
        for alias in (agent, home / ".agents") for path in (alias, alias.resolve())
    ):
        raise ValueError("use a personal workspace separate from HOME and the Pi user configuration")
    advisories: set[str] = set()
    matches: dict[str, dict[str, str]] = {name: {} for name in SKILLS}
    user_path = agent / "settings.json"
    user_append = agent / "APPEND_SYSTEM.md"
    user_settings = {}
    try:
        user_data = check.file(user_path)
        if user_data is not None:
            user_settings = json_object(user_data, user_path)
    except (OSError, ValueError, TypeError) as error:
        advisories.add(f"user settings not inspected: {error}")
    try:
        has_user_append = check.file(user_append) is not None
    except (OSError, ValueError):
        has_user_append = user_append.exists()
        advisories.add(f"user append could not be checked: {user_append}")

    def discover(path: Path, scope: str, excluded: set[Path], *, root: bool = True) -> None:
        try:
            info = check.stat_path(path)
            if info is None:
                check.states[str(path)] = None
            elif stat.S_ISDIR(info.st_mode):
                check.directory(path)
                for child in sorted(path.iterdir()):
                    if not child.name.startswith(".") and child.name != "node_modules" and (
                        child.is_dir() or child.name == "SKILL.md" or (root and child.suffix == ".md")
                    ):
                        discover(child, scope, excluded, root=False)
            elif stat.S_ISREG(info.st_mode) and path.suffix == ".md" and path not in excluded:
                data = check.file(path, required=True)
                assert data is not None
                label = skill_name(data, path)
                if label is not None and label in SKILLS and path != KIT / "skills" / label / "SKILL.md":
                    matches[label].setdefault(str(path), scope)
            else:
                check.states[str(path)] = [info.st_dev, info.st_ino, info.st_mode]
        except (OSError, ValueError) as error:
            advisories.add(f"skill discovery advisory for {path}: {error}")

    def resource_path(entry: str, base: Path) -> Path:
        if entry.startswith("~/"):
            return Path(os.path.abspath(home / entry[2:]))
        return Path(os.path.abspath(base / entry))

    user_agents = home / ".agents/skills"
    project_agents = (parent / ".agents/skills" for parent in (workspace, *workspace.parents) if parent != home)
    sources = (("user", agent, user_settings, (agent / "skills", user_agents)),
               ("workspace", workspace / ".pi", project_settings, (workspace / ".pi/skills", *project_agents)))
    for scope, base, settings, roots in sources:
        for key in ("packages", "extensions"):
            if settings.get(key):
                advisories.add(f"{scope} {key} in {base / 'settings.json'} were not evaluated")
        extension_dir = base / "extensions"
        if extension_dir.exists() or extension_dir.is_symlink():
            advisories.add(f"existing extensions at {extension_dir} were not evaluated")
        configured = settings.get("skills", [])
        if not isinstance(configured, list) or any(not isinstance(item, str) for item in configured):
            advisories.add(f"unrecognized {scope} skills setting in {base / 'settings.json'}")
            configured = []
        excluded = {resource_path(item[1:], base) for item in configured if item.startswith("-")}
        for root in roots:
            discover(root, scope, excluded)
        for item in configured:
            if not item or item.startswith(("!", "-", "+")) or any(token in item for token in "*?[]{}"):
                if item.startswith(("!", "+")) or any(token in item for token in "*?[]{}"):
                    advisories.add(f"{scope} skill filters need a Pi resource check after setup")
                continue
            discover(resource_path(item, base), scope, excluded)
    return user_append, has_user_append, matches, sorted(advisories)


def inspect(workspace: Path, entries: list[str], append: str, choices: dict[str, str],
            no_skills: bool) -> tuple[dict, dict[Path, bytes], dict]:
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
    settings_path = workspace / ".pi/settings.json"
    project_append = workspace / ".pi/APPEND_SYSTEM.md"
    settings_bytes = check.file(settings_path)
    project_settings = {} if settings_bytes is None else json_object(settings_bytes, settings_path)
    append_bytes = check.file(project_append)
    user_append, has_user_append, matches, advisories = resources(check, workspace, project_settings)
    template_path = KIT / "templates/pi/APPEND_SYSTEM.md"
    template = check.file(template_path, required=True)
    assert template is not None
    mapping = {"version": 1, "workspace": str(workspace), "kit": str(KIT), "repositories": repos}
    if current is not None and json_object(current, saved) != mapping:
        raise ValueError(f"conflict: existing mapping differs at {saved}; setup will not edit it")
    desired: dict[Path, bytes] = {saved: current if current is not None else json_bytes(mapping)}
    blockers = []
    skill_plan = {}
    configured_skills = project_settings.get("skills", [])
    additions = []
    if settings_bytes is not None:
        desired[settings_path] = settings_bytes
    for name in SKILLS:
        path = KIT / "skills" / name / "SKILL.md"
        check.file(path, required=True)
        conflicts = matches[name]
        choice = choices.get(name)
        already_registered = isinstance(configured_skills, list) and str(path) in configured_skills
        # New settings can exclude a project-scoped file. User-scoped auto/configured
        # resources must be disabled in their own scope, never by writing user settings.
        project_excludable = settings_bytes is None and all(scope == "workspace" for scope in conflicts.values())
        status = "preserved" if settings_bytes is not None else "not-registered"
        if no_skills or choice == "keep":
            status = "already-registered; change existing settings manually" if already_registered else "keep-existing"
        elif conflicts and choice is None and (settings_bytes is None or already_registered):
            status = "choice-required"
            if settings_bytes is None:
                blockers.append(f"conflicting skill name {name}; use --skill-choice {name}=keep or {name}=register")
        elif choice == "register" and conflicts and not project_excludable:
            status = "manual-collision-resolution"
            blockers.append(f"conflicting skill name {name}; disable the listed resources in their Pi scope and inspect again")
        elif settings_bytes is None:
            status = "register"
            additions.extend([str(path), *(f"-{conflict}" for conflict in conflicts)])
        elif already_registered:
            status = "already-registered"
        elif choice == "register":
            status = "manual-registration"
            advisories.append(f"add the selected {name} kit path to existing project settings yourself, then inspect again")
        skill_plan[name] = {"kit": str(path), "existing": conflicts, "selection": status,
                            "choices": [f"--skill-choice {name}=keep", f"--skill-choice {name}=register"]}
    if additions:
        desired[settings_path] = json_bytes({"skills": additions})
    if append_bytes is not None:
        desired[project_append] = append_bytes
        if append == "use-template" and append_bytes != template:
            blockers.append(f"existing {project_append} is custom; use keep-personal or edit it yourself")
    elif append == "use-template":
        desired[project_append] = template
    actions = {}
    for path, content in desired.items():
        actions[str(path.relative_to(workspace))] = {
            "action": "unchanged" if check.states[str(path)] is not None else "create",
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    trusted_append = project_append if project_append in desired else user_append if has_user_append else None
    plan = {"version": 2, "workspace": str(workspace), "repositories": repos,
            "instruction_precedence": SHADOW, "actions": actions, "preconditions": check.states,
            "append": {"choice": append, "choices": ["keep-personal", "use-template"],
                       "template": str(template_path), "trusted": str(trusted_append) if trusted_append else None,
                       "untrusted": str(user_append) if has_user_append else None},
            "skills": skill_plan, "skill_choices": choices, "no_skills": no_skills,
            "blockers": blockers, "advisories": advisories}
    readiness = {
        "workspace_configuration": ("blocked" if blockers else "configured"
                                    if all(item["action"] == "unchanged" for item in actions.values()) else "planned"),
        "local_checks": {"pi": command("pi", "--version"), "herdr": command("herdr", "--version"), "repositories": repo_results},
        "capabilities": {
            "knowledge_integration": knowledge_readiness(workspace, (KIT, *(Path(path) for path in repos.values()))),
            "shared_meeting_notes": "not established; deferred",
            "fathom": "optional; NOT VERIFIED",
            "clickup": "standalone read-only reader available; authentication not checked",
            "context_retrieval": "selected-task preparation available locally; no task assessment observed by setup",
            "live_factory": "coordinator-invoked loop available locally; live provider and account operation NOT VERIFIED",
            "provider_fallback": "writer-only switch requires explicit approval; role isolation and accounts NOT VERIFIED",
            "openspec_drafting": "local draft and strict validation helper available; tool and target workflow not checked by setup",
            "full_task_start": "blocked: explicit developer launch approval required",
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
    pending = {path: content for path, content in desired.items()
               if plan["actions"][str(path.relative_to(workspace))]["action"] == "create"}
    directories = sorted({path.parent for path in pending})
    for directory in directories:
        parent = workspace if plan["preconditions"][str(directory)] is None else directory
        if not os.access(parent, os.W_OK | os.X_OK):
            raise ValueError(f"setup destination is not writable: {parent}")
    workspace_fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    opened = {}
    try:
        for directory in directories:
            if plan["preconditions"][str(directory)] is None:
                os.mkdir(directory.name, mode=0o700, dir_fd=workspace_fd)
            opened[directory] = os.open(directory.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                        dir_fd=workspace_fd)
        for path, content in pending.items():
            fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                         dir_fd=opened[path.parent])
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
    finally:
        for directory_fd in opened.values():
            os.close(directory_fd)
        os.close(workspace_fd)


def skill_choices(entries: list[str]) -> dict[str, str]:
    choices = {}
    for entry in entries:
        name, _, choice = entry.partition("=")
        if name not in SKILLS or choice not in {"keep", "register"} or name in choices:
            raise ValueError("expected unique --skill-choice NAME=keep or NAME=register for a kit skill")
        choices[name] = choice
    return choices


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    preview = sub.add_parser("inspect", help="print a read-only JSON plan and local observations")
    preview.add_argument("--workspace", required=True)
    preview.add_argument("--repo", action="append", default=[], metavar="NAME=PATH")
    preview.add_argument("--append", choices=("keep-personal", "use-template"), default="keep-personal")
    preview.add_argument("--skill-choice", action="append", default=[], metavar="NAME=keep|register")
    preview.add_argument("--no-skills", action="store_true", help="do not register kit skills")
    install = sub.add_parser("apply", help="create only the missing resources in a still-current plan")
    install.add_argument("--plan", required=True, type=Path, help="JSON output saved from inspect")
    install.add_argument("--approve", action="store_true")
    install.add_argument("--acknowledge-instruction-shadow", action="store_true", help=SHADOW)
    args = parser.parse_args()
    try:
        if args.mode == "inspect":
            choices = skill_choices(args.skill_choice)
            if choices and args.no_skills:
                raise ValueError("select --no-skills or individual --skill-choice values, not both")
            preview_plan, _, readiness = inspect(local_path(args.workspace), args.repo, args.append, choices, args.no_skills)
            print(json_bytes({"ok": True, "plan": preview_plan, "readiness": readiness}).decode(), end="")
            return 0
        if not args.approve:
            raise ValueError("apply requires explicit --approve after inspecting the plan")
        plan_path = local_path(str(args.plan))
        data = Inspection().file(plan_path, required=True)
        assert data is not None
        plan = json_object(data, plan_path).get("plan")
        if (not isinstance(plan, dict) or plan.get("version") != 2 or not isinstance(plan.get("workspace"), str)
                or not isinstance(plan.get("repositories"), dict) or not isinstance(plan.get("append"), dict)
                or not isinstance(plan.get("skill_choices"), dict) or type(plan.get("no_skills")) is not bool):
            raise TypeError("invalid setup plan: inspect again for a version 2 plan")
        repos = plan["repositories"]
        append = plan["append"].get("choice")
        if append not in ("keep-personal", "use-template"):
            raise ValueError("invalid setup plan: unknown append choice")
        choices = skill_choices([f"{name}={choice}" for name, choice in plan["skill_choices"].items()])
        if plan["no_skills"] and choices:
            raise ValueError("invalid setup plan: contradictory skill choices")
        if not all(isinstance(path, str) for path in repos.values()):
            raise ValueError("invalid setup plan: expected local repository paths")
        try:
            observed, desired, readiness = inspect(local_path(plan["workspace"]),
                 [f"{name}={path}" for name, path in repos.items()], append, choices, plan["no_skills"])
        except (OSError, ValueError, TypeError) as error:
            raise ValueError(f"stale or invalid setup plan; inspect again: {error}") from error
        if json_bytes(observed) != json_bytes(plan):
            raise ValueError("stale setup plan; inspect again before applying")
        if observed["blockers"]:
            raise ValueError("; ".join(observed["blockers"]))
        if (observed["actions"].get(".pi/APPEND_SYSTEM.md", {}).get("action") == "create"
                and not args.acknowledge_instruction_shadow):
            raise ValueError(f"apply requires explicit --acknowledge-instruction-shadow. {SHADOW}")
        apply(observed, desired)
        readiness["workspace_configuration"] = "configured"
        print(json_bytes({"ok": True, "applied": observed["actions"], "readiness": readiness}).decode(), end="")
    except (OSError, ValueError, RuntimeError, TypeError) as error:
        print(f"setup blocked: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
