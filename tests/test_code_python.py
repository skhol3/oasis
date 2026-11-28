"""tools/code_python.py (v0.20.0 S3): can the environment's Python load the checkout's code?

The environment's own interpreter compiles every .py file of the checkout once (check); oasis' own Python
tells a genuine syntax error from a limit of that interpreter and gives the lowest Python the code needs,
best-effort (ast feature_version). An interpreter of another version is simulated by fake_interpreter: the
host Python whose compile first parses the files of one directory with the grammar of Python 3.<minor>. The
suite uses no other real interpreter. Every file lives in a fresh system temp directory.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import ast
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'tools' / 'code_python.py'
# Run by fake_interpreter as `<host> -I -B hook.py <minor> <scope> -I -B <code_python.py> compile`: compile parses
# each file below scope as Python 3.<minor> first (a SyntaxError there is that Python's), then runs the helper.
HOOK = '''import ast, builtins, runpy, sys
minor, scope = int(sys.argv[1]), sys.argv[2]
real = builtins.compile
def compile(source, filename, mode, *args, **kwargs):
    if str(filename).startswith(scope):
        real(source, filename, mode, ast.PyCF_ONLY_AST, _feature_version=minor)
    return real(source, filename, mode, *args, **kwargs)
builtins.compile = compile
sys.argv = sys.argv[5:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
MATCH = 'def kind(value):\n    match value:\n        case 1:\n            return "one"\n    return "other"\n'


def load_tool(name='code_python'):
    """A tool module loaded from its file, as the tools load their siblings."""
    spec = importlib.util.spec_from_file_location(f'oasis_test_{name}', ROOT / 'tools' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_interpreter(path: Path, minor: int, scope: Path) -> Path:
    """An environment Python 3.<minor> for the files below scope: the host Python with that grammar."""
    hook = path.with_name(path.name + '-hook.py')
    hook.write_text(HOOK)
    path.write_text(f'#!/bin/sh\nexec {sys.executable!r} -I -B {str(hook)!r} {minor} {str(scope)!r} "$@"\n')
    path.chmod(0o755)
    return path


def feature_error(source: str, path: Path, minor: int) -> SyntaxError:
    """The SyntaxError Python 3.<minor>'s grammar gives source (ast feature_version), as the fake raises it."""
    try:
        compile(source.encode(), str(path), 'exec', ast.PyCF_ONLY_AST, _feature_version=minor)
    except SyntaxError as exc:
        return exc
    raise AssertionError(f'{path} parses as Python 3.{minor}')


def host_error(source: str, path: Path) -> SyntaxError:
    try:
        compile(source.encode(), str(path), 'exec', dont_inherit=True)
    except SyntaxError as exc:
        return exc
    raise AssertionError(f'{path} compiles')


class CodePythonTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-code-python-')).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.root = self.scratch / 'checkout'
        self.root.mkdir()
        self.helper = load_tool()

    def write(self, name, text, data=None):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if data is None:
            path.write_text(text)
        else:
            path.write_bytes(data)
        return path

    def tree(self):
        return {str(path): path.read_bytes() if path.is_file() else None for path in sorted(self.scratch.rglob('*'))}

    def test_a_clean_tree_passes_and_skips_git_node_modules_pycache_and_environments(self):
        self.write('shop/__manifest__.py', "{'name': 'Shop'}\n")
        self.write('shop/models/sale.py', MATCH)
        # A coding cookie applies: the bytes are compiled, not a decoded text.
        self.write('shop/legacy.py', None, '# -*- coding: latin-1 -*-\nNAME = "caf\xe9"\n'.encode('latin-1'))
        broken = 'def broken(:\n'
        for skipped in ('.git/hooks/x.py', 'node_modules/pkg/x.py', 'shop/__pycache__/x.py', '.venv/lib/x.py',
                        'env/lib/x.py'):
            self.write(skipped, broken)
        self.write('.venv/pyvenv.cfg', 'home = /usr/bin\n')
        environment = self.root / 'env'
        before = self.tree()
        result = self.helper.check(sys.executable, self.root, sys.version_info[1], environment=environment)
        self.assertEqual(result, {'status': 'ok', 'files': 3})
        # Read-only: no .pyc, no file changed.
        self.assertEqual(self.tree(), before)
        self.assertEqual([str(path) for path in self.helper.python_files(self.root, environment)],
                         [str(self.root / 'shop' / name) for name in ('__manifest__.py', 'legacy.py', 'models/sale.py')])

    def test_no_python_file_passes_without_running_the_interpreter(self):
        self.assertEqual(self.helper.check(str(self.scratch / 'missing'), self.root, 8), {'status': 'ok', 'files': 0})

    def test_an_older_python_that_cannot_load_match_names_the_file_and_the_lowest_python(self):
        python = fake_interpreter(self.scratch / 'python3.8', 8, self.root)
        self.write('a_module/__init__.py', 'from . import models\n')
        sale = self.write('a_module/models.py', MATCH)
        self.write('b_module/models.py', MATCH)
        error = feature_error(MATCH, sale, 8)
        result = self.helper.check(str(python), self.root, 8)
        self.assertEqual(result, {'status': 'cannot_load', 'files': 3, 'path': str(sale), 'line': error.lineno,
                                  'message': error.msg, 'needs': '3.10'})
        # The same code with Python 3.10's grammar loads.
        self.assertEqual(self.helper.check(str(fake_interpreter(self.scratch / 'python3.10', 10, self.root)),
                                           self.root, 10), {'status': 'ok', 'files': 3})

    def test_a_genuine_syntax_error_is_told_apart_from_the_environment(self):
        python = fake_interpreter(self.scratch / 'python3.8', 8, self.root)
        broken = self.write('a_module/broken.py', 'def broken(:\n    pass\n')
        error = host_error('def broken(:\n    pass\n', broken)
        self.assertEqual(self.helper.check(str(python), self.root, 8),
                         {'status': 'syntax_error', 'files': 1, 'path': str(broken), 'line': error.lineno,
                          'message': error.msg})
        # A file the environment's Python cannot load comes first, even after a genuine syntax error.
        sale = self.write('b_module/models.py', MATCH)
        error = feature_error(MATCH, sale, 8)
        self.assertEqual(self.helper.check(str(python), self.root, 8),
                         {'status': 'cannot_load', 'files': 2, 'path': str(sale), 'line': error.lineno,
                          'message': error.msg, 'needs': '3.10'})

    def test_the_timeout_scales_with_the_files_and_a_slow_interpreter_is_reported(self):
        self.assertEqual([self.helper.timeout_for(count) for count in (1, 100, 1000)], [21, 25, 70])
        slow = self.scratch / 'slow-python'
        slow.write_text('#!/bin/sh\nexec sleep 30\n')
        slow.chmod(0o755)
        self.write('a.py', 'x = 1\n')
        self.assertEqual(self.helper.check(str(slow), self.root, 12, timeout=0.5),
                         {'status': 'timeout', 'files': 1, 'seconds': 0.5})

    def test_an_interpreter_that_does_not_run_or_answers_something_else_is_unchecked(self):
        self.write('a.py', 'x = 1\n')
        other = self.scratch / 'other-python'
        for text in ('#!/bin/sh\nexit 0\n', '#!/bin/sh\necho 3.12\n', '#!/bin/sh\necho \'{"files": 1}\'\n',
                     '#!/bin/sh\necho \'{"files": 1, "errors": [{"path": "/elsewhere.py", "line": 1, '
                     '"message": "x"}]}\'\n', '#!/bin/sh\necho \'{"files": 1, "errors": []}\'\nexit 3\n'):
            with self.subTest(text=text):
                other.write_text(text)
                other.chmod(0o755)
                self.assertEqual(self.helper.check(str(other), self.root, 12), {'status': 'unchecked'})
        self.assertEqual(self.helper.check(str(self.scratch / 'missing'), self.root, 12), {'status': 'unchecked'})

    def test_a_planned_python_is_checked_best_effort_by_its_grammar(self):
        # setup plans a new environment, or adopts one it does not run: the code parsed with ast feature_version.
        self.write('a.py', 'x = 1\n')
        self.assertEqual(self.helper.parse_check(self.root, '3.8'), {'status': 'ok', 'files': 1})
        sale = self.write('b.py', MATCH)
        error = feature_error(MATCH, sale, 8)
        self.assertEqual(self.helper.parse_check(self.root, '3.8'),
                         {'status': 'cannot_load', 'files': 2, 'path': str(sale), 'line': error.lineno,
                          'message': error.msg, 'needs': '3.10'})
        self.assertEqual(self.helper.parse_check(self.root, '3.10'), {'status': 'ok', 'files': 2})
        sale.unlink()
        broken = self.write('c.py', 'def broken(:\n')
        error = host_error('def broken(:\n', broken)
        self.assertEqual(self.helper.parse_check(self.root, '3.8'),
                         {'status': 'syntax_error', 'files': 2, 'path': str(broken), 'line': error.lineno,
                          'message': error.msg})

    def test_code_that_only_warns_adds_nothing_to_stderr(self):
        # Review review-d12f1db671db3666: an invalid escape (\d in a plain string) or `is` with a literal only
        # warns; compiling it in oasis' own process must print nothing, in setup's check and in doctor's hint.
        import contextlib
        import io
        import warnings
        self.write('a.py', "import re\nPATTERN = re.compile('\\d+')\nSAME = 1 is 1\n")
        stderr = io.StringIO()
        with warnings.catch_warnings():
            warnings.simplefilter('default')
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(self.helper.parse_check(self.root, '3.12'), {'status': 'ok', 'files': 1})
                self.assertIsNone(self.helper.compile_error(Path(self.root / 'a.py').read_bytes(), 'a.py'))
                self.helper.lowest_python([self.root / 'a.py'], 7)
        self.assertEqual(stderr.getvalue(), '')

    def test_the_helper_parses_as_python_3_7_since_the_environment_runs_it(self):
        # Best-effort (ast feature_version), as for the code: Odoo 15.0 supports Python 3.7.
        ast.parse(HELPER.read_text(encoding='utf-8'), str(HELPER), feature_version=(3, 7))

    def test_compile_mode_reads_nul_separated_paths_and_prints_one_json_object(self):
        import json
        import subprocess
        good = self.write('a b.py', 'x = 1\n')
        bad = self.write('c.py', 'def broken(:\n')
        result = subprocess.run([sys.executable, '-I', '-B', str(HELPER), 'compile'], capture_output=True,
                                input=f'{good}\0{bad}\0'.encode())
        error = host_error('def broken(:\n', bad)
        self.assertEqual((result.returncode, result.stderr), (0, b''))
        self.assertEqual(json.loads(result.stdout), {'files': 2, 'errors': [
            {'path': str(bad), 'line': error.lineno, 'message': error.msg}]})
        self.assertFalse((self.root / '__pycache__').exists())


if __name__ == '__main__':
    unittest.main()
