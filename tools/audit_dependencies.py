#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import defaultdict
from importlib.metadata import PackageNotFoundError, packages_distributions, version
from pathlib import Path

IMPORT_DISTRIBUTIONS = {
    "dateutil": "python-dateutil", "defusedxml": "defusedxml",
    "freezegun": "freezegun", "markupsafe": "MarkupSafe",
    "pytest": "pytest", "selenium": "selenium", "xlsxwriter": "XlsxWriter",
}
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+")
MODULE_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


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
                relative = path.relative_to(project_root) if path.is_relative_to(project_root) else path
                raise ValueError(f"Cannot parse {relative}: {error}") from error
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".", 1)[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module.split(".", 1)[0]]
                for name in names:
                    if name in sys.stdlib_module_names or name in local_roots:
                        continue
                    relative = path.relative_to(project_root) if path.is_relative_to(project_root) else path
                    imports[name].append(f"{relative}:{node.lineno}")
    return imports


def distribution_for_import(import_name: str) -> str | None:
    if import_name in IMPORT_DISTRIBUTIONS:
        return IMPORT_DISTRIBUTIONS[import_name]
    distributions = packages_distributions().get(import_name, [])
    return sorted(distributions)[0] if distributions else None


def installed_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
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
