#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import csv
import email.parser
import inspect
import os
import re
import sys
import sysconfig
from collections import defaultdict
from pathlib import Path, PurePosixPath

# This helper runs with the project environment's Python, 3.7 and later (Odoo 15 supports 3.7):
# importlib.metadata exists from 3.8, packages_distributions and sys.stdlib_module_names from 3.10.
# Where they exist they are used as they are; otherwise the fallbacks below compute the same data.
try:
    from importlib import metadata
except ImportError:  # Python 3.7
    metadata = None

IMPORT_DISTRIBUTIONS = {
    "dateutil": "python-dateutil", "defusedxml": "defusedxml",
    "freezegun": "freezegun", "markupsafe": "MarkupSafe",
    "pytest": "pytest", "selenium": "selenium", "xlsxwriter": "XlsxWriter",
}
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+")
MODULE_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
DISTRIBUTION_DIR = re.compile(r"\.(dist-info|egg-info)$")
# Standard library packages that some distributions ship apart (Debian: python3-distutils, ...).
SPLIT_STDLIB = frozenset({"distutils", "ensurepip", "idlelib", "lib2to3", "tkinter", "turtledemo", "venv"})


class ScannedDistribution:
    """A *.dist-info or *.egg-info directory read without importlib.metadata (Python 3.7)."""

    def __init__(self, path: Path):
        self._path = path
        text = self.read_text("METADATA") or self.read_text("PKG-INFO") or ""
        self.metadata = email.parser.Parser().parsestr(text, headersonly=True)
        self.version = self.metadata["Version"]

    def read_text(self, name: str) -> str | None:
        try:
            return (self._path / name).read_text(encoding="utf-8")
        except OSError:
            return None

    @property
    def files(self) -> list[PurePosixPath] | None:
        """RECORD, else installed-files.txt (relative to the egg-info directory), else SOURCES.txt."""
        record = self.read_text("RECORD")
        if record:
            return [PurePosixPath(row[0]) for row in csv.reader(record.splitlines()) if row]
        installed = self.read_text("installed-files.txt")
        if installed:
            return [PurePosixPath(os.path.normpath(f"{self._path.name}/{line.strip()}"))
                    for line in installed.splitlines() if line.strip()]
        sources = self.read_text("SOURCES.txt")
        if sources:
            return [PurePosixPath(line) for line in sources.splitlines() if line.strip()]
        return None


def scan_distributions(paths: list[str]) -> list[ScannedDistribution]:
    """The distributions installed on `paths` (sys.path), first one of each name, as
    importlib.metadata finds them."""
    found: dict[str, ScannedDistribution] = {}
    for entry in paths:
        try:
            names = sorted(os.listdir(entry or "."))
        except OSError:
            continue
        for name in names:
            path = Path(entry or ".") / name
            if not DISTRIBUTION_DIR.search(name) or not path.is_dir():
                continue
            distribution = ScannedDistribution(path)
            if distribution.metadata["Name"]:
                found.setdefault(normalize_distribution(distribution.metadata["Name"]), distribution)
    return list(found.values())


_DISTRIBUTIONS = None


def installed_distributions() -> list:
    global _DISTRIBUTIONS
    if _DISTRIBUTIONS is None:
        _DISTRIBUTIONS = list(metadata.distributions()) if metadata else scan_distributions(sys.path)
    return _DISTRIBUTIONS


def top_level_name(name: PurePosixPath) -> str:
    """The importable name a distribution file provides, as importlib.metadata infers it."""
    parts = name.parts
    if len(parts) > 1:
        return parts[0]
    return inspect.getmodulename(str(name)) or str(name)


def top_level_mapping(distributions) -> dict[str, list[str]]:
    """importlib.metadata.packages_distributions (Python 3.10+) over `distributions`: top_level.txt
    when the distribution declares it, else the top-level names of its files."""
    mapping: dict[str, list[str]] = defaultdict(list)
    for distribution in distributions:
        declared = (distribution.read_text("top_level.txt") or "").split()
        names = declared or [name for name in {top_level_name(PurePosixPath(str(path)))
                                                for path in distribution.files or ()}
                             if "." not in name]
        for name in names:
            mapping[name].append(distribution.metadata["Name"])
    return dict(mapping)


def scan_stdlib_module_names() -> frozenset[str]:
    """sys.stdlib_module_names (Python 3.10+) from this interpreter's library directories: the
    built-in and frozen modules, the modules and packages of the standard library and its extension
    modules."""
    names = set(sys.builtin_module_names) | SPLIT_STDLIB
    names |= {name for name, module in list(sys.modules.items())
              if "." not in name and getattr(getattr(module, "__spec__", None), "origin", None) == "frozen"}
    paths = sysconfig.get_paths()
    directories = []
    for key in ("stdlib", "platstdlib"):
        if paths.get(key):
            directories += [paths[key], os.path.join(paths[key], "lib-dynload")]
    for directory in directories:
        try:
            entries = os.listdir(directory)
        except OSError:
            continue
        for entry in entries:
            full = os.path.join(directory, entry)
            if os.path.isdir(full):
                name = entry if os.path.isfile(os.path.join(full, "__init__.py")) else None
            else:
                name = inspect.getmodulename(entry)
            if name and name.isidentifier():
                names.add(name)
    return frozenset(names)


