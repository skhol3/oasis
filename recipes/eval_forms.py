"""The forms that are wrong on each Odoo series, read by tools/recipe_evals.py (v0.19.0 S7).

Series knowledge lives with the recipes, not in tools/ (tools name no series but odoo_versions.py). One
entry per form: the form, the file kinds it applies to, a regular expression (multi-line mode; a group
named `hit` marks the reported line when the match starts earlier, for a field inside a `<record>`), a
short reason and the source line that proves it, relative to the Odoo source tree of that series:
19.0 at commit 8a2481dfc, 15.0 at commit 3a28e5b0. Every supported series needs an entry.
"""
import re
from typing import NamedTuple


class Form(NamedTuple):
    form: str
    kinds: tuple
    pattern: re.Pattern
    reason: str
    source: str


def form(name, kinds, pattern, reason, source):
    return Form(name, tuple(kinds.split()), re.compile(pattern, re.M), reason, source)


def in_record(models, field):
    """A `<field name="<field>">` inside a `<record>` of one of models (the field is the hit)."""
    names = '|'.join(re.escape(model) for model in models.split())
    return (rf'<record\b[^>]*\bmodel=["\'](?:{names})["\'][^>]*>'
            rf'(?:(?!</record>)[\s\S])*?<field\s+name=["\'](?P<hit>{field})["\']')


def route_type(value):
    """An http route whose type is value (the type is the hit)."""
    return rf'\broute\((?:[^()]|\([^()]*\))*?(?P<hit>\btype\s*=\s*["\']{value}["\'])'


def view_mode(mode):
    """mode among the view modes of an action, in XML data or a Python dictionary."""
    return (rf'<field\s+name=["\']view_mode["\'][^>]*>[^<]*?(?P<hit>\b{mode}\b)'
            rf'|["\']view_mode["\']\s*:\s*["\'][^"\']*?\b{mode}\b')


def modifier_expression():
    """invisible, readonly or required holding more than a constant or a context expression."""
    constant = r'\s*(?:[01]|True|False|invisible|readonly|required)\s*'
    return (r'(?<![\w-])(?:invisible|readonly|required)\s*=\s*'
            rf'(?:"(?!{constant}")(?![^"]*\bcontext\b)[^"]*"|\'(?!{constant}\')(?![^\']*\bcontext\b)[^\']*\')'
            r'|<attribute\s+name=["\'](?:invisible|readonly|required)["\']\s*>'
            rf'(?!{constant}<)(?![^<]*\bcontext\b)[^<]*</attribute>')


MENUS_AND_ACTIONS = 'ir.ui.menu ir.actions.act_window ir.actions.server'

