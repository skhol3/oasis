"""The GitHub Actions workflow (v0.17.0 S4): the Odoo 15 Python job runs tests that exist; every job has a
timeout. Read as text: no YAML parser is needed. v0.21.0 S2: the wording of its steps is not compared."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import importlib
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / '.github/workflows/tests.yml'


def jobs(text):
    """{job name: its lines} of the workflow's jobs: table."""
    found, name = {}, None
    for line in text.split('\n')[text.split('\n').index('jobs:') + 1:]:
        match = re.fullmatch(r'  ([A-Za-z0-9_-]+):', line)
        if match:
            name = match.group(1)
            found[name] = []
        elif name is not None:
            found[name].append(line)
    return {key: '\n'.join(lines) for key, lines in found.items()}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.jobs = jobs(WORKFLOW.read_text())

    def test_every_job_has_a_timeout(self):
        self.assertEqual(sorted(self.jobs), ['odoo15-python', 'suite'])
        for name, body in self.jobs.items():
            with self.subTest(job=name):
                self.assertRegex(body, r'(?m)^    timeout-minutes: [1-9][0-9]*$')

    def test_the_odoo15_job_runs_tests_that_exist(self):
        body = self.jobs['odoo15-python']
        names = re.findall(r'^ +(test_[a-z_0-9]+\.[A-Za-z]+Tests(?:\.test_[a-z_0-9]+)?) \\$', body, re.M)
        self.assertEqual(names, [
            'test_audit_dependencies.AuditDependenciesTests.test_python_39_and_38_give_the_same_output',
            'test_check_environment.OldPythonAuditTests',
            'test_dev_users.DevelopmentUsersTests.test_the_runner_works_with_an_odoo_15_python',
            'test_adopted_environment.LockComparisonTests.test_names_are_normalized_on_both_sides_on_python_39_and_38',
            'test_adopted_environment.LockComparisonTests.'
            'test_a_distribution_without_usable_metadata_is_left_out_on_python_39_and_38',
        ])
        for name in names:
            with self.subTest(test=name):
                module, cls, *method = name.split('.')
                case = getattr(importlib.import_module(module), cls)
                self.assertTrue(issubclass(case, unittest.TestCase))
                if method:
                    self.assertTrue(callable(getattr(case, method[0], None)), name)


if __name__ == '__main__':
    unittest.main()
