"""Load a packaged helper of tools/ from its own file.

The tools run with python3 -I, which keeps the tools directory off sys.path, and a helper may share
its name with a built-in module (gc), so a tool never imports a sibling: it loads it by path, and so
never imports project Python code either. A tool loads this file the same way, in two lines:

    _spec = importlib.util.spec_from_file_location('oasis_siblings', Path(__file__).with_name('siblings.py'))
    _spec.loader.exec_module(siblings := importlib.util.module_from_spec(_spec))

Each call loads a new module, named as the caller asks (the names the tools used before stay).
"""
import importlib.util
from pathlib import Path


def load(name: str, module_name: str):
    """tools/<name>.py, next to this file, as a new module called module_name."""
    spec = importlib.util.spec_from_file_location(module_name, Path(__file__).with_name(f'{name}.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def loader(prefix: str):
    """load() for one tool: its helper <name> is loaded as the module <prefix><name>."""
    return lambda name: load(name, prefix + name)
