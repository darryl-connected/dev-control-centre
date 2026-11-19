#!/usr/bin/env python3
"""
Offline tests for scripts/factory-job.py and the shared contract module.

Real git repositories and worktrees are built in temporary directories. No
network, no production repo, no commits outside the fixture repositories.

Run: python -B -m unittest discover -s tests -p 'test_factory_job.py' -v
     python -B tests/test_factory_job.py
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACKAGE / "scripts" / "lib"))

import factory_contract as contract

SCRIPT = PACKAGE / "scripts" / "factory-job.py"
SOL = "openai-codex/gpt-6.1-sol"
WRITER = "openai-codex/gpt-6.2-sol"
BASE_CONTENTS = {
    "AGENTS.md": "# Repo rules\n\nRun the checks before reporting.\n",
    "docs/readme.md": "readme\n",
    "src/app.py": "def main():\n    return 1\n",
    "tests/test_app.py": "def test_main():\n    assert True\n",
    ".gitignore": "dist/\n",
}


def clean_env(home: Path) -> dict[str, str]:
    # Pass only what the subprocess needs. This is not a filesystem sandbox.
    return {
        "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
        "PATH": os.environ["PATH"], "PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
    }


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_digest(data: dict) -> str:
    return digest(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def fixture_file_map(root: Path) -> dict:
    # Independent fixture oracle. Fixture regular files are all visible except dist/.
    files = {}
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root)
        if relative.parts[0] not in {".git", "dist"} and item.is_file():
            mode = "100755" if item.stat().st_mode & 0o111 else "100644"
            files[relative.as_posix()] = {"sha256": digest(item.read_bytes()), "mode": mode}
    return files


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = root / "repo"
        self.repo.mkdir(parents=True)
        self.home = root / "home"
        self.home.mkdir()
        self._git("init", "-q", "-b", "main", "--object-format=sha1")
        self._git("config", "user.email", "fixture@example.invalid")
        self._git("config", "user.name", "Factory Fixture")
        for path, text in BASE_CONTENTS.items():
            self.write(path, text)
        self.base_commit = self.commit("base")

    def _git(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", "-C", str(cwd or self.repo), *args],
            capture_output=True,
            encoding="utf-8",
            check=False,
            env=clean_env(self.home),
        )
        if check and result.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}{result.stdout}")
        return result

    def write(self, path: str, text: str, mode: int | None = None) -> None:
        full = self.repo / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")
        if mode is not None:
            full.chmod(mode)

    def commit(self, message: str) -> str:
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def stage(self, path: str) -> None:
        self._git("add", "--", path)

    def baseline(self) -> dict:
        return {
            "commit": self._git("rev-parse", "HEAD").stdout.strip(),
            "status": self._git("status", "--porcelain=v1", "-uall").stdout.splitlines(),
            "index_digest": digest(self._git("ls-files", "--stage", "-z").stdout.encode("utf-8")),
            "files": fixture_file_map(self.repo),
        }

    def target_state(self) -> tuple:
        files = {
            p.relative_to(self.repo).as_posix(): (p.read_bytes(), p.stat().st_mode)
            for p in self.repo.rglob("*") if p.is_file() and ".git" not in p.relative_to(self.repo).parts
        }
        return (
            files, (self.repo / ".git/index").read_bytes(), (self.repo / ".git/HEAD").read_bytes(),
            self._git("show-ref", "--head").stdout,
        )

    def worktree(self, name: str, branch: str | None = None) -> Path:
        path = self.root / name
        branch = branch or f"factory-{name}"
        self._git("worktree", "add", "-q", "-b", branch, str(path), "HEAD")
        return path


class JobCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="factory-job-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fixture = Fixture(self.tmp)
        self.repo = self.fixture.repo

    # -- helpers ---------------------------------------------------------- #

    def manifest(self, writer: Path, **overrides) -> dict:
        data = {
            "version": 1, "task": {"id": "FIX-01", "goal": "Change the return value"},
            "repo": str(self.repo), "base": self.fixture.baseline(),
            "writer": {"worktree": str(writer), "model": WRITER},
            "allowed_paths": ["src/**", "tests/test_app.py"], "frozen": {},
            "tier": {"id": "B", "reason": "runtime code"},
            "decisions": [{"id": "D1", "source": "approved fixture requirements"}],
            "acceptance": [{
                "id": "C1", "source": "D1", "input": "fixture input", "action": "run main",
                "expected": "main returns 2", "observation": "read return value",
            }],
            "guards": [{
                "id": "G1", "decisions": ["D1"], "command": "python -m unittest -q",
                "boundary": "app public callable", "mutation": "restore previous constant",
                "expected_failure": "expected 2 but observed 1", "limits": "not a load test",
            }],
            "risks": ["previous constant"], "boundaries": ["local Git, no live services"],
            "out_of_scope": ["production"], "verification": ["python -m unittest -q"],
            "evidence": "exit and observed value", "stopping_point": "stop on drift",
            "report": "record exits and skips", "lint_debt": [],
            "budgets": {"writer": {"minutes": 17, "calls": 23}, "reviewer": {"minutes": 19, "calls": 29}},
        }
        data.update(overrides)
        return data

    def sync(self, source: Path, target: Path) -> None:
        files = fixture_file_map(source)
        for path, entry in files.items():
            full = target / path
            full.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / path, full)
            full.chmod(int(entry["mode"], 8))

    def write_candidate(self, candidate: Path, path: str, text: str) -> None:
        full = candidate / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")

    def receipt(self, manifest: dict, candidate: Path, review: Path, **overrides) -> dict:
        files = fixture_file_map(candidate)
        manifest_value = json_digest(manifest)
        data = {
            "version": 1,
            "manifest_digest": manifest_value,
            "candidate_digest": json_digest({"manifest": manifest_value, "files": files}),
            "verdict": "approved",
            "reviewer": {"model": SOL, "worktree": str(review)},
            "findings": [],
            "verification": [
                {"command": command, "status": "pass", "evidence": "exit 0", "skipped": []}
                for command in manifest["verification"]
            ],
            "mutations": [
                {"guard": guard["id"], "result": "failed-as-expected", "evidence": "observed failure"}
                for guard in manifest["guards"]
            ],
            "not_verified": [],
        }
        data.update(overrides)
        return data

    def build_candidate(self, name: str = "candidate", edit: bool = True) -> Path:
        candidate = self.fixture.worktree(name)
        if edit:
            self.write_candidate(candidate, "src/app.py", "def main():\n    return 2\n")
            self.write_candidate(candidate, "src/feature.py", "FEATURE = True\n")
        return candidate

    def build_review(self, candidate: Path, name: str = "review") -> Path:
        review = self.fixture.worktree(name)
        self.sync(candidate, review)
        return review

    def assert_ok(self, result: dict) -> None:
        self.assertTrue(result["ok"], json.dumps(result.get("errors"), indent=2))

    def assert_fails(self, result: dict, fragment: str) -> None:
        self.assertFalse(result["ok"], f"expected failure mentioning {fragment!r}")
        joined = " | ".join(result["errors"])
        self.assertIn(fragment, joined, joined)

    # -- manifest validation ---------------------------------------------- #

    def test_example_manifest_renders_every_contract_field(self) -> None:
        manifest = self.manifest(self.tmp / "writer")
        errors, _ = contract.validate_manifest(manifest)
        self.assertEqual(errors, [])
        brief = contract.render_brief(manifest)
        for label in (
            "Decision traceability",
            "Defect demonstration",
            "Acceptance examples",
            "Risk cases",
            "Boundaries",
            "Out of scope",
            "Verification commands",
            "What each guard does not prove",
            "Budget:",
            "FINISH:",
        ):
            self.assertIn(label, brief)
        self.assertEqual(brief, contract.render_brief(manifest))

    def test_invalid_manifests_are_rejected(self) -> None:
        base = self.manifest(self.tmp / "writer")
        cases = {
            "empty goal": lambda m: m["task"].__setitem__("goal", ""),
            "bool budget": lambda m: m["budgets"]["writer"].__setitem__("minutes", True),
            "zero budget": lambda m: m["budgets"]["reviewer"].__setitem__("calls", 0),
            "unmapped decision": lambda m: m["decisions"].append({"id": "D2", "source": "nowhere"}),
            "unknown guard decision": lambda m: m["guards"][0]["decisions"].append("D9"),
            "blank mutation": lambda m: m["guards"][0].__setitem__("mutation", ""),
            "unknown key": lambda m: m.__setitem__("extra", True),
            "unsafe pattern": lambda m: m.__setitem__("allowed_paths", ["../evil.py"]),
            "absolute pattern": lambda m: m.__setitem__("allowed_paths", ["/etc/passwd"]),
            "sha not full": lambda m: m["base"].__setitem__("commit", "deadbee"),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                manifest = copy.deepcopy(base)
                mutate(manifest)
                errors, _ = contract.validate_manifest(manifest)
                self.assertTrue(errors, f"{name} was accepted")

    def test_unprefixed_sha_and_empty_labels_fail_preflight(self) -> None:
        manifest = self.manifest(self.tmp / "writer")
        manifest["base"]["commit"] = "a" * 40
        result = contract.preflight(manifest)
        self.assertFalse(result["ok"])
        self.assertIn("commit does not exist", " | ".join(result["errors"]))

    # -- baseline ---------------------------------------------------------- #

    def test_preflight_passes_on_clean_baseline(self) -> None:
        manifest = self.manifest(self.tmp / "writer")
        self.assert_ok(contract.preflight(manifest, root=PACKAGE))

    def test_preflight_accepts_staged_only_baseline(self) -> None:
        self.fixture.write("src/staged.py", "STAGED = True\n")
        self.fixture.stage("src/staged.py")
        manifest = self.manifest(self.tmp / "writer")
        self.assert_ok(contract.preflight(manifest, root=PACKAGE))

    def test_preflight_rejects_unstaged_baseline(self) -> None:
        self.fixture.write("src/app.py", "def main():\n    return 3\n")
        with self.assertRaises(contract.ContractError):
            contract.capture_baseline(self.repo)

    def test_snapshot_rejects_staged_deletion_and_invalid_baseline_fields(self) -> None:
        manifest = self.manifest(self.tmp / "writer")
        for field in ("commit", "status", "index_digest", "files"):
            with self.subTest(field):
                broken = copy.deepcopy(manifest)
                del broken["base"][field]
                errors, _ = contract.validate_manifest(broken)
                self.assertTrue(any(f"base.{field}" in error for error in errors), errors)
        self.fixture._git("rm", "--", "src/app.py")
        path = self.tmp / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        before = self.fixture.target_state()
        snapshot = self.run_cli("snapshot", str(path))
        self.assertEqual(snapshot.returncode, 2, snapshot.stdout + snapshot.stderr)
        self.assertIn("staged deletion", snapshot.stderr)
        self.assertEqual(before, self.fixture.target_state())

    def test_snapshot_declines_repository_clean_filters(self) -> None:
        manifest = self.manifest(self.tmp / "writer")
        path = self.tmp / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        sentinel = self.tmp / "filter-ran"
        self.fixture._git("config", "filter.fixture.clean", f"touch '{sentinel}'; cat")
        (self.repo / ".git/info/attributes").write_text("src/app.py filter=fixture\n", encoding="utf-8")
        self.fixture.write("src/app.py", "change to force Git to inspect the file\n")
        before = self.fixture.target_state()
        snapshot = self.run_cli("snapshot", str(path))
        self.assertEqual(snapshot.returncode, 2, snapshot.stdout + snapshot.stderr)
        self.assertIn("configured process or clean filters", snapshot.stderr)
        self.assertFalse(sentinel.exists())
        self.assertEqual(before, self.fixture.target_state())

    def test_preflight_rejects_untracked_baseline(self) -> None:
        self.fixture.write("src/loose.py", "LOOSE = True\n")
        with self.assertRaises(contract.ContractError):
            contract.capture_baseline(self.repo)

    def test_preflight_rejects_baseline_drift(self) -> None:
        manifest = self.manifest(self.tmp / "writer")
        self.fixture.write("src/app.py", "def main():\n    return 4\n")
        self.assert_fails(contract.preflight(manifest, root=PACKAGE), "base.status")

        self.fixture._git("checkout", "--", ".")
        manifest = self.manifest(self.tmp / "writer")
        self.fixture.write("src/other.py", "OTHER = 1\n")
        self.fixture.stage("src/other.py")
        self.assert_fails(contract.preflight(manifest, root=PACKAGE), "index")

    def test_preflight_rejects_head_drift(self) -> None:
        manifest = self.manifest(self.tmp / "writer")
        self.fixture.write("docs/readme.md", "new readme\n")
        self.fixture.commit("move head")
        self.assert_fails(contract.preflight(manifest, root=PACKAGE), "base.commit")

    # -- integration positive --------------------------------------------- #

    def test_integration_accepts_reviewed_candidate(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        manifest = self.manifest(candidate)
        receipt = self.receipt(manifest, candidate, review)
        self.assert_ok(contract.integration(manifest, candidate, receipt, root=PACKAGE))

    def test_integration_accepts_staged_baseline_copied_into_candidate(self) -> None:
        self.fixture.write("src/staged.py", "STAGED = True\n")
        self.fixture.stage("src/staged.py")
        manifest = self.manifest(self.tmp / "writer")
        candidate = self.fixture.worktree("staged-candidate")
        self.sync(self.repo, candidate)
        review = self.build_review(candidate, "staged-review")
        manifest["writer"]["worktree"] = str(candidate)
        receipt = self.receipt(manifest, candidate, review)
        self.assert_ok(contract.integration(manifest, candidate, receipt, root=PACKAGE))

    def test_integration_records_skips_as_not_verified(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        manifest = self.manifest(candidate)
        receipt = self.receipt(manifest, candidate, review)
        receipt["verification"][0]["skipped"] = ["device-gpu"]
        result = contract.integration(manifest, candidate, receipt, root=PACKAGE)
        self.assert_ok(result)
        self.assertTrue(any("NOT VERIFIED" in note for note in result["notes"]))

    # -- integration negative: paths, hashes, baseline --------------------- #

    def test_integration_rejects_changes_outside_allowlist(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        manifest = self.manifest(candidate, allowed_paths=["src/app.py", "src/feature.py"])
        self.assert_integration(manifest, candidate, self.receipt(manifest, candidate, review))

        self.write_candidate(candidate, "docs/extra.md", "extra\n")
        self.sync(candidate, review)
        self.assert_integration(
            manifest, candidate, self.receipt(manifest, candidate, review), "outside the allowlist: docs/extra.md",
        )

    def test_integration_rejects_exact_prefix_bypass(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        manifest = self.manifest(candidate, allowed_paths=["src/app.py", "src/feature.py"])
        self.assert_integration(manifest, candidate, self.receipt(manifest, candidate, review))
        self.write_candidate(candidate, "src/app.py.bak", "backup\n")
        self.sync(candidate, review)
        self.assert_integration(
            manifest, candidate, self.receipt(manifest, candidate, review), "outside the allowlist: src/app.py.bak",
        )

    def test_integration_rejects_dropped_baseline_and_deletions(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        manifest = self.manifest(candidate)
        self.assert_integration(manifest, candidate, self.receipt(manifest, candidate, review))
        # An unstaged deletion is represented explicitly in the working-tree map.
        (candidate / "src/app.py").unlink()
        (review / "src/app.py").unlink()
        receipt = self.receipt(manifest, candidate, review)
        files = fixture_file_map(candidate) | {"src/app.py": {"deleted": True}}
        receipt["candidate_digest"] = json_digest({"manifest": receipt["manifest_digest"], "files": files})
        self.assert_integration(manifest, candidate, receipt, "baseline prerequisite dropped: src/app.py")
        # After staging the deletion, the path is absent from the content map.
        for worktree in (candidate, review):
            self.fixture._git("add", "-u", "--", "src/app.py", cwd=worktree)
        receipt = self.receipt(manifest, candidate, review)
        self.assert_integration(manifest, candidate, receipt, "baseline prerequisite dropped: src/app.py")

    def test_integration_rejects_frozen_change(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        path = "docs/readme.md"
        manifest = self.manifest(candidate, allowed_paths=["src/**", path])
        manifest["frozen"] = {path: digest(BASE_CONTENTS[path].encode())}
        self.assert_integration(manifest, candidate, self.receipt(manifest, candidate, review))

        self.write_candidate(candidate, path, "edited frozen file\n")
        self.sync(candidate, review)
        self.assert_integration(
            manifest, candidate, self.receipt(manifest, candidate, review), "frozen: docs/readme.md does not match its reviewed hash",
        )
        self.write_candidate(candidate, path, BASE_CONTENTS[path])
        (candidate / path).chmod(0o755)
        self.sync(candidate, review)
        self.assert_integration(
            manifest, candidate, self.receipt(manifest, candidate, review), "frozen: docs/readme.md does not match its baseline mode",
        )

    def test_gates_reject_target_content_drift_with_identical_status_and_index(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        self.fixture._git("update-index", "--assume-unchanged", "src/app.py")
        manifest = self.manifest(candidate)
        receipt = self.receipt(manifest, candidate, review)
        self.assert_integration(manifest, candidate, receipt)
        path = self.tmp / "manifest.json"
        before = self.fixture.target_state()
        clean = self.run_cli("preflight", str(path), "--json")
        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
        self.assertEqual(before, self.fixture.target_state())

        self.fixture.write("src/app.py", "changed despite the unchanged hint\n")
        before = self.fixture.target_state()
        drift = self.run_cli("preflight", str(path), "--json")
        self.assertEqual(drift.returncode, 1, drift.stdout + drift.stderr)
        self.assertEqual(json.loads(drift.stdout)["errors"], ["base.files: target file contents changed since the snapshot"])
        self.assertEqual(before, self.fixture.target_state())
        self.assert_integration(manifest, candidate, receipt, "base.files: target file contents changed")

    def test_integration_rejects_mode_change_outside_allowlist(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        manifest = self.manifest(candidate)
        (candidate / "docs/readme.md").chmod(0o755)
        (review / "docs/readme.md").chmod(0o755)
        receipt = self.receipt(manifest, candidate, review)
        self.assert_fails(
            contract.integration(manifest, candidate, receipt, root=PACKAGE),
            "docs/readme.md",
        )

    def test_integration_rejects_symlink(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        manifest = self.manifest(candidate)
        receipt = self.receipt(manifest, candidate, review)
        link = candidate / "src/link.py"
        os.symlink("app.py", link)
        self.addCleanup(lambda: link.unlink(missing_ok=True))
        result = contract.integration(manifest, candidate, receipt, root=PACKAGE)
        self.assert_fails(result, "symlink")

    def test_integration_rejects_candidate_changed_after_review(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        manifest = self.manifest(candidate)
        receipt = self.receipt(manifest, candidate, review)
        self.assert_integration(manifest, candidate, receipt)
        self.write_candidate(candidate, "src/feature.py", "FEATURE = False\n")
        self.sync(candidate, review)
        self.assert_integration(manifest, candidate, receipt, "review.candidate_digest")

    def test_integration_rejects_manifest_changed_after_review(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        manifest = self.manifest(candidate)
        receipt = self.receipt(manifest, candidate, review)
        self.assert_integration(manifest, candidate, receipt)
        altered = copy.deepcopy(manifest)
        altered["task"]["goal"] = "a different goal"
        receipt["candidate_digest"] = self.receipt(altered, candidate, review)["candidate_digest"]
        self.assert_integration(altered, candidate, receipt, "review.manifest_digest")

    def test_ignored_build_output_is_outside_the_gate(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        manifest = self.manifest(candidate)
        receipt = self.receipt(manifest, candidate, review)
        (candidate / "dist").mkdir(exist_ok=True)
        (candidate / "dist/out.js").write_text("generated\n", encoding="utf-8")
        self.assertNotIn("dist/out.js", contract.content_map(candidate))
        result = contract.integration(manifest, candidate, receipt, root=PACKAGE)
        self.assert_ok(result)
        self.assertIn("does not replay tests", result["gate_limit"])

    # -- integration negative: review attestation -------------------------- #

    def test_integration_rejects_bad_review_attestations(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        manifest = self.manifest(candidate)
        good = self.receipt(manifest, candidate, review)
        self.assert_integration(manifest, candidate, good)

        def mutate(mutator):
            receipt = copy.deepcopy(good)
            mutator(receipt)
            return receipt

        cases = {
            "acceptance review must run on Sol": mutate(
                lambda r: r["reviewer"].__setitem__("model", "deepseek/deepseek-flash")
            ),
            "review.verdict": mutate(lambda r: r.__setitem__("verdict", "needs work")),
            "must be distinct": mutate(
                lambda r: r["reviewer"].__setitem__("worktree", str(candidate))
            ),
            "recognized severity": mutate(lambda r: r["findings"].append(
                {"id": "F1", "severity": "hgh", "status": "open", "description": "bad"},
            )),
            "unresolved blocking finding": mutate(
                lambda r: r["findings"].append(
                    {"id": "F1", "severity": "blocking", "status": "open", "description": "bad"}
                )
            ),
            "no record for required command": mutate(lambda r: r["verification"].pop()),
            "not verified": mutate(lambda r: r["verification"][0].__setitem__("status", "not-verified")),
            "no mutation evidence": mutate(lambda r: r["mutations"].pop()),
            "did not fail under the mutation": mutate(lambda r: r["mutations"][0].__setitem__("result", "survived")),
            "must state what was observed": mutate(lambda r: r["verification"][0].__setitem__("evidence", "")),
            "must state the observed failure": mutate(lambda r: r["mutations"][0].__setitem__("evidence", "")),
            "skipped: must be a list": mutate(lambda r: r["verification"][0].pop("skipped")),
            "duplicate command record": mutate(lambda r: r["verification"].append(r["verification"][0])),
            "duplicate mutation record": mutate(lambda r: r["mutations"].append(r["mutations"][0])),
        }
        for reason, receipt in cases.items():
            with self.subTest(reason):
                self.assert_integration(manifest, candidate, receipt, reason)

    def test_integration_rejects_reviewer_model_matching_writer(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        manifest = self.manifest(candidate)
        receipt = self.receipt(manifest, candidate, review)
        self.assert_integration(manifest, candidate, receipt)
        for label in (WRITER, "other-provider/GPT-6.2-SOL", "gpt-6.2-sol"):
            with self.subTest(label):
                receipt["reviewer"]["model"] = label
                self.assert_integration(manifest, candidate, receipt, "must not be the writer's model")

    def test_integration_rejects_review_tree_content_drift(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        manifest = self.manifest(candidate)
        receipt = self.receipt(manifest, candidate, review)
        self.assert_integration(manifest, candidate, receipt)
        extra = review / "docs/extra.md"
        extra.write_text("review notes in the tree\n", encoding="utf-8")
        self.assert_integration(manifest, candidate, receipt, "reviewed files do not match")

        unrelated = Fixture(self.tmp / "unrelated-repo")
        self.sync(candidate, unrelated.repo)
        receipt["reviewer"]["worktree"] = str(unrelated.repo)
        self.assert_integration(manifest, candidate, receipt, "must belong to the same repository")

    # -- alignment wiring -------------------------------------------------- #

    def test_preflight_and_integration_block_on_alignment_failure(self) -> None:
        empty_root = self.tmp / "missing-package"
        empty_root.mkdir()
        manifest = self.manifest(self.tmp / "writer")
        self.assert_fails(contract.preflight(manifest, root=empty_root), "alignment")

        candidate = self.build_candidate()
        review = self.build_review(candidate)
        receipt = self.receipt(manifest, candidate, review)
        self.assert_fails(contract.integration(manifest, candidate, receipt, root=empty_root), "alignment")

    # -- CLI --------------------------------------------------------------- #

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *args],
            cwd=self.tmp,
            env=clean_env(self.fixture.home),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_preflight_json_and_rejection(self) -> None:
        manifest = self.manifest(self.tmp / "writer")
        path = self.tmp / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.run_cli("preflight", str(path), "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertIn("duration_ms", payload)
        self.assertGreaterEqual(payload["duration_ms"], 0)

        manifest["task"]["goal"] = ""
        path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.run_cli("preflight", str(path), "--json")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["ok"])

    def test_cli_snapshot_render_and_candidate(self) -> None:
        skeleton = json.loads(self.run_cli("example").stdout)
        self.assertEqual(skeleton["version"], 1)
        manifest = self.manifest(self.tmp / "writer")
        path = self.tmp / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")

        rendered = self.run_cli("render", str(path))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertIn("Decision traceability", rendered.stdout)

        candidate = self.build_candidate()
        manifest["writer"]["worktree"] = str(candidate)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        payload = json.loads(self.run_cli("candidate", str(path), "--candidate", str(candidate)).stdout)
        self.assertEqual(payload["candidate_digest"], self.receipt(manifest, candidate, candidate)["candidate_digest"])
        self.assertEqual(payload["files"], fixture_file_map(candidate))

    def test_cli_snapshot_captures_baseline_without_overwriting(self) -> None:
        skeleton = contract.example_manifest(str(self.repo))
        skeleton["writer"]["worktree"] = str(self.tmp / "writer")
        path = self.tmp / "manifest.json"
        path.write_text(json.dumps(skeleton), encoding="utf-8")
        before = path.read_bytes()
        result = self.run_cli("snapshot", str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["base"]["commit"], self.fixture.base_commit)
        self.assertEqual(data["base"], self.fixture.baseline())
        self.assertEqual(path.read_bytes(), before, "snapshot must not overwrite the manifest")

    def assert_integration(self, manifest: dict, candidate: Path, receipt: dict, reason: str = "") -> dict:
        manifest_path = self.tmp / "manifest.json"
        receipt_path = self.tmp / "receipt.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        before = self.fixture.target_state()
        result = self.run_cli(
            "integration",
            str(manifest_path),
            "--candidate",
            str(candidate),
            "--review",
            str(receipt_path),
            "--json",
        )
        self.assertEqual(before, self.fixture.target_state(), "gate must not change target files, index or refs")
        self.assertEqual(result.returncode, 1 if reason else 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        if reason:
            self.assert_fails(payload, reason)
            self.assertEqual(len(payload["errors"]), 1, payload["errors"])
        else:
            self.assert_ok(payload)
        return payload

    def test_cli_integration_positive_and_never_runs_attested_command(self) -> None:
        candidate = self.build_candidate()
        review = self.build_review(candidate)
        sentinel = self.tmp / "would-run"
        manifest = self.manifest(candidate, verification=[f"touch '{sentinel}'"])
        manifest["guards"][0]["command"] = f"touch '{sentinel}'"
        receipt = self.receipt(manifest, candidate, review)
        payload = self.assert_integration(manifest, candidate, receipt)
        self.assertEqual(payload["changed_paths"], ["src/app.py", "src/feature.py"])
        self.assertFalse(sentinel.exists(), "gate must not execute attested command strings")


if __name__ == "__main__":
    unittest.main(verbosity=2)
