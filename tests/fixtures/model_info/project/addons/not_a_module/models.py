from odoo import fields, models


class NotAModule(models.Model):
    # No __manifest__.py next to this file: never scanned.
    _inherit = 'coffee.order'

    ignored = fields.Char()
