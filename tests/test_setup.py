"""C1/C2/C6/C7: real setup CLI, disposable paths and recorded local subprocesses."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_factory_job import clean_env

KIT = Path(__file__).resolve().parents[1]
APPROVE = ("--approve", "--acknowledge-instruction-shadow")
DESTINATIONS = {".pi/settings.json", ".pi/APPEND_SYSTEM.md", ".dcc/workspace.json"}


def file_map(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        entry = {"mode": oct(mode)}
        if stat.S_ISLNK(mode):
            entry["link"] = os.readlink(path)
        elif stat.S_ISREG(mode):
            entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        out[path.relative_to(root).as_posix()] = entry
    return out


def evidence(name: str, data: object) -> None:
    directory = os.environ.get("DCC_EVIDENCE")
    if directory:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=name + "-", suffix=".json", delete=False) as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")


def write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


class SetupFixture:
    def __init__(self, root: Path, kit: Path = KIT) -> None:
        self.root = root
        self.kit = kit
        self.workspace = root / "workspace"
        self.home = root / "home"
        self.repo = root / "target repo"
        self.other_repo = root / "other repo"
        self.bin = root / "bin"
        self.trace = root / "trace.jsonl"
        self.outside = root / "outside-settings.json"
        self.plan = root / "reviewed-plan.json"
        for path in (self.workspace, self.home, self.repo, self.other_repo, self.bin):
            path.mkdir()
        write(self.outside, '{"keep":"outside"}\n', 0o640)
        actual_git = shutil.which("git")
        if not actual_git:
            raise RuntimeError("Git is required for the real local repo fixture")
        for repo in (self.repo, self.other_repo):
            self.git(actual_git, repo, "init", "-q")
            write(repo / "README.md", "fixture\n", 0o644)
            self.git(actual_git, repo, "add", "README.md")
        # All setup child processes cross the Python audit hook below. Separate executable
        # fixtures also reject/record accidental launches, not only missing-binary paths.
        for executable in ("pi", "herdr", "git", "npm", "brew", "pip", "curl", "wget", "ssh"):
            write(self.bin / executable,
                  f"#!{sys.executable}\n"
                  "import os, sys\n"
                  f"name = {executable!r}\n"
                  "args = sys.argv[1:]\n"
                  "if name == 'git' and len(args) == 5 and args[:2] == ['--no-optional-locks', '-C']"
                  " and args[3:] == ['rev-parse', '--show-toplevel']:\n"
                  f"    os.execv({actual_git!r}, [{actual_git!r}, *args])\n"
                  "if name in {'pi', 'herdr'} and args == ['--version']:\n"
                  "    print(name + ' fixture version 1.2.3')\n"
                  "    raise SystemExit(0)\n"
                  "print('forbidden fixture command', name, args, file=sys.stderr)\n"
                  "raise SystemExit(97)\n", 0o700)
        self.cli_results: list[dict[str, tuple[str, ...] | int | str]] = []

    def git(self, exe: str, repo: Path, *args: str) -> str:
        return subprocess.run([exe, "-C", str(repo), *args], env=clean_env(self.home),
                              text=True, capture_output=True, check=True, timeout=10).stdout

    def __call__(self, *args: str) -> subprocess.CompletedProcess[str]:
        audited = """
import json, runpy, sys
trace, script, *args = sys.argv[1:]
def record(event, values):
    if event == 'subprocess.Popen':
        with open(trace, 'a', encoding='utf-8') as handle:
            print(json.dumps(values[1]), file=handle)
    if event in {'os.system', 'os.exec', 'os.posix_spawn', 'socket.connect'}:
        with open(trace, 'a', encoding='utf-8') as handle:
            print(json.dumps({'forbidden': event}), file=handle)
        raise RuntimeError('forbidden fixture boundary: ' + event)
