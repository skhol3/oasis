#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

NAME_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)$")


class LockfileError(ValueError):
    pass


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_packages(path: Path) -> dict[str, tuple[str, str]]:
    packages: dict[str, tuple[str, str]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = NAME_PATTERN.fullmatch(stripped)
        if not match:
            raise LockfileError(f"Malformed or unpinned lock entry at {path}:{line_number}: {stripped}")
        name, expected = match.groups()
        normalized = normalize(name)
        existing = packages.get(normalized)
        if existing and existing[1] != expected:
            raise LockfileError(f"Conflicting lock entries for {name}: {existing[1]} and {expected}")
        packages[normalized] = (name, expected)
    if not packages:
        raise LockfileError(f"Lockfile contains no pinned packages: {path}")
    return packages


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} <lockfile>", file=sys.stderr)
        return 2
    lockfile = Path(sys.argv[1])
    if not lockfile.is_file():
        print(f"ERROR: Lockfile not found: {lockfile}", file=sys.stderr)
        return 2
    missing: list[str] = []
    mismatched: list[str] = []
    try:
        packages = locked_packages(lockfile)
    except LockfileError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    for _normalized, (name, expected) in sorted(packages.items()):
        try:
            actual = version(name)
        except PackageNotFoundError:
            missing.append(f"{name}=={expected}")
            continue
        if actual != expected:
            mismatched.append(f"{name}: expected={expected} actual={actual}")
    print(f"locked_packages={len(packages)}")
    for item in missing: print(f"missing_package={item}")
    for item in mismatched: print(f"version_mismatch={item}")
    print(f"missing_packages={len(missing)}")
    print(f"version_mismatches={len(mismatched)}")
    return 1 if missing or mismatched else 0


if __name__ == "__main__":
    raise SystemExit(main())
