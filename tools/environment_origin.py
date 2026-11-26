#!/usr/bin/env python3
"""Whether oasis created a project environment (v0.17.0 S1; internal CLI).

Usage:
  environment_origin.py mark <environment> <command>
      write the mark of an environment oasis just created with `uv venv` (<command>: what created it)
  environment_origin.py created <environment>
      exit 0 when <environment> carries the mark, 1 otherwise

oasis creates an environment only with `uv venv`, in `bootstrap --apply` and `setup --apply`, and marks it
right after with <environment>/.oasis-created. Every other environment is adopted (`setup --environment`, an
answered path, or one created by hand): oasis never writes into it, and `doctor --environment --full` reports
its drift from the locks as a WARN naming `bootstrap --apply`, which syncs it, instead of a FAIL. An
environment created before 0.17.0 has no mark: creating that file by hand makes its drift a FAIL again.
"""
from pathlib import Path
import sys

MARK = '.oasis-created'


def mark(environment: Path, command: str) -> None:
    """Mark environment, which oasis just created with uv venv through command."""
    (environment / MARK).write_text(f'created by {command} (uv venv); oasis reports its drift from the locks as '
                                    'a failure\n', encoding='utf-8')


def created(environment: Path) -> bool:
    """Whether oasis created environment (its mark exists); False for an adopted one."""
    return (environment / MARK).is_file()


def main(arguments: list) -> int:
    if len(arguments) == 3 and arguments[0] == 'mark':
        mark(Path(arguments[1]), arguments[2])
        return 0
    if len(arguments) == 2 and arguments[0] == 'created':
        return 0 if created(Path(arguments[1])) else 1
    print(f'Usage: {Path(sys.argv[0]).name} mark <environment> <command> | created <environment>', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
