"""Keep the suite away from the user's machine configuration (AGENTS.md: tests never touch a real
configuration; v0.14.0 S2, S10).

Every test module imports this module before anything else (test_bundle checks it). On import it
points XDG_CONFIG_HOME at a fresh, empty system temp directory, whatever the inherited value was, so
the machine file `$XDG_CONFIG_HOME/oasis/config.toml` resolves to scratch and is absent in the test
process and in every subprocess that inherits its environment. A test that needs a machine file sets
its own XDG_CONFIG_HOME (and HOME when it removes XDG_CONFIG_HOME). The directory is removed when the
process exits. Python imports a module once per process, so the whole suite shares one directory,
and a single module run alone gets its own.
"""
import atexit
import os
from pathlib import Path
import shutil
import tempfile

CONFIG_HOME = Path(tempfile.mkdtemp(prefix='oasis-test-config-')).resolve()
os.environ['XDG_CONFIG_HOME'] = str(CONFIG_HOME)
atexit.register(shutil.rmtree, CONFIG_HOME, ignore_errors=True)
