"""Checked, disjoint coverage and prerequisites for the two offline QA profiles."""

from __future__ import annotations

import ast
import ctypes
import os
import platform
import shutil
import subprocess
import sys
import unittest
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NATIVE = "native"
LINUX_SECURITY = "linux-security"
PROFILE_SUITES = {
    NATIVE: (
        "test_clickup", "test_draft", "test_e2e_clickup", "test_e2e_draft",
        "test_e2e_factory.DistributionTest", "test_e2e_factory_run", "test_e2e_knowledge",
        "test_e2e_pi_setup", "test_e2e_prepare", "test_factory_alignment", "test_factory_inbox",
        "test_factory_job", "test_factory_run", "test_instruction_packaging", "test_knowledge",
        "test_native_factory_inbox", "test_prepare", "test_setup", "test_validate_brief",
        "test_verification_profiles", "test_verify_suite", "test_workspace_policy",
    ),
    LINUX_SECURITY: ("test_e2e_factory.RelocatedHandoffTest", "test_e2e_factory_inbox.InboxE2E"),
}
PROFILE_RESOURCES = (
    "tests/fixtures/factory-inbox-provider.ts",
    "tests/fixtures/factory-run-provider.ts",
    "tests/fixtures/verification/observe-pi-entry.cjs",
)
FileRequirement = tuple[str, str, bool]
PI: FileRequirement = ("DCC_PI_EXECUTABLE", "absolute path to the pinned Pi CLI", True)
NATIVE_FILES: tuple[FileRequirement, ...] = (
    PI,
    ("DCC_HERDR_EXECUTABLE", "absolute path to the Herdr CLI", True),
    ("DCC_PI_SDK_MODULE", "absolute path to the installed Pi SDK entry file", False),
    ("DCC_B3_NODE", "absolute path to the Node runtime used by OpenSpec", True),
    ("DCC_B3_OPENSPEC", "absolute path to the installed OpenSpec entry file", False),
)
# None means the requirement passed. Do not display environment values.
Check = tuple[str, str | None]


def catalog(root: Path) -> set[str]:
    """Read test declarations without importing modules or doing unittest discovery.

    The packaged layout uses top-level classes with statically named methods.
    The child separately checks actual unittest IDs against this catalog.
    """
    suite = root / "tests"
    modules = sorted(suite.rglob("test_*.py"))
    if not modules:
        raise ValueError("no test_*.py modules under tests")
    declared: set[str] = set()
    for module in modules:
        if module.parent != suite or module.is_symlink():
            raise ValueError(f"unsupported test module path: {module.relative_to(root)}")
        tree = ast.parse(module.read_bytes(), filename=str(module))
        names = [f"{module.stem}.{group.name}.{method.name}"
                 for group in tree.body if isinstance(group, ast.ClassDef)
                 for method in group.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and method.name.startswith("test_")]
        if not names:
            raise ValueError(f"no static test methods declared in {module.name}")
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate test declarations in {module.name}")
        declared.update(names)
    return declared


def classify(declared: set[str], suites: dict[str, tuple[str, ...]]) -> dict[str, set[str]]:
    chosen: dict[str, set[str]] = {name: set() for name in suites}
    assigned: set[str] = set()
    problems = []
    for profile, selectors in suites.items():
        for selector in selectors:
            matches = {name for name in declared if name.startswith(selector + ".")}
            if not matches:
                problems.append(f"{profile} selector has no tests: {selector}")
            for duplicate in sorted(assigned & matches):
                problems.append(f"duplicate coverage: {duplicate}")
            chosen[profile].update(matches)
            assigned.update(matches)
    problems.extend(f"unclassified test: {name}" for name in sorted(declared - assigned))
    if problems:
        raise ValueError("; ".join(problems))
    return chosen


def coverage(root: Path = ROOT) -> dict[str, set[str]]:
    missing = [name for name in PROFILE_RESOURCES if not (root / name).is_file()]
    if missing:
        raise ValueError("missing packaged fixture resources: " + ", ".join(missing))
    return classify(catalog(root), PROFILE_SUITES)


