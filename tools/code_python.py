#!/usr/bin/env python3
"""Whether a Python can load the checkout's code (v0.20.0 S3: an environment's Python 3.8 adopted for a
checkout whose code uses `match`).

check(python, root, minor, environment=None, timeout=None)
    Runs python, the environment's own interpreter, once: `python -I -B code_python.py compile`, with the
    checkout's .py files (python_files) on stdin, NUL-separated. That interpreter compiles the bytes of each
    one with compile(source, path, 'exec') (its coding cookie applies; nothing is executed and no .pyc is
    written) and prints one JSON object: the number of files and their first ERROR_LIMIT compile errors. Then
    oasis' own Python (the one running this function) compiles each failing file too: a file it rejects as well
    is a syntax error in the code (`syntax_error`), not a limit of the environment's Python; the first file it
    accepts is `cannot_load`, with the lowest Python the code needs (lowest_python, best-effort). The timeout
    scales with the number of files (timeout_for); a timeout or an answer that is not that object is reported,
    never taken for a result.
parse_check(root, python)
    The same question without an interpreter, for a Python setup plans or reads from a pyvenv.cfg: the code
    parsed with the grammar of that Python (ast feature_version), best-effort.

Each returns a dict: {'status': 'ok', 'files': n}; {'status': 'cannot_load', 'files', 'path', 'line',
'message', 'needs': '3.<minor>' or None}; {'status': 'syntax_error', 'files', 'path', 'line', 'message'};
{'status': 'timeout', 'files', 'seconds'}; {'status': 'unchecked'} (the interpreter did not run or did not
answer). ast feature_version is best-effort: it rejects match, except* and PEP 695 for an older Python but
accepts parenthesized context managers, PEP 758 and f-strings that Python could not read, so `needs` and
parse_check can miss a newer feature; check, with the environment's own interpreter, cannot.

Python 3.7 compatible: the `compile` mode runs with the environment's Python, as old as Odoo 15's.
"""
from __future__ import annotations

import json
import math
import os
import sys

# Directories never searched for code: git's, JavaScript packages, bytecode caches; and any directory that holds a
# pyvenv.cfg (a Python environment: the configured one when it is inside the checkout, or another).
SKIPPED = frozenset(('.git', 'node_modules', '__pycache__'))
TIMEOUT_BASE_SECONDS = 20
TIMEOUT_SECONDS_PER_FILE = 0.05
ERROR_LIMIT = 50


def python_files(root, environment=None):
    """Every regular .py file below root (absolute paths), files of a directory first, then its subdirectories,
    each in name order; SKIPPED directories, environments (environment, and any directory holding a pyvenv.cfg)
    and symbolic links are left out."""
    root = os.path.abspath(str(root))
    environment = os.path.realpath(str(environment)) if environment else None
    found = []
    for directory, subdirectories, names in os.walk(root):
        kept = []
        for name in sorted(subdirectories):
            path = os.path.join(directory, name)
            if (name in SKIPPED or os.path.islink(path) or os.path.isfile(os.path.join(path, 'pyvenv.cfg'))
                    or os.path.realpath(path) == environment):
                continue
            kept.append(name)
        subdirectories[:] = kept
        for name in sorted(names):
            path = os.path.join(directory, name)
            if name.endswith('.py') and not os.path.islink(path) and os.path.isfile(path):
                found.append(path)
    return found


def read(path):
    try:
        with open(path, 'rb') as handle:
            return handle.read()
    except OSError:
        return None


def compile_error(source, path, minor=None):
    """(line, message) of the error compiling source, None when it compiles; with minor, only parsed with the
    grammar of Python 3.<minor> (ast feature_version)."""
    import warnings
    try:
        # Code that only warns (an invalid escape, `is` with a literal) compiles: its SyntaxWarning stays
        # silent, so oasis' output never gains a line per such file.
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            if minor is None:
                compile(source, path, 'exec', dont_inherit=True)
            else:
                import ast
                ast.parse(source, path, feature_version=(3, minor))
    except SyntaxError as exc:
        return exc.lineno, exc.msg
    except (ValueError, RecursionError, MemoryError) as exc:
        # A null byte before Python 3.12, a nesting or a size the compiler cannot take.
        return None, str(exc) or type(exc).__name__
    return None


