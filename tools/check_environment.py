#!/usr/bin/env python3
"""Compare the installed distributions with a lock (run with the environment's Python, 3.8 and later).

Distribution names are normalized on both sides (PEP 503, v0.17.0 S1): lowercase, runs of `-`, `_` and `.`
become `-`. The installed names come from each distribution's metadata, not from importlib.metadata's own
name lookup, which before Python 3.10 does not find `zope.event-5.0.dist-info` for `zope-event`. A dist-info or
egg-info without usable metadata (none, no name or version, or not readable as text) is left out: a locked package
it would be is then reported missing.

Exit status: 0 when the environment matches the lock, DRIFT_EXIT (3) when it does not (missing packages or other
versions), 2 for a usage error or a lock that cannot be read; an uncaught exception exits 1, so a crash is never
taken for a drift (tools/environment_checks.sh reports only DRIFT_EXIT of an adopted environment as a WARN).
"""
from __future__ import annotations

import re
import sys
from importlib.metadata import distributions
from pathlib import Path

NAME_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)$")
DRIFT_EXIT = 3


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


def installed_versions() -> dict[str, str]:
    """{normalized name: version} of every installed distribution; the first one on sys.path wins, as
    importlib.metadata.version would find it. A distribution without usable metadata is left out: none (some
    Pythons give None, others raise TypeError reading it), no name or version, or metadata that cannot be read."""
    found: dict[str, str] = {}
    for dist in distributions():
        try:
            metadata = dist.metadata
            # get(), not [], as Distribution.version reads it: a missing key is None, without the
            # DeprecationWarning of Python 3.12 and later.
            name, version = (metadata.get('Name'), metadata.get('Version')) if metadata is not None else (None, None)
        except (TypeError, ValueError, KeyError, OSError):
            continue
        if name and version:
            found.setdefault(normalize(name), version)
    return found


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
    installed = installed_versions()
    for normalized, (name, expected) in sorted(packages.items()):
        actual = installed.get(normalized)
        if actual is None:
            missing.append(f"{name}=={expected}")
            continue
        if actual != expected:
            mismatched.append(f"{name}: expected={expected} actual={actual}")
    print(f"locked_packages={len(packages)}")
    for item in missing: print(f"missing_package={item}")
    for item in mismatched: print(f"version_mismatch={item}")
    print(f"missing_packages={len(missing)}")
    print(f"version_mismatches={len(mismatched)}")
    return DRIFT_EXIT if missing or mismatched else 0


if __name__ == "__main__":
    raise SystemExit(main())
