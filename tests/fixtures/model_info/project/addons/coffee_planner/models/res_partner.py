from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    subscription_count = fields.Integer()
