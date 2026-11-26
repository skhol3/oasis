"""What differs between Odoo series, in one table; the only place tools write such options.

19.0 and 15.0 are listed, each read from its source; values for other series stay out of the
table until they are verified (see odd/tasks/location-independence.md, L6). 19.0 comes first: the
series a tool takes when it must pick one. config.py emits the Odoo options of the configured series
(ODOO_SECOND_PORT_OPTION, ODOO_DEMO_OFF_ARGS) for the shell tools.

15.0 (v0.15.0 S2) was read from the 15.0 source (commit 3a28e5b0): odoo/__init__.py:19-20
(MIN_PY_VERSION, MAX_PY_VERSION; odoo/cli/server.py:69 refuses a newer Python), odoo/tools/config.py
(--without-demo:111, --longpolling-port:136, --test-tags:165, --dev:287, --stop-after-init:293, `all`:529,
test_enable from test_tags without stop_after_init:534), odoo/tools/debugger.py:8 (the debuggers),
odoo/service/server.py:28-47 and 1340 (reload), odoo/tests/common.py:2842 (the class filter) and
odoo/addons/base/models/res_users.py:367 (groups_id). PostgreSQL: the source enforces no minimum;
12 is the documented one found (odd/tasks/v0.15.0.md L3), 14 the PostgreSQL of the user's 15.0
compose file.

Keys:
- python: lowest and highest supported Python minor version, inclusive ("3.10", "3.14").
  15.0: 3.7-3.12.
- python_default: the Python of a workspace that sets [tooling].environment instead of named
  [environments] (a named environment declares its own); within the range above. The Python of the
  official Debian package Odoo builds for the series (v0.15.0 S9), from the base image of its
  setup/package.dfdebian: 19.0 `FROM ubuntu:noble` (Python 3.12), 15.0 `FROM debian:bullseye`
  (Python 3.9).
- postgres_min: lowest supported PostgreSQL major version.
- postgres_default: the PostgreSQL major version of the compose file `oasis setup` writes (the image
  postgres:<version>); at or above postgres_min. 19.0: 17, a release with years of upstream support
  left, while 13 (the minimum) reached its end of life in November 2025. A choice within the
  supported range, not a value read from the 19.0 source (v0.14.0 L13).
- second_port_option: the option of the second (gevent/longpolling) server port.
- second_port_conf_option: the odoo.conf option of that port (a linked worktree's second port
  starts after it): gevent_port on 19.0, longpolling_port on 15.0 (config.py:136, dest).
- demo_off_args: the options that install without demo data. 19.0 loads no demo data unless
  --with-demo is given, but keeps the explicit off option the tools always passed: whether an
  odoo.conf could turn demo data back on without it is unverified, so the guard stays. 15.0 loads
  demo data unless told otherwise, and its --without-demo takes a value (config.py:111-113: an
  optparse option without an action stores the next argument; its help says "comma-separated, use
  all for all modules"): given alone it would take the next word of the command line, such as
  --stop-after-init or --test-tags, as that value. Any value turns demo data off for every module
  installed (config.py:522-523), so 15.0 passes --without-demo=all.
- demo_on_args: the options that install with demo data (install-module --with-demo,
  init-dev-database --with-demo). 15.0 has no --with-demo option and loads demo data by default:
  nothing to pass.
- test_tags_implies_stop: whether --test-tags implies --stop-after-init. The tests path
  (test-module, and verify-module through it) passes --stop-after-init in every series, so a test
  run ends in a series where it is false (15.0) too.
- test_class_filter: whether --test-tags takes `/module:Class.method` (test-module --only).
- dev_option: the option that turns on developer mode features (`<option>=<feature>,...`).
- dev_features: every feature that option takes, in the order a selector offers them: the
  closed set a dev mode choice is built from (no free text). 19.0: odoo/tools/config.py:428-437
  of the 19.0 source (commit 8a2481dfc); it has no debugger features (pdb, ipdb, wdb, pudb,
  werkzeug). 15.0: the debuggers (debugger.py:8), qweb, reload, werkzeug and xml (config.py:287-289).
- dev_all: the features the word `all` turns on (19.0: ALL_DEV_MODE, config.py:29; not replica.
  15.0: config.py:529, in that order).
- dev_reload_packages: the Python packages of which one must be importable for the `reload`
  feature (19.0: odoo/service/server.py:1663-1675; 15.0: server.py:28-47); without any, Odoo logs a
  warning and disables reload. Empty for a series without `reload`.
- user_groups_field: the res.users field of a user's groups (init-dev-database writes it).
- runtime_requirements: what the series needs at run time that the requirements.txt of its source
  does not list, as (requirement, reason) pairs; a new runtime.in that `oasis setup` writes requires
  each after the source's requirements, below a comment with its reason (v0.15.0 S9). 19.0: none.
  15.0: setuptools<81, since Odoo 15 imports pkg_resources without listing setuptools, an environment
  uv creates has none and uv pip sync removes it from one that has it (without it odoo-bin stops with
  "No module named 'pkg_resources'"; odd/tasks/v0.15.0.md L24); setuptools' deprecation warning for
  pkg_resources says to pin Setuptools<81 to keep it.
- ldap_override: (Odoo's python-ldap pin, the pin that replaces it) when that pin does not build against
  OpenLDAP 2.6, else None (v0.16.0 S3). 15.0: python-ldap==3.4.0 links libldap_r, which OpenLDAP 2.6
  removed; 3.4.4 builds against both. `oasis setup` proposes the replacement in overrides.txt when the
  source's requirements.txt has that pin and this machine has OpenLDAP 2.6 without libldap_r
  (tools/known_problems.py).

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
        'second_port_conf_option': 'gevent_port',
        'demo_off_args': ['--without-demo'],
        'demo_on_args': ['--with-demo'],
        'test_tags_implies_stop': True,
        'test_class_filter': True,
        'dev_option': '--dev',
        'dev_features': ['access', 'qweb', 'reload', 'replica', 'xml'],
        'dev_all': ['access', 'qweb', 'reload', 'xml'],
        'dev_reload_packages': ['inotify', 'watchdog'],
        'user_groups_field': 'group_ids',
        'runtime_requirements': [],
        'ldap_override': None,
    },
    '15.0': {
        'python': ('3.7', '3.12'),
        # setup/package.dfdebian of the 15.0 source: FROM debian:bullseye, whose Python is 3.9.
        'python_default': '3.9',
        'postgres_min': 12,
        'postgres_default': 14,
        'second_port_option': '--longpolling-port',
        'second_port_conf_option': 'longpolling_port',
        'demo_off_args': ['--without-demo=all'],
        'demo_on_args': [],
        'test_tags_implies_stop': False,
        'test_class_filter': True,
        'dev_option': '--dev',
        'dev_features': ['ipdb', 'pdb', 'pudb', 'wdb', 'qweb', 'reload', 'werkzeug', 'xml'],
        'dev_all': ['pdb', 'reload', 'qweb', 'werkzeug', 'xml'],
        'dev_reload_packages': ['inotify', 'watchdog'],
        'user_groups_field': 'groups_id',
        'runtime_requirements': [('setuptools<81', 'Odoo 15.0 imports pkg_resources without listing setuptools, '
                                  'which provides it: an environment uv creates has none and uv pip sync would '
                                  'remove it; setuptools advises <81 to keep pkg_resources.')],
        'ldap_override': ('python-ldap==3.4.0', 'python-ldap==3.4.4'),
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
