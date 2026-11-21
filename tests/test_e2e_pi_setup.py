"""C2–C7: load a relocated distribution with the declared Pi SDK, offline."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from test_e2e_factory import ARCHIVE, EXPECTED_MEMBERS
from test_factory_job import clean_env
from test_instruction_packaging import PRIVATE_MARKERS, SKILL_CLAUSES
from test_setup import APPROVE, KIT, SetupFixture, evidence, file_map, write

SKILLS = ("setup", "factory", "grilling")
CALLER_ARGS = {
    "setup": "dcc-offline-setup inspect only",
    "factory": "dcc-offline-factory inspect only",
    "grilling": "dcc-offline-grilling inspect fixture decisions.md, example.csv and task.md; do not implement",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PiDistributionTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="dcc-pi-e2e-", dir=os.environ.get("DCC_EVIDENCE"))
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.relocated = self.root / "relocated kit"
        self.fx = SetupFixture(self.root, self.relocated)
        self.node = shutil.which("node")
        self.sdk = os.environ.get("DCC_PI_SDK_MODULE")
        self.assertTrue(self.sdk and Path(self.sdk).is_file(), "DCC_PI_SDK_MODULE must name the installed Pi SDK; no skipping")
        self.assertTrue(self.node, "Node is required for real Pi SDK evidence")
        self.audit = self.root / "child-process-audit.mjs"
        self.child_trace = self.root / "node-child-commands.jsonl"
        write(self.audit, """
