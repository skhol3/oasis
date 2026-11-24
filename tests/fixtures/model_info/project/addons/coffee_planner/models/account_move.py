from odoo import fields, models


class AccountMove(models.Model):
    _inherit = ['account.move', 'mail.activity.mixin']

    subscription_id = fields.Many2one('coffee.subscription')
    ref = fields.Char(tracking=True)