def file_problem(value: str | None, expectation: str, executable: bool) -> str | None:
    if not value:
        return f"is not set; expected {expectation}"
    path = Path(value)
    if not path.is_absolute():
        return f"is not an absolute path; expected {expectation}"
    if not path.is_file():
        return f"does not name an existing file; expected {expectation}"
    if executable and not os.access(path, os.X_OK):
        return f"names a file that is not executable; expected {expectation}"
    return None


def namespace_problem(executable: str) -> str | None:
    try:
        probe = subprocess.run([executable, "-Urn", "--", "/bin/true"], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return f"user/network namespace probe could not run ({type(error).__name__})"
    return f"user/network namespace probe failed with status {probe.returncode}" if probe.returncode else None


def linux_kernel_checks() -> list[Check]:
    proc = Path(f"/proc/self/task/{os.getpid()}/children")
    try:
        proc.read_bytes()
        proc_problem = None
    except OSError:
        proc_problem = "readable /proc/self/task/<pid>/children required"
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        descriptor = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        inotify_problem = f"inotify_init1 failed (errno {ctypes.get_errno()})" if descriptor < 0 else None
        if descriptor >= 0:
            os.close(descriptor)
    except AttributeError:
        inotify_problem = "libc does not expose inotify_init1"
    landlock_problem = None
    if platform.machine().lower() not in {"x86_64", "amd64", "aarch64", "arm64"} or not hasattr(os, "O_PATH"):
        landlock_problem = "fixture needs Linux x86_64/arm64 Landlock ABI and O_PATH"
    elif libc.syscall(444, None, 0, 1) < 1:  # LANDLOCK_CREATE_RULESET_VERSION
        landlock_problem = f"Landlock ABI query failed (errno {ctypes.get_errno()})"
    return [("/proc", proc_problem), ("inotify", inotify_problem), ("Landlock", landlock_problem)]


def requirements(profile: str) -> list[Check]:
    host = sys.platform
    result: list[Check]
    files: tuple[FileRequirement, ...]
    if profile == LINUX_SECURITY:
        result = [("platform", None if host.startswith("linux") else "linux-security requires Linux")]
        files = (PI,)
    else:
        supported = host == "darwin" or host.startswith("linux")
        result = [("platform", None if supported else "native profile supports macOS and Linux; Windows is NOT VERIFIED")]
        files = NATIVE_FILES
    for name, expectation, executable in files:
        result.append((name, file_problem(os.environ.get(name), expectation, executable)))
    if profile == LINUX_SECURITY and host.startswith("linux"):
        executable_path = shutil.which("unshare")
        result.append(("unshare", namespace_problem(executable_path) if executable_path else "not found on PATH"))
        result.extend(linux_kernel_checks())
    elif profile == NATIVE:
        for tool in ("git", "node"):
            result.append((tool, None if shutil.which(tool) else "not found on PATH"))
        if hasattr(os, "geteuid"):
            result.append(("non-root", None if os.geteuid() else "real publisher write-denial fixture requires a non-root owner"))
    return result


def test_cases(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_cases(item)
        else:
            yield item


def run_selected(profile: str) -> int:
    """Child interpreter, reached only after CLI checks in the parent interpreter."""
    expected = coverage()[profile]
    sys.path.insert(0, str(ROOT / "tests"))
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(PROFILE_SUITES[profile])
    if loader.errors:
        print("\n".join(str(error) for error in loader.errors), file=sys.stderr)
        return 1
    observed = [test.id() for test in test_cases(suite)]
    actual = set(observed)
    if actual != expected or len(observed) != len(actual):
        print(f"verify-suite: loaded test IDs differ from static coverage; missing={sorted(expected - actual)}, "
              f"unexpected={sorted(actual - expected)}, duplicates={len(observed) - len(actual)}", file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    for test, reason in result.skipped:
        print(f"NOT VERIFIED  {test.id()}: {reason}", file=sys.stderr)
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == "__main__":
    sys.exit(run_selected(sys.argv[1]))