def compile_files(paths):
    """The compile errors of paths, at most ERROR_LIMIT, as {'path', 'line', 'message'}; unreadable files are
    left out."""
    errors = []
    for path in paths:
        source = read(path)
        if source is None:
            continue
        error = compile_error(source, path)
        if error is not None:
            errors.append({'path': path, 'line': error[0], 'message': error[1]})
            if len(errors) >= ERROR_LIMIT:
                break
    return errors


def timeout_for(count):
    """Seconds the environment's Python gets to compile count files."""
    return TIMEOUT_BASE_SECONDS + math.ceil(count * TIMEOUT_SECONDS_PER_FILE)


def lowest_python(paths, above):
    """The lowest Python "3.<minor>" over above whose grammar parses every file oasis' own Python compiles
    (ast feature_version, best-effort), or None when no Python up to oasis' own is over above."""
    host = sys.version_info[1]
    needed = above + 1
    if needed > host:
        return None
    for path in paths:
        if needed == host:
            break
        source = read(path)
        if source is None or compile_error(source, path) is not None:
            continue
        while needed < host and compile_error(source, path, needed) is not None:
            needed += 1
    return '3.%d' % needed


def classified(paths, errors, minor):
    """The result for the errors the Python 3.<minor> to check gave: the first one oasis' own Python does not give
    is cannot_load; else the first one is a syntax error in the code."""
    genuine = None
    for error in errors:
        source = read(error['path'])
        if source is not None and compile_error(source, error['path']) is not None:
            genuine = genuine or error
            continue
        return dict(status='cannot_load', files=len(paths), path=error['path'], line=error['line'],
                    message=error['message'], needs=lowest_python(paths, minor))
    if genuine is not None:
        return dict(status='syntax_error', files=len(paths), path=genuine['path'], line=genuine['line'],
                    message=genuine['message'])
    return {'status': 'ok', 'files': len(paths)}


def answer(output, paths):
    """The errors of the JSON object compile printed, None when output is not that object for paths."""
    try:
        report = json.loads(output.decode('utf-8'))
    except (UnicodeError, ValueError):
        return None
    if not isinstance(report, dict) or report.get('files') != len(paths) or not isinstance(report.get('errors'), list):
        return None
    sent = set(paths)
    for error in report['errors']:
        if not (isinstance(error, dict) and error.get('path') in sent and isinstance(error.get('message'), str)
                and (error.get('line') is None or type(error.get('line')) is int)):
            return None
    return report['errors']


def check(python, root, minor, environment=None, timeout=None):
    """Whether python (the environment's interpreter, Python 3.<minor>) compiles the code of root (module
    docstring); timeout in seconds, by default timeout_for the number of files."""
    import subprocess
    paths = python_files(root, environment)
    if not paths:
        return {'status': 'ok', 'files': 0}
    seconds = timeout_for(len(paths)) if timeout is None else timeout
    try:
        result = subprocess.run([str(python), '-I', '-B', os.path.abspath(__file__), 'compile'],
                                input=b'\0'.join(os.fsencode(path) for path in paths), stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=seconds)
    except subprocess.TimeoutExpired:
        return {'status': 'timeout', 'files': len(paths), 'seconds': seconds}
    except (OSError, subprocess.SubprocessError):
        return {'status': 'unchecked'}
    errors = answer(result.stdout, paths) if result.returncode == 0 else None
    if errors is None:
        return {'status': 'unchecked'}
    return classified(paths, errors, minor)


def parse_check(root, python, environment=None):
    """Whether Python python ("3.<minor>") can parse the code of root, best-effort (module docstring): a file oasis'
    own Python does not compile is a syntax error in the code, reported only when no other file fails."""
    minor = int(python.split('.')[1])
    paths = python_files(root, environment)
    errors = []
    for path in paths:
        source = read(path)
        if source is None:
            continue
        error = compile_error(source, path) or compile_error(source, path, minor)
        if error is not None:
            errors.append({'path': path, 'line': error[0], 'message': error[1]})
            if len(errors) >= ERROR_LIMIT:
                break
    return classified(paths, errors, minor)


def main(arguments):
    if arguments != ['compile']:
        sys.stderr.write('Usage: code_python.py compile  (the paths on stdin, NUL-separated)\n')
        return 2
    paths = [os.fsdecode(item) for item in sys.stdin.buffer.read().split(b'\0') if item]
    sys.stdout.write(json.dumps({'files': len(paths), 'errors': compile_files(paths)}) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