_STDLIB_MODULE_NAMES = None
_TOP_LEVEL = None


def stdlib_module_names() -> frozenset[str]:
    global _STDLIB_MODULE_NAMES
    if _STDLIB_MODULE_NAMES is None:
        _STDLIB_MODULE_NAMES = getattr(sys, "stdlib_module_names", None) or scan_stdlib_module_names()
    return _STDLIB_MODULE_NAMES


def packages_distributions() -> dict[str, list[str]]:
    global _TOP_LEVEL
    if _TOP_LEVEL is None:
        native = getattr(metadata, "packages_distributions", None)
        _TOP_LEVEL = native() if native else top_level_mapping(installed_distributions())
    return _TOP_LEVEL


def relative_path(path: Path, root: Path) -> Path:
    """`path` relative to `root` when inside it (Path.is_relative_to is Python 3.9+)."""
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def normalize_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement_file(path: Path, seen: set[Path] | None = None) -> set[str]:
    seen = seen or set()
    path = path.resolve()
    if path in seen:
        return set()
    seen.add(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    declared: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-r ", "--requirement ")):
            include = line.split(maxsplit=1)[1]
            declared |= parse_requirement_file(path.parent / include, seen)
            continue
        if line.startswith("-"):
            continue
        match = NAME_PATTERN.match(line)
        if match:
            declared.add(normalize_distribution(match.group(0)))
    return declared


def addon_names(roots: list[Path]) -> dict[str, Path]:
    return {
        path.name: path
        for root in roots if root.is_dir()
        for path in root.iterdir()
        if path.is_dir() and (path / "__manifest__.py").is_file()
    }


def scan_targets(module: str | None, project_root: Path, roots: list[Path]) -> list[Path]:
    addons = addon_names(roots)
    if module:
        if not MODULE_PATTERN.fullmatch(module) or module not in addons:
            raise ValueError(f"Module not found in this repository: {module}")
        return [addons[module]]
    targets = [addons[name] for name in sorted(addons)]
    project_tests = project_root / "tests"
    if project_tests.is_dir():
        targets.append(project_tests)
    return targets


def collect_imports(targets: list[Path], project_root: Path, roots: list[Path]) -> dict[str, list[str]]:
    local_roots = set(addon_names(roots)) | {"odoo", "openerp"}
    imports: dict[str, list[str]] = defaultdict(list)
    for target in targets:
        for path in target.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeDecodeError) as error:
                raise ValueError(f"Cannot parse {relative_path(path, project_root)}: {error}") from error
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".", 1)[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module.split(".", 1)[0]]
                for name in names:
                    if name in stdlib_module_names() or name in local_roots:
                        continue
                    imports[name].append(f"{relative_path(path, project_root)}:{node.lineno}")
    return imports


def distribution_for_import(import_name: str) -> str | None:
    if import_name in IMPORT_DISTRIBUTIONS:
        return IMPORT_DISTRIBUTIONS[import_name]
    distributions = packages_distributions().get(import_name, [])
    return sorted(distributions)[0] if distributions else None


def installed_version(distribution: str) -> str:
    if metadata is None:
        wanted = normalize_distribution(distribution)
        return next((found.version for found in installed_distributions()
                     if normalize_distribution(found.metadata["Name"]) == wanted), "missing")
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "missing"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit external Python imports without modifying source or the environment.",
        usage="%(prog)s [-h] [module]",
    )
    parser.add_argument("--project-root", type=Path, required=True, help=argparse.SUPPRESS)
    parser.add_argument("--requirements-dir", type=Path, required=True, help=argparse.SUPPRESS)
    parser.add_argument("--addon-root", type=Path, required=True, action="append", help=argparse.SUPPRESS)
    parser.add_argument("module", nargs="?", help="Optional repository addon to audit")
    args = parser.parse_args()
    try:
        declared = parse_requirement_file(args.requirements_dir / "dev.in")
        imports = collect_imports(scan_targets(args.module, args.project_root, args.addon_root),
                                  args.project_root, args.addon_root)
    except (FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    failures = 0
    print(f"scope={args.module or 'all'}")
    print(f"declared_distributions={len(declared)}")
    print(f"external_imports={len(imports)}")
    for import_name in sorted(imports):
        distribution = distribution_for_import(import_name)
        normalized = normalize_distribution(distribution) if distribution else ""
        status = "declared" if normalized in declared else "undeclared"
        installed = installed_version(distribution) if distribution else "unknown"
        print(f"import={import_name} distribution={distribution or 'unmapped'} "
              f"status={status} installed={installed} occurrences={len(imports[import_name])}")
        for evidence in imports[import_name]:
            print(f"  {evidence}")
        if status != "declared":
            failures += 1
    print(f"undeclared_dependencies={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