sys.addaudithook(record)
sys.argv = [script, *args]
runpy.run_path(script, run_name='__main__')
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", audited, str(self.trace), str(self.kit / "scripts/setup.py"), *args],
            text=True, capture_output=True, timeout=20, cwd=self.root,
            env=clean_env(self.home) | {"PATH": str(self.bin)}, check=False,
        )
        self.cli_results.append({"args": args, "exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        return result

    def inspect(self, *extra: str, with_repos: bool = True) -> subprocess.CompletedProcess[str]:
        return self("inspect", "--workspace", str(self.workspace), *(
            ("--repo", f"app={self.repo}", "--repo", f"tools={self.other_repo}") if with_repos else ()
        ), *extra)

    def apply(self, *flags: str) -> subprocess.CompletedProcess[str]:
        return self("apply", "--plan", str(self.plan), *flags)

    def snapshot(self) -> dict:
        return {"workspace": file_map(self.workspace), "home": file_map(self.home), "repo": file_map(self.repo),
                "other_repo": file_map(self.other_repo), "outside": self.outside.read_bytes().hex(),
                "outside_mode": oct(self.outside.stat().st_mode)}

    def child_commands(self) -> list:
        return [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()] if self.trace.exists() else []

    def user_settings(self) -> None:
        agent = self.home / ".pi/agent"
        write(agent / "settings.json", '{"quietStartup":true}\n', 0o640)
        write(agent / "APPEND_SYSTEM.md", "SYNTHETIC user-only appendix\n", 0o644)
        write(agent / "auth.json", 'not a real credential; do not read via Pi\n', 0o600)
        write(agent / "trust.json", '{"sentinel":"untouched"}\n', 0o640)


class SetupTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="dcc-setup-", dir=os.environ.get("DCC_EVIDENCE"))
        self.addCleanup(temp.cleanup)
        self.fx = SetupFixture(Path(temp.name).resolve())
        self.addCleanup(self.record_and_check_trace)
        self.maps: dict = {}

    def record_and_check_trace(self) -> None:
        fx = self.fx
        commands = fx.child_commands()
        evidence(self._testMethodName, {"subprocesses": commands, "cli": fx.cli_results, "maps": self.maps})
        allowed = [[str(fx.bin / name), "--version"] for name in ("pi", "herdr")] + [
            [str(fx.bin / "git"), "--no-optional-locks", "-C", str(repo), "rev-parse", "--show-toplevel"]
            for repo in (fx.repo, fx.other_repo)
        ]
        for argv in commands:
            self.assertIn(argv, allowed, "unexpected child command in inspect/apply boundary")

    def parsed(self, result: subprocess.CompletedProcess[str]) -> dict:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def assert_technical_request_only(self, text: str) -> None:
        # Inspect the actual request/error text, not structured capability data (which
        # legitimately reports optional knowledge) or local paths echoed in errors.
        diagnostic = text.replace(str(self.fx.root), "<fixture>").replace(str(KIT), "<kit>")
        self.assertNotRegex(diagnostic.lower(), r"\b(?:business|identity|voice|revenue|knowledge|seven[- ]question|(?:shared[- ]?)?meetings?|fathom)\b",
                            "A14 setup diagnostic must not request excluded or deferred intake")

    def refusal(self, result: subprocess.CompletedProcess[str], message: str, before: dict) -> None:
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(message, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assert_technical_request_only(result.stderr)
        after = self.fx.snapshot()
        self.maps.setdefault("refusals", []).append({"message": message, "before": before, "after": after})
        self.assertEqual(after, before)

    def save_plan(self) -> dict:
        result = self.fx.inspect()
        plan = self.parsed(result)
        write(self.fx.plan, result.stdout)
        return plan

    def test_inspect_approve_apply_and_repeat_preserve_bytes_and_modes(self) -> None:
        fx = self.fx
        fx.user_settings()
        # Pre-existing project directory and unrelated local settings sentinel.
        write(fx.workspace / ".pi/keep.txt", "leave alone", 0o640)
        self.maps["before"] = before = fx.snapshot()
        inspected = self.save_plan()
        self.assertEqual(fx.snapshot(), before)
        plan = inspected["plan"]
        self.assertEqual(set(plan["actions"]), DESTINATIONS)
        self.assertEqual({item["action"] for item in plan["actions"].values()}, {"create"})
        self.assertIn("shadows rather than combines with user APPEND_SYSTEM", plan["instruction_precedence"])
        self.assertIn("Preserving bytes does not preserve effective instructions", plan["instruction_precedence"])
        self.refusal(fx.apply(), "requires explicit --approve", before)
        self.refusal(fx.apply("--acknowledge-instruction-shadow"), "requires explicit --approve", before)
        self.refusal(fx.apply("--approve"), "requires explicit --acknowledge-instruction-shadow", before)
        self.assertEqual(self.parsed(fx.apply(*APPROVE))["readiness"]["workspace_configuration"], "configured")
        self.maps["after"] = after = fx.snapshot()
        self.assertEqual(set(after["workspace"]) - set(before["workspace"]), DESTINATIONS | {".dcc"})
        for section in ("home", "repo", "other_repo", "outside", "outside_mode"):
            self.assertEqual(after[section], before[section], section)
        for path in before["workspace"]:
            self.assertEqual(after["workspace"][path], before["workspace"][path], path)
        self.assertEqual(json.loads((fx.workspace / ".dcc/workspace.json").read_text()), {
            "version": 1, "workspace": str(fx.workspace), "kit": str(KIT),
            "repositories": {"app": str(fx.repo), "tools": str(fx.other_repo)},
        })
        self.assertEqual(json.loads((fx.workspace / ".pi/settings.json").read_text()), {
            "skills": [str(KIT / f"skills/{name}/SKILL.md") for name in ("setup", "factory", "grilling")],
        })
        self.assertEqual((fx.workspace / ".pi/APPEND_SYSTEM.md").read_bytes(), (KIT / "templates/pi/APPEND_SYSTEM.md").read_bytes())
        self.refusal(fx.apply(*APPROVE), "stale setup plan", after)
        next_plan = fx.inspect(with_repos=False)
        self.assertEqual(self.parsed(next_plan)["plan"]["repositories"], plan["repositories"])
        write(fx.plan, next_plan.stdout)
        rerun = self.parsed(fx.apply(*APPROVE))
        self.assertEqual({item["action"] for item in rerun["applied"].values()}, {"unchanged"})
        self.assertEqual(fx.snapshot(), after)
        self.assertIn([str(fx.bin / "pi"), "--version"], fx.child_commands())
        self.assertIn([str(fx.bin / "herdr"), "--version"], fx.child_commands())
        self.assertIn([str(fx.bin / "git"), "--no-optional-locks", "-C", str(fx.repo), "rev-parse", "--show-toplevel"], fx.child_commands())

    def test_only_missing_mapping_or_workspace_requested(self) -> None:
        fx = self.fx
        before = fx.snapshot()
        self.refusal(fx.inspect(with_repos=False), "missing named local Git target mapping; supply --repo NAME=PATH", before)
        self.refusal(fx("inspect", "--repo", f"app={fx.repo}"), "the following arguments are required: --workspace", before)
        self.refusal(fx.inspect("--repo", "invalid-mapping", with_repos=False), "expected unique --repo NAME=PATH mappings", before)
        self.refusal(fx("apply", *APPROVE), "the following arguments are required: --plan", before)
        for mode, legitimate in (("inspect", ("--workspace", "--repo NAME=PATH")), ("apply", ("--plan", "--approve"))):
            with self.subTest(help_for=mode):
                help_output = fx(mode, "--help")
                self.assertEqual(help_output.returncode, 0, help_output.stderr)
                for option in legitimate:
                    self.assertIn(option, help_output.stdout)
                self.assert_technical_request_only(help_output.stdout + help_output.stderr)
        supplied = self.parsed(fx.inspect())["plan"]["repositories"]
        self.assertEqual(supplied, {"app": str(fx.repo), "tools": str(fx.other_repo)})
        self.assertEqual(fx.snapshot(), before)

    def test_observed_local_results_are_not_integration_readiness(self) -> None:
        fx = self.fx
        found = self.parsed(fx.inspect())["readiness"]
        local = found["local_checks"]
        for name in ("pi", "herdr"):
            self.assertEqual(local[name]["status"], "working")
            self.assertEqual(local[name]["exit"], 0)
            self.assertEqual(local[name]["stdout"], f"{name} fixture version 1.2.3")
        for key, repo in (("app", fx.repo), ("tools", fx.other_repo)):
            self.assertEqual(local["repositories"][key]["status"], "working")
            self.assertEqual(local["repositories"][key]["stdout"], str(repo))
        self.assertEqual(found["capabilities"], {
            "knowledge_integration": "not configured; optional",
            "shared_meeting_notes": "not established; deferred",
            "fathom": "optional; NOT VERIFIED", "clickup": "standalone read-only reader available; authentication not checked",
            "context_retrieval": "selected-task preparation available locally; no task assessment observed by setup", "live_factory": "unsupported: not implemented",
            "provider_fallback": "unsupported: not implemented", "full_task_start": "blocked: OpenSpec drafting and live factory launch are unsupported",
        })
        self.assertEqual(found["workflow"], "blocked; registration is not overall workflow readiness or launch permission")
        self.assertEqual(found["verification"], {
            "platform": sys.platform, "scope": "local setup checks only; no Pi loading observed by setup",
            "fresh_macos_v9_prepared_exercise": "NOT VERIFIED", "full_macos_v10": "NOT VERIFIED",
            "windows_follow_up": "NOT VERIFIED", "authenticated_integrations": "NOT VERIFIED",
        })
        for missing, other in (("pi", "herdr"), ("herdr", "pi")):
            with self.subTest(missing=missing):
                original = fx.bin / missing
                parked = fx.root / f"missing-{missing}"
                original.rename(parked)
                observed = self.parsed(fx.inspect())["readiness"]["local_checks"]
                self.assertEqual(observed[missing], {"status": "blocked", "reason": f"{missing} executable missing"})
                self.assertEqual(observed[other]["status"], "working")
                parked.rename(original)

    def test_version_command_failure_is_blocked(self) -> None:
        write(self.fx.bin / "herdr", f"#!{sys.executable}\nprint('not a usable result')\nraise SystemExit(9)\n", 0o700)
        actual = self.parsed(self.fx.inspect())["readiness"]["local_checks"]["herdr"]
        self.assertEqual(actual["status"], "blocked")
        self.assertEqual(actual["exit"], 9)

    def test_conflicts_and_malformed_settings_never_partially_apply(self) -> None:
        fx = self.fx
        self.save_plan()
        for relative, content, reason in (
            (".pi/settings.json", '{"theme":"fixture"}', "conflict:"),
            (".pi/settings.json", '{"broken":}', "malformed JSON"),
            (".pi/settings.json", '{"skills":[],"skills":[]}', "malformed JSON"),
            (".pi/APPEND_SYSTEM.md", "keep existing instructions\n", "conflict:"),
            (".dcc/workspace.json", "[]", "expected a JSON object"),
        ):
            with self.subTest(relative=relative, content=content):
                path = fx.workspace / relative
                write(path, content)
                before = fx.snapshot()
                self.refusal(fx.inspect(), reason, before)
                self.refusal(fx.apply(*APPROVE), f"stale or invalid setup plan; inspect again: {reason}", before)
                path.unlink()

    def test_destination_and_ancestor_symlinks_are_rejected(self) -> None:
        fx = self.fx
        self.save_plan()
        for relative in (".pi", ".dcc", ".pi/settings.json", ".pi/APPEND_SYSTEM.md", ".dcc/workspace.json"):
            with self.subTest(relative=relative):
                path = fx.workspace / relative
                path.parent.mkdir(exist_ok=True)
                path.symlink_to(fx.outside if relative != ".dcc" else fx.root / "missing-dir")
                before = fx.snapshot()
                self.refusal(fx.inspect(), "symlink not allowed", before)
                self.refusal(fx.apply(*APPROVE), "symlink not allowed", before)
                path.unlink()
        alias = fx.root / "workspace-alias"
        alias.symlink_to(fx.workspace, target_is_directory=True)
        self.refusal(fx("inspect", "--workspace", str(alias), "--repo", f"app={fx.repo}"), "symlink not allowed", fx.snapshot())

    def test_apply_rejects_symlink_to_a_valid_plan(self) -> None:
        fx = self.fx
        self.save_plan()
        physical = fx.root / "physical-plan.json"
        fx.plan.rename(physical)
        fx.plan.symlink_to(physical)
        self.refusal(fx.apply(*APPROVE), "symlink not allowed", fx.snapshot())

    def test_stale_plan_rejects_new_directory_and_changed_user_append(self) -> None:
        fx = self.fx
        fx.user_settings()
        self.save_plan()
        (fx.workspace / ".dcc").mkdir()
        self.refusal(fx.apply(*APPROVE), "stale setup plan", fx.snapshot())
        self.save_plan()
        appendix = fx.home / ".pi/agent/APPEND_SYSTEM.md"
        appendix.chmod(0o600)
        self.refusal(fx.apply(*APPROVE), "stale setup plan", fx.snapshot())

    def test_detects_existing_skill_by_name_not_directory(self) -> None:
        fx = self.fx
        self.save_plan()
        for root in (fx.home / ".pi/agent/skills", fx.workspace / ".pi/skills", fx.root / ".agents/skills"):
            with self.subTest(root=root):
                skill = root / "other-directory/SKILL.md"
                write(skill, "---\nname: 'factory'\ndescription: 'fixture duplicate'\n---\n# Sentinel\n")
                self.refusal(fx.inspect(), "conflicting skill name factory", fx.snapshot())
                self.refusal(fx.apply(*APPROVE), "conflicting skill name factory", fx.snapshot())
                skill.unlink()
        fallback = fx.workspace / ".pi/skills/setup/SKILL.md"
        write(fallback, "---\nname: null\ndescription: 'synthetic fallback-name collision'\n---\n# Sentinel\n")
        self.refusal(fx.inspect(), "conflicting skill name setup", fx.snapshot())

    def test_refuses_ambiguous_user_resource_configuration_without_edits(self) -> None:
        fx = self.fx
        settings = fx.home / ".pi/agent/settings.json"
        for content, reason in (("{", "malformed JSON"), ('{"packages":["not-installed"]}', "cannot rule out"),
                                ('{"skills":["somewhere"]}', "cannot rule out")):
            with self.subTest(content=content):
                write(settings, content)
                self.refusal(fx.inspect(), reason, fx.snapshot())

    def test_workspace_cannot_be_target_or_kit(self) -> None:
        fx = self.fx
        nested = fx.repo / "workspace"
        nested.mkdir()
        before = fx.snapshot()
        for path, reason in ((fx.repo, "inside a Git checkout"), (nested, "inside a Git checkout"), (KIT, "separate from the kit")):
            with self.subTest(path=path):
                self.refusal(fx("inspect", "--workspace", str(path), "--repo", f"app={fx.repo}"), reason, before)


if __name__ == "__main__":
    unittest.main()
