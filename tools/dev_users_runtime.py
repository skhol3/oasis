#!/usr/bin/env python3
"""Private stdin-only credential transport; invoked by the guarded development CLI."""
import json
import logging
from pathlib import Path
import subprocess
import sys

from config import load
from odoo_addons_path import linked_addons_path


def main():
    created = False
    # Do not expose credentials through initialization/authentication exception logs.
    logging.disable(logging.CRITICAL)
    try:
        root, module, database = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
        values = load(root)
        payload = json.load(sys.stdin)
        declaration = payload['declaration']
        passwords = payload['passwords']
        with_demo = payload['with_demo']
        demo_flag = '--with-demo' if with_demo else '--without-demo'
        # The options of common.sh's odoo_config_arguments: a linked worktree that shares the
        # main checkout's odoo.conf gets its own root in addons_path.
        addons = linked_addons_path(values)
        config_args = ['-c', values['ODOO_CONFIG'], *([f'--addons-path={addons}'] if addons else [])]
        sys.path.insert(0, values['ODOO_SOURCE'])
        import odoo
        import odoo.service.common
        import odoo.service.db
        from odoo.modules.registry import Registry

        odoo.tools.config.parse_config([*config_args, '--no-http',
                                       demo_flag, '--log-level=critical'])
        # Odoo creates the DB itself: an existing name or a concurrent CREATE fails,
        # never the ensure_database behavior that might reuse another caller's DB.
        odoo.service.db.exp_create_database(
            database, with_demo, 'en_US', user_password=passwords[0],
            login=declaration['administrator_login'])
        created = True
        if not odoo.service.common.exp_authenticate(
                database, declaration['administrator_login'], passwords[0], {}):
            raise ValueError('Administrator initialization could not be verified.')
        # Optional environment modules are installed first so native demo XML can
        # reference their routes without making them mandatory addon dependencies.
        modules = declaration.get('demo_modules', []) if with_demo else []
        for install_module in dict.fromkeys([*modules, module]):
            install = subprocess.run(
                [values['PYTHON'], values['ODOO_BIN'], *config_args,
                 '-d', database, '-i', install_module, demo_flag, '--stop-after-init',
                 '--no-http', '--log-level=critical'], capture_output=True)
            if install.returncode:
                raise ValueError('Module installation failed.')
        # Another process installed the addon: reload rather than reuse base's registry.
        registry = Registry.new(database)
        with registry.cursor() as cr:
            env = odoo.api.Environment(cr, odoo.api.SUPERUSER_ID, {})
            users = env['res.users'].with_context(
                no_reset_password=True, mail_create_nosubscribe=True,
                mail_notrack=True, active_test=False)
            prepared = []
            for account, password in zip(declaration.get('users', []), passwords[1:]):
                if users.search([('login', '=', account['login'])], limit=1):
                    raise ValueError('A configured account already exists.')
                groups = [env.ref(xmlid) for xmlid in
                          dict.fromkeys(['base.group_user', *account['groups']])]
                if any(group._name != 'res.groups' for group in groups):
                    raise ValueError('A configured XML ID is not a role.')
                prepared.append({
                    'login': account['login'], 'name': account['name'],
                    'password': password, 'group_ids': [(6, 0, [g.id for g in groups])],
                    'company_id': env.company.id,
                    'company_ids': [(6, 0, [env.company.id])],
                })
            expected = []
            for account in prepared:
                expected.append((account['login'], account['password'], users.create(account).id))
            cr.commit()
        for login, password, uid in expected:
            if odoo.service.common.exp_authenticate(database, login, password, {}) != uid:
                raise ValueError('Account authentication could not be verified.')
        return 0
    except Exception:
        # The host emits a fixed message, never exception details or database contents.
        return 1 if created else 3


if __name__ == '__main__':
    sys.exit(main())
