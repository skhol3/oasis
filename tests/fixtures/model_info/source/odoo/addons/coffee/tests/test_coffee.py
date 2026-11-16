from odoo import fields, models


class SkippedTestExtension(models.Model):
    _inherit = 'coffee.order'

    skipped = fields.Char()
