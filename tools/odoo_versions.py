"""What differs between Odoo series, in one table; the only place tools write such options.

Only 19.0 is listed. Values for other series stay out of the table until they are verified
(see odd/tasks/location-independence.md, L6). config.py emits the Odoo options of the
configured series (ODOO_SECOND_PORT_OPTION, ODOO_DEMO_OFF_ARGS) for the shell tools.

Keys:
- python: lowest and highest supported Python minor version, inclusive ("3.10", "3.14").
- python_default: the Python of a workspace that sets [tooling].environment instead of named
  [environments] (a named environment declares its own); within the range above.
- postgres_min: lowest supported PostgreSQL major version.
- postgres_default: the PostgreSQL major version of the compose file `oasis setup` writes (the image
  postgres:<version>); at or above postgres_min. 19.0: 17, a release with years of upstream support
  left, while 13 (the minimum) reached its end of life in November 2025. A choice within the
  supported range, not a value read from the 19.0 source (v0.14.0 L13).
- second_port_option: the option of the second (gevent/longpolling) server port.
- demo_off_args: the options that install without demo data. 19.0 loads no demo data unless
  --with-demo is given, but keeps the explicit off option the tools always passed: whether an
  odoo.conf could turn demo data back on without it is unverified, so the guard stays.
- test_tags_implies_stop: whether --test-tags implies --stop-after-init.
- test_class_filter: whether --test-tags takes `/module:Class.method` (test-module --only).
- dev_option: the option that turns on developer mode features (`<option>=<feature>,...`).
- dev_features: every feature that option takes, in the order a selector offers them: the
  closed set a dev mode choice is built from (no free text). 19.0: odoo/tools/config.py:428-437
  of the 19.0 source (commit 8a2481dfc); it has no debugger features (pdb, ipdb, wdb, pudb,
  werkzeug), which older series may have had (unverified: read their source when adding one).
- dev_all: the features the word `all` turns on (19.0: ALL_DEV_MODE, config.py:29; not replica).
- dev_reload_packages: the Python packages of which one must be importable for the `reload`
  feature (19.0: odoo/service/server.py:1663-1675); without any, Odoo logs a warning and
  disables reload. Empty for a series without `reload`.

Shell tools read one value with `python3 -I -B odoo_versions.py <version> <key>`: a boolean
prints true or false, a list its items quoted for the shell, anything else its text. An
unsupported series or an unknown key exits 2.
"""
import copy
import json
import re
import shlex
import sys

CAPABILITIES = {
    '19.0': {
        'python': ('3.10', '3.14'),
        'python_default': '3.12',
        'postgres_min': 13,
        'postgres_default': 17,
        'second_port_option': '--gevent-port',
        'demo_off_args': ['--without-demo'],
        'test_tags_implies_stop': True,
        'test_class_filter': True,
        'dev_option': '--dev',
        'dev_features': ['access', 'qweb', 'reload', 'replica', 'xml'],
        'dev_all': ['access', 'qweb', 'reload', 'xml'],
        'dev_reload_packages': ['inotify', 'watchdog'],
    },
}

PYTHON = re.compile(r'3\.(?:0|[1-9][0-9]?)')


class UnsupportedVersion(ValueError):
    """An Odoo series that is not in CAPABILITIES."""


def supported() -> list[str]:
    return list(CAPABILITIES)


def capability(version, key: str):
    """The value of key for the Odoo series version (a copy: callers cannot change the table).

    An unknown series raises UnsupportedVersion; an unknown key is a programming error (KeyError).
    """
    if not isinstance(version, str) or version not in CAPABILITIES:
        raise UnsupportedVersion(f'Unsupported Odoo version {json.dumps(version)}; '
                                 f'supported: {", ".join(CAPABILITIES)}.')
    return copy.deepcopy(CAPABILITIES[version][key])


def python_supported(version, python) -> bool:
    """Whether python ("3.<minor>") lies within the supported range of the Odoo series."""
    if not isinstance(python, str) or not PYTHON.fullmatch(python):
        return False
    low, high = (tuple(int(part) for part in bound.split('.'))
                 for bound in capability(version, 'python'))
    return low <= tuple(int(part) for part in python.split('.')) <= high


def main(arguments: list[str]) -> int:
    if len(arguments) != 2:
        print('Usage: odoo_versions.py <version> <key>', file=sys.stderr)
        return 2
    version, key = arguments
    try:
        value = capability(version, key)
    except UnsupportedVersion as exc:
        print(exc, file=sys.stderr)
        return 2
    except KeyError:
        print(f'Unknown capability {json.dumps(key)}.', file=sys.stderr)
        return 2
    if isinstance(value, bool):
        print('true' if value else 'false')
    elif isinstance(value, (list, tuple)):
        print(shlex.join(str(item) for item in value))
    else:
        print(value)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
