"""What differs between Odoo series, in one table; the only place tools write such options.

Only 19.0 is listed. Values for other series stay out of the table until they are verified
(see odd/tasks/location-independence.md, L6). config.py emits the Odoo options of the
configured series (ODOO_SECOND_PORT_OPTION, ODOO_DEMO_OFF_ARGS) for the shell tools.

Keys:
- python: lowest and highest supported Python minor version, inclusive ("3.10", "3.14").
- postgres_min: lowest supported PostgreSQL major version.
- second_port_option: the option of the second (gevent/longpolling) server port.
- demo_off_args: the options that install without demo data. 19.0 loads no demo data unless
  --with-demo is given, but keeps the explicit off option the tools always passed: whether an
  odoo.conf could turn demo data back on without it is unverified, so the guard stays.
- test_tags_implies_stop: whether --test-tags implies --stop-after-init.
"""
import copy
import json
import re

CAPABILITIES = {
    '19.0': {
        'python': ('3.10', '3.14'),
        'postgres_min': 13,
        'second_port_option': '--gevent-port',
        'demo_off_args': ['--without-demo'],
        'test_tags_implies_stop': True,
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
