from odoo import api, fields, models


class CoffeeSubscription(models.Model):
    _name = 'coffee.subscription'
    _description = 'Coffee subscription'
    _inherit = ['mail.thread']

    name = fields.Char(required=True)
    partner_id = fields.Many2one('res.partner')
    line_ids = fields.One2many('coffee.subscription.line', 'subscription_id')
    state = fields.Selection([('draft', 'Draft'), ('active', 'Active')], default='draft')

    def action_renew(self):
        return True


class CoffeeSubscriptionLine(models.Model):
    _name = 'coffee.subscription.line'

    subscription_id = fields.Many2one('coffee.subscription')
    quantity = fields.Integer()


class CoffeePlannerMixin(models.AbstractModel):
    _name = 'coffee.planner.mixin'
    _description = 'Planner mixin'
