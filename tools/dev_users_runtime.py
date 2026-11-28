#!/usr/bin/env python3
"""Private stdin-only credential transport; invoked by the guarded development CLI.

It runs with the project environment's Python (3.7+ for Odoo 15), so it imports only the standard library
of that version: dev_users.py (the host's Python) reads the configuration and passes the values this needs
(the runtime key of the stdin payload), never config.py, which needs 3.11 (tomllib).
"""
import json
import logging
import subprocess
import sys

# The exits dev_users.py reads: 0 initialized, CREATED_THEN_FAILED the database was created and a later step
# failed, 3 nothing was created; any other (1: an uncaught error) is unknown.
CREATED_THEN_FAILED = 4


def main():
    created = False
    # Do not expose credentials through initialization/authentication exception logs.
    logging.disable(logging.CRITICAL)
    try:
        module, database = sys.argv[2], sys.argv[3]
        payload = json.load(sys.stdin)
        declaration = payload['declaration']
        passwords = payload['passwords']
        with_demo = payload['with_demo']
        # The language and the country (None: none) dev_users.py checked against the Odoo source's lists.
        lang, country = payload['lang'], payload['country']
        # Decided by dev_users.py (runtime_values): the demo options and users' groups field of the series,
        # and common.sh's odoo_config_arguments.
        runtime = payload['runtime']
        demo_flags = runtime['demo_flags']
        groups_field = runtime['groups_field']
        config_args = runtime['config_args']
        sys.path.insert(0, runtime['odoo_source'])
        import odoo
        import odoo.service.common
        import odoo.service.db
        from odoo.modules.registry import Registry

        odoo.tools.config.parse_config([*config_args, '--no-http',
                                       *demo_flags, '--log-level=critical'])
        # Odoo creates the DB itself, as its database manager form does (every supported series takes the same
        # arguments): an existing name or a concurrent CREATE fails, never reusing another caller's DB.
        odoo.service.db.exp_create_database(
            database, with_demo, lang, user_password=passwords[0],
            login=declaration['administrator_login'], country_code=country)
        created = True
        if not odoo.service.common.exp_authenticate(
                database, declaration['administrator_login'], passwords[0], {}):
            raise ValueError('Administrator initialization could not be verified.')
        # Optional environment modules are installed first so native demo XML can
        # reference their routes without making them mandatory addon dependencies.
        modules = declaration.get('demo_modules', []) if with_demo else []
        for install_module in dict.fromkeys([*modules, module]):
            install = subprocess.run(
                [runtime['python'], runtime['odoo_bin'], *config_args,
                 '-d', database, '-i', install_module, *demo_flags, '--stop-after-init',
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
                    'password': password, groups_field: [(6, 0, [g.id for g in groups])],
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
        # The host emits a fixed message, never exception details or database contents. CREATED_THEN_FAILED, not
        # 1: an interpreter error the runner does not catch also exits 1, and says nothing of the database.
        return CREATED_THEN_FAILED if created else 3


if __name__ == '__main__':
    sys.exit(main())