import child from "node:child_process";
import {appendFileSync} from "node:fs";
import {syncBuiltinESMExports} from "node:module";
for (const operation of ["spawn", "spawnSync", "exec", "execSync", "execFile", "execFileSync", "fork"]) {
  child[operation] = (command, args) => {
    appendFileSync(process.env.DCC_CHILD_TRACE, JSON.stringify({operation, command, args: Array.isArray(args) ? args : []}) + "\\n");
    throw new Error("unexpected child command from offline probe: " + command);
  };
}
syncBuiltinESMExports();
""")
        output = self.root / "build output"
        built = subprocess.run([sys.executable, "-B", str(KIT / "scripts/build.py"), "--output", str(output)],
                               cwd=self.root, env=clean_env(self.fx.home), check=False, capture_output=True, text=True, timeout=20)
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        self.relocated.mkdir()
        with tarfile.open(output / ARCHIVE, "r:gz") as archive:
            self.assertCountEqual(archive.getnames(), EXPECTED_MEMBERS)
            for member in archive.getmembers():
                out = self.relocated / member.name
                self.assertTrue(member.isfile() and out.resolve().is_relative_to(self.relocated))
                stream = archive.extractfile(member)
                assert stream is not None
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(stream.read())
        self.results: list[dict] = []
        self.maps: dict = {}
        self.addCleanup(self.record_evidence)

    def record_evidence(self) -> None:
        node_commands = self.child_trace.read_text(encoding="utf-8").splitlines() if self.child_trace.exists() else []
        setup_commands = self.fx.child_commands()
        evidence(self._testMethodName, {"probe": self.results, "setup": self.fx.cli_results,
                                       "node_child_commands": node_commands, "setup_child_commands": setup_commands,
                                       "maps": self.maps})
        self.assertEqual(node_commands, [], "offline Pi probe must not spawn a child process")
        expected = [[str(self.fx.bin / name), "--version"] for name in ("pi", "herdr")] + [
            [str(self.fx.bin / "git"), "--no-optional-locks", "-C", str(repo), "rev-parse", "--show-toplevel"]
            for repo in (self.fx.repo, self.fx.other_repo)
        ]
        for command in setup_commands:
            self.assertIn(command, expected)

    def install(self) -> None:
        before = self.fx.snapshot()
        plan = self.fx.inspect()
        self.assertEqual(plan.returncode, 0, plan.stdout + plan.stderr)
        self.assertEqual(self.fx.snapshot(), before)
        write(self.fx.plan, plan.stdout)
        result = self.fx.apply(*APPROVE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = self.fx.snapshot()
        self.maps.update(before_setup=before, after_setup=after)
        for section in ("home", "repo", "other_repo", "outside", "outside_mode"):
            self.assertEqual(after[section], before[section], section)
        settings = json.loads((self.fx.workspace / ".pi/settings.json").read_text())
        self.assertEqual(settings, {"skills": [str(self.relocated / f"skills/{name}/SKILL.md") for name in SKILLS]})

    def probe(self, *, status: int = 0, sdk: str | None = None) -> subprocess.CompletedProcess[str]:
        env = clean_env(self.fx.home) | {"DCC_CHILD_TRACE": str(self.child_trace), "PI_OFFLINE": "1"}
        selected = self.sdk if sdk is None else sdk
        if selected:
            env["DCC_PI_SDK_MODULE"] = selected
        command = [str(self.node), "--import", str(self.audit), str(self.relocated / "scripts/verify-pi-resources.mjs"),
                   "--fixture-root", str(self.root)]
        before = self.fx.snapshot() | {"kit": file_map(self.relocated)}
        result = subprocess.run(command, cwd=self.root, env=env, text=True, capture_output=True, timeout=30, check=False)
        after = self.fx.snapshot() | {"kit": file_map(self.relocated)}
        try:
            observed = json.loads(result.stdout)
        except ValueError:
            observed = result.stdout
        self.results.append({"argv": command, "sdk": selected, "exit": result.returncode, "stdout": observed,
                             "stderr": result.stderr, "before": before, "after": after})
        self.assertEqual(after, before)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return result

    def check_good_probe(self, data: dict, global_append: str | None) -> None:
        self.assertTrue(data["ok"])
        self.assertEqual(data["sdkVersion"], "1.4.0")
        self.assertEqual(data["resourceLoader"], "DefaultResourceLoader")
        self.assertEqual(data["sessionStorage"], "in memory")
        self.assertEqual(data["transport"], "Pi faux provider with local context recorder; no model API")
        self.assertEqual(data["platform"], sys.platform)
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["kit"], str(self.relocated))
        self.assertEqual(data["workspace"], str(self.fx.workspace))
        self.assertEqual(data["workflow"], "blocked; resource loading is not overall readiness or launch permission")
        self.assertEqual(set(data["notVerified"]), {
            "fresh macOS V9/prepared exercise", "full macOS V10", "Windows follow-up", "authenticated integrations",
            "live orchestration/fallback", "model obedience",
        })
        trusted, denied = data["trusted"], data["denied"]
        self.assertTrue(trusted["requestedTrust"] and trusted["projectTrusted"])
        self.assertFalse(denied["requestedTrust"] or denied["projectTrusted"])
        self.assertEqual(trusted["diagnostics"], [])
        self.assertEqual(denied["diagnostics"], [])
        self.assertEqual(denied["skills"], [])
        self.assertEqual(denied["expansions"], [])
        neutral = (self.relocated / "templates/pi/APPEND_SYSTEM.md").read_bytes()
        self.assertEqual(trusted["appendSources"], [{"path": str(self.fx.workspace / ".pi/APPEND_SYSTEM.md"), "sha256": sha(neutral)}])
        self.assertIn(neutral.decode().strip(), trusted["systemPrompt"])
        self.assertNotIn(neutral.decode().strip(), denied["systemPrompt"])
        for clause in ("Read the target repository's `AGENTS.md`", "A readiness verdict is not permission to launch",
                       "Do not overwrite existing settings without approval", "Say NOT VERIFIED"):
            self.assertIn(clause, trusted["systemPrompt"])
            self.assertNotIn(clause, denied["systemPrompt"])
        if global_append is None:
            self.assertEqual(denied["appendSources"], [])
        else:
            self.assertNotIn(global_append, trusted["systemPrompt"])
            self.assertIn(global_append, denied["systemPrompt"])
            path = self.fx.home / ".pi/agent/APPEND_SYSTEM.md"
            self.assertEqual(denied["appendSources"], [{"path": str(path), "sha256": sha(path.read_bytes())}])
        self.assertEqual({skill["name"] for skill in trusted["skills"]}, set(SKILLS))
        self.assertEqual([entry["name"] for entry in trusted["expansions"]], list(SKILLS))
        assert self.sdk is not None
        sdk_root = Path(self.sdk).resolve().parents[1]
        for result in (trusted, denied):
            self.assertNotRegex(result["systemPrompt"].replace(str(self.relocated), "<kit>")
                                .replace(str(self.fx.workspace), "<workspace>")
                                .replace(str(sdk_root), "<pi-sdk>").lower(), PRIVATE_MARKERS)
        for entry in trusted["expansions"]:
            name = entry["name"]
            path = self.relocated / f"skills/{name}/SKILL.md"
            text = path.read_text(encoding="utf-8")
            body = text.split("\n---\n", 1)[1].strip()
            skill = next(skill for skill in trusted["skills"] if skill["name"] == name)
            self.assertEqual(skill["filePath"], str(path))
            self.assertEqual(skill["baseDir"], str(path.parent))
            self.assertEqual(skill["description"], text.split("description: '", 1)[1].split("'\n", 1)[0])
            self.assertEqual(skill["sha256"], sha(path.read_bytes()))
            self.assertFalse(skill["disableModelInvocation"])
            self.assertIn(f"<name>{name}</name>", trusted["systemPrompt"])
            self.assertIn(f"<location>{path}</location>", trusted["systemPrompt"])
            self.assertNotIn(str(path), denied["systemPrompt"])
            self.assertEqual(entry["command"], f"/skill:{name} {CALLER_ARGS[name]}")
            self.assertEqual(entry["systemPrompt"], trusted["systemPrompt"])
            self.assertEqual(entry["bodySha256"], sha(body.encode()))
            self.assertEqual(entry["userText"], f'<skill name="{name}" location="{path}">\nReferences are relative to {path.parent}.\n'
                             f"\n{body}\n</skill>\n\n{CALLER_ARGS[name]}")
            self.assertNotRegex(entry["userText"].replace(str(self.relocated), "<kit>").lower(), PRIVATE_MARKERS)
            for clause in SKILL_CLAUSES[name]:
                self.assertIn(clause, entry["userText"], name)
            if name == "setup":
                for target in ("docs/knowledge-hub.md", "scripts/knowledge.py"):
                    relative = os.path.relpath(self.relocated / target, path.parent)
                    self.assertIn(f"]({relative})", entry["userText"])
                    self.assertTrue((self.relocated / target).is_file())
                self.assertIn("An explicit PRD lookup returns an index of citations, not task context or approval", entry["userText"])
            if name == "factory":
                expected = {"factory/COORDINATOR.md", "factory/WORKER.md", "factory/REVIEWER.md",
                            "references/factory-contract.md", "scripts/factory-job.py", "scripts/factory-alignment.py"}
                actual = {(path.parent / link).resolve().relative_to(self.relocated).as_posix()
                          for link in re.findall(r"\]\(([^)]+)\)", entry["userText"])}
                self.assertLessEqual(expected, actual)
                for target in actual:
                    self.assertTrue((self.relocated / target).is_file(), target)

    def test_relocated_probe_fresh_home_and_discoverable_skills(self) -> None:
        write(self.fx.workspace / "decisions.md", "Approved decision: output CSV.\n")
        write(self.fx.workspace / "example.csv", "name;state\ninput;fixed\n")
        write(self.fx.workspace / "task.md", "Retention is undecided; the requirement owner must decide.\n")
        self.assertEqual(list(self.fx.home.iterdir()), [])
        self.install()
        self.check_good_probe(json.loads(self.probe().stdout), None)

    def test_real_trusted_project_append_shadows_instead_of_merging(self) -> None:
        self.fx.user_settings()
        self.install()
        self.check_good_probe(json.loads(self.probe().stdout), "SYNTHETIC user-only appendix")

    def test_probe_fails_without_declaration_or_importable_sdk(self) -> None:
        self.install()
        for module, reason in (("", "missing absolute DCC_PI_SDK_MODULE"), (str(self.root / "missing.js"), "Cannot find module")):
            with self.subTest(module=module):
                result = self.probe(status=1, sdk=module)
                self.assertIn("Pi resource evidence unavailable", result.stderr)
                self.assertIn(reason, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_missing_append_cannot_pass_loading_evidence(self) -> None:
        self.install()
        (self.fx.workspace / ".pi/APPEND_SYSTEM.md").unlink()
        result = json.loads(self.probe(status=1).stdout)
        self.assertFalse(result["ok"])
        self.assertEqual(result["trusted"]["appendSources"], [])
        self.assertIn("trusted: wrong APPEND_SYSTEM source", result["errors"])

    def test_each_missing_skill_is_a_real_probe_failure(self) -> None:
        self.install()
        path = self.fx.workspace / ".pi/settings.json"
        original = json.loads(path.read_text())
        for name in SKILLS:
            with self.subTest(skill=name):
                write(path, json.dumps({"skills": [item for item in original["skills"] if f"/skills/{name}/" not in item]}))
                data = json.loads(self.probe(status=1).stdout)
                self.assertFalse(data["ok"])
                self.assertNotIn(name, {item["name"] for item in data["trusted"]["skills"]})
                self.assertIn(f"trusted: wrong source or not model-discoverable: {name}", data["errors"])
                self.assertIn(f"trusted: incomplete Pi command expansion: {name}", data["errors"])

    def test_duplicate_name_fails_probe_even_if_expected_path_wins(self) -> None:
        self.install()
        duplicate = self.fx.workspace / ".pi/skills/duplicate/SKILL.md"
        write(duplicate, "---\nname: factory\ndescription: 'synthetic collision'\n---\n# Not the kit factory\n")
        result = json.loads(self.probe(status=1).stdout)
        self.assertFalse(result["ok"])
        self.assertIn("trusted: Pi skill diagnostics (including collisions) must be empty", result["errors"])
        diagnostic = next(item for item in result["trusted"]["diagnostics"] if item["type"] == "collision")
        self.assertIn("factory", diagnostic["message"])
        self.assertIn(str(duplicate), json.dumps(diagnostic))
        settings = self.fx.workspace / ".pi/settings.json"
        contents = json.loads(settings.read_text())
        write(settings, json.dumps({"skills": [path for path in contents["skills"] if not path.endswith("/factory/SKILL.md")]}))
        shadowed = json.loads(self.probe(status=1).stdout)
        self.assertIn("trusted: wrong source or not model-discoverable: factory", shadowed["errors"])
        self.assertIn("trusted: incomplete Pi command expansion: factory", shadowed["errors"])
        self.assertIn(str(duplicate), {skill["filePath"] for skill in shadowed["trusted"]["skills"]})


if __name__ == "__main__":
    unittest.main()
