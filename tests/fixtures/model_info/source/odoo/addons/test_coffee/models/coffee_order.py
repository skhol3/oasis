from odoo import fields, models


class CoffeeOrder(models.Model):
    # Odoo source test_* modules are skipped.
    _inherit = 'coffee.order'

    test_only = fields.Char()
