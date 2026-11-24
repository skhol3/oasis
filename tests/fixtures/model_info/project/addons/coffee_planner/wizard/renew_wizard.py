from odoo import fields, models


class CoffeeSubscriptionRenew(models.TransientModel):
    _name = 'coffee.subscription.renew'
    _description = 'Renew subscriptions'

    months = fields.Integer(default=1)
