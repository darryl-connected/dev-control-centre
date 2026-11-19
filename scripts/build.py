#!/usr/bin/env python3
"""Build an offline distribution. No installation, publishing or Git writes."""

from __future__ import annotations

import argparse
import gzip
import io
import os
import sys
import tarfile
import tempfile
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_NAME = "dev-control-centre.tar.gz"
MEMBERS = (
    "AGENTS.md",
    "LICENSE",
    "README.md",
    "docs/pi-setup.md",
    "docs/scope.md",
    "factory/COORDINATOR.md",
    "factory/WORKER.md",
    "factory/REVIEWER.md",
    "references/factory-alignment.json",
    "references/factory-contract.md",
    "requirements-dev.txt",
    "scripts/build.py",
    "scripts/factory-alignment.py",
    "scripts/factory-job.py",
    "scripts/lib/factory_contract.py",
    "scripts/setup.py",
    "scripts/validate-brief.py",
    "scripts/verify-pi-resources.mjs",
    "skills/factory/SKILL.md",
    "skills/grilling/SKILL.md",
    "skills/setup/SKILL.md",
    "templates/pi/APPEND_SYSTEM.md",
    "tests/test_e2e_factory.py",
    "tests/test_e2e_pi_setup.py",
    "tests/test_factory_alignment.py",
    "tests/test_factory_job.py",
    "tests/test_instruction_packaging.py",
    "tests/test_setup.py",
    "tests/test_validate_brief.py",
)


def build(output: Path) -> Path:
    sources = []
    for member in MEMBERS:
        source = PACKAGE_ROOT / member
        if source.resolve() != source or not source.is_file():
            raise ValueError(f"missing or non-regular distribution resource: {member}")
        sources.append((member, source.read_bytes()))

    if output.is_symlink():
        raise ValueError("output must not be a symlink")
    output.mkdir(exist_ok=True)
    destination = output / ARCHIVE_NAME
    with tempfile.TemporaryDirectory(dir=output, prefix=".build-") as workspace:
        temporary = Path(workspace) / ARCHIVE_NAME
        with (
            temporary.open("wb") as handle,
            gzip.GzipFile(filename="", fileobj=handle, mode="wb", mtime=0) as zipped,
            tarfile.open(fileobj=zipped, mode="w") as archive,
        ):
            for member, data in sources:
                info = tarfile.TarInfo(member)
                info.mode = 0o755 if member.endswith(".py") and data.startswith(b"#!") else 0o644
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        os.replace(temporary, destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="directory with an existing parent")
    args = parser.parse_args()
    try:
        print(build(args.output))
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