FORMS = {
    '19.0': (
        form('<tree>', 'xml', r'<tree(?=[\s/>])',
             'list views are <list>: tree is not a view type',
             'odoo/addons/base/models/ir_ui_view.py:149'),
        form('view_mode tree', 'xml py', view_mode('tree'),
             'the list view mode is list',
             'odoo/addons/base/models/ir_actions.py:318'),
        form('attrs', 'xml', r'(?<![\w-])attrs\s*=\s*["\']|<attribute\s+name=["\']attrs["\']',
             'refused since 17.0: write invisible, readonly or required as a Python expression',
             'odoo/addons/base/models/ir_ui_view.py:497'),
        form('states', 'xml', r'(?<![\w-])states\s*=\s*["\']|<attribute\s+name=["\']states["\']',
             'refused since 17.0: write invisible as a Python expression',
             'odoo/addons/base/models/ir_ui_view.py:497'),
        form('states= on a field', 'py', r'\bstates\s*=\s*\{',
             'unknown field parameter: set readonly in the view',
             'odoo/orm/fields.py:533'),
        form('_sql_constraints', 'py', r'\b_sql_constraints\s*=',
             'ignored: declare a models.Constraint attribute',
             'odoo/orm/model_classes.py:163'),
        form('name_get', 'py', r'\bdef\s+name_get\s*\(|\.name_get\s*\(',
             'no longer exists: override _compute_display_name',
             'odoo/orm/models.py:1438'),
        form('_name_search', 'py', r'\bdef\s+_name_search\s*\(',
             'no longer exists: set _rec_names_search or override _search_display_name',
             'odoo/orm/models.py:1455'),
        form('check_access_rights', 'py', r'\.check_access_rights\s*\(',
             'deprecated: check_access(operation) or has_access(operation)',
             'odoo/orm/models.py:4167'),
        form('check_access_rule', 'py', r'\.check_access_rule\s*\(',
             'deprecated: check_access(operation) or has_access(operation)',
             'odoo/orm/models.py:4181'),
        form("type='json'", 'py', route_type('json'),
             "deprecated alias: type='jsonrpc'",
             'odoo/http.py:814'),
        form('t-esc', 'xml', r'(?<![\w-])t-esc\s*=',
             'deprecated directive: t-out',
             'odoo/addons/base/models/ir_qweb.py:2491'),
        form('tour.register', 'js', r'\btour\.register\s*\(|\bfrom\s+["\']web_tour\.tour["\']',
             'tours are added to registry.category("web_tour.tours")',
             'addons/web_tour/static/src/js/tour_service.js:58'),
        form('group_operator', 'py', r'\bgroup_operator\s*=',
             'deprecated: aggregator',
             'odoo/orm/fields.py:486'),
        form('groups_id', 'py xml csv', r'\bgroups_id\b',
             'renamed group_ids on users, menus and actions',
             'odoo/addons/base/models/res_users.py:257'),
        form('users on res.groups', 'xml', in_record('res.groups', 'users'),
             'renamed user_ids',
             'odoo/addons/base/models/res_groups.py:17'),
        form('category_id on res.groups', 'xml', in_record('res.groups', 'category_id'),
             "a group's application is privilege_id",
             'odoo/addons/base/models/res_groups.py:36'),
        form('user_has_groups', 'py', r'\.user_has_groups\s*\(',
             'no longer exists: self.env.user.has_groups',
             'odoo/addons/base/models/res_users.py:1034'),
        form('SavepointCase', 'py', r'\bSavepointCase\b',
             'no longer exists: TransactionCase',
             'odoo/tests/common.py:990'),
        form('expression.AND/OR', 'py', r'\bexpression\.(?:AND|OR)\s*\(',
             'deprecated: combine Domain objects',
             'odoo/osv/expression.py:242'),
        form('self._cr/_uid/_context', 'py', r'\bself\._(?:cr|uid|context)\b',
             'deprecated: self.env.cr, self.env.uid, self.env.context',
             'odoo/orm/models.py:5931'),
        form('toggle_active override', 'py', r'\bdef\s+toggle_active\s*\(',
             'deprecated: override action_archive or action_unarchive',
             'odoo/orm/models.py:5808'),
        form('invalidate_cache', 'py', r'\.invalidate_cache\s*\(',
             'no longer exists: invalidate_model or invalidate_recordset',
             'odoo/orm/models.py:6728'),
        form('div.oe_chatter', 'xml', r'\bclass=["\']oe_chatter["\']',
             'not a chatter: write <chatter/>',
             'addons/mail/static/src/chatter/web/form_compiler.js:47'),
    ),
    '15.0': (
        form('<list>', 'xml', r'<list(?=[\s/>])',
             'list views are <tree>: list is not a view type',
             'odoo/addons/base/models/ir_ui_view.py:243'),
        form('view_mode list', 'xml py', view_mode('list'),
             'the list view mode is tree',
             'odoo/addons/base/models/ir_actions.py:238'),
        form('invisible/readonly/required expression', 'xml', modifier_expression(),
             'evaluated with only context: a condition on record values goes in attrs',
             'odoo/addons/base/models/ir_ui_view.py:100'),
        form('column_invisible', 'xml', r'(?<![\w-])column_invisible\s*=|<attribute\s+name=["\']column_invisible["\']',
             'refused by the view schema: invisible on a field of a <tree> hides the column',
             'odoo/addons/base/models/ir_ui_view.py:97'),
        form('models.Constraint', 'py', r'\bmodels\.Constraint\s*\(',
             'does not exist: declare _sql_constraints',
             'odoo/models.py:497'),
        form('models.Index', 'py', r'\bmodels\.(?:Unique)?Index\s*\(',
             'does not exist: create the index in init() with tools.create_index',
             'odoo/tools/sql.py:223'),
        form('display_name assigned', 'py', r'\.display_name\s*=(?!=)',
             'labels come from name_get: a display_name set in a compute is not what users see',
             'odoo/models.py:1845'),
        form('_rec_names_search', 'py', r'\b_rec_names_search\s*=',
             'not read: override _name_search',
             'odoo/models.py:1917'),
        form('Domain', 'py', r'\bfrom\s+odoo(?:\.fields|\.orm\.domains)?\s+import\b[^\n]*\bDomain\b',
             'does not exist: domains are lists, combined with expression.AND/OR',
             'odoo/osv/expression.py:272'),
        form('@odoo/owl', 'js', r'\bfrom\s+["\']@odoo/owl["\']',
             'Owl 1 is the global owl: const { Component } = owl',
             'addons/web/static/lib/owl/owl.js:5610'),
        form('import without /** @odoo-module **/', 'js',
             r'\A(?![\s\S]*@odoo-module)[\s\S]*?^(?P<hit>(?:import|export)\b)',
             'only a file whose first comment is /** @odoo-module **/ may import',
             'odoo/tools/js_transpiler.py:593'),
        form('web_tour.tours', 'js', r'\bcategory\(\s*["\']web_tour\.tours["\']',
             'tours are registered with tour.register from web_tour.tour',
             'addons/web_tour/static/src/js/tour_manager.js:74'),
        form('check_access', 'py', r'\.check_access\s*\(',
             'does not exist: check_access_rights and check_access_rule',
             'odoo/models.py:3559'),
        form('has_access', 'py', r'\.has_access\s*\(',
             'does not exist: check_access_rights(operation, raise_exception=False)',
             'odoo/models.py:3559'),
        form('_filtered_access', 'py', r'\._filtered_access\s*\(',
             'does not exist: _filter_access_rules',
             'odoo/models.py:3602'),
        form('self.env._', 'py', r'\benv\._\s*\(',
             'does not exist: from odoo import _',
             'odoo/tools/translate.py:550'),
        form('aggregator', 'py', r'\baggregator\s*=',
             'unknown field parameter: group_operator',
             'odoo/fields.py:285'),
        form('group_ids', 'xml', in_record('res.users ' + MENUS_AND_ACTIONS, 'group_ids'),
             'the field is groups_id',
             'odoo/addons/base/models/res_users.py:367'),
        form('group_ids', 'py',
             r'\benv\[\s*["\']res\.users["\']\s*\][^\n]*?\.(?:create|write)\(\s*\[?\s*\{[^}]*?'
             r'["\'](?P<hit>group_ids)["\']\s*:',
             'the field is groups_id',
             'odoo/addons/base/models/res_users.py:367'),
        form('user_ids on res.groups', 'xml', in_record('res.groups', 'user_ids'),
             'the field is users',
             'odoo/addons/base/models/res_users.py:201'),
        form('privilege_id on res.groups', 'xml', in_record('res.groups', 'privilege_id'),
             "does not exist: a group's application is category_id",
             'odoo/addons/base/models/res_users.py:208'),
        form('sequence on res.groups', 'xml', in_record('res.groups', 'sequence'),
             'res.groups has no sequence field',
             'odoo/addons/base/models/res_users.py:197'),
        form('has_groups', 'py', r'\.has_groups\s*\(',
             'does not exist: has_group checks one group',
             'odoo/addons/base/models/res_users.py:895'),
        form('<chatter>', 'xml', r'<chatter(?=[\s/>])',
             'not rendered: <div class="oe_chatter"> with the message fields',
             'addons/mail/static/src/widgets/form_renderer/form_renderer.js:133'),
        form("type='jsonrpc'", 'py', route_type('jsonrpc'),
             'route types are http and json',
             'odoo/http.py:323'),
        form('SQL', 'py', r'\bfrom\s+odoo\.tools(?:\.sql)?\s+import\b[^\n]*\bSQL\b|\btools\.SQL\s*\(',
             'does not exist: cr.execute(query, params)',
             'odoo/sql_db.py:303'),
        form('flush_model/invalidate_model', 'py',
             r'\.(?:flush_model|flush_recordset|invalidate_model|invalidate_recordset)\s*\(',
             'do not exist: flush() and invalidate_cache()',
             'odoo/models.py:5668'),
    ),
}
