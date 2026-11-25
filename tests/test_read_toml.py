import oasis_test_env  # noqa: F401  (isolates the machine file; must stay the first import)
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('oasis_config_read_toml', ROOT / 'tools' / 'config.py')
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)


class ReadTomlTests(unittest.TestCase):
    def test_a_file_that_is_not_utf8_is_invalid_toml_not_a_traceback(self):
        # v0.14.0 review (review-262785243766b1a5): setup's next steps catch only InvalidConfig.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'oasis-workspace.toml'
            path.write_bytes(b"workspace_version = 1\nname = '\xff'\n")
            with self.assertRaises(config.InvalidConfig) as caught:
                config.read_toml(path)
            self.assertEqual(str(caught.exception), f'Invalid TOML in {path}.')

    def test_a_missing_file_and_a_parse_error_stay_invalid_toml(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'oasis-workspace.toml'
            for content in (None, b'broken = [\n'):
                with self.subTest(content=content):
                    if content is not None:
                        path.write_bytes(content)
                    with self.assertRaises(config.InvalidConfig):
                        config.read_toml(path)


if __name__ == '__main__':
    unittest.main()
