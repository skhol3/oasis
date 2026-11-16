from odoo import api, fields, models


class CoffeeOrder(models.Model):
    _inherit = ['coffee.order', 'mail.activity.mixin']

    barista_id = fields.Many2one(comodel_name='res.users', string='Barista')
    amount = fields.Float(groups='base.group_user')

    @api.constrains('barista_id')
    def _check_barista(self):
        pass

    @api.onchange('partner_id')
    def _onchange_partner(self):
        pass

    def _compute_amount(self):
        return super()._compute_amount()


class CoffeeShop(models.Model):
    # A new model built on coffee.order is not an extension of it.
    _name = 'coffee.shop'
    _inherit = ['coffee.order']

    shop_only = fields.Char()
