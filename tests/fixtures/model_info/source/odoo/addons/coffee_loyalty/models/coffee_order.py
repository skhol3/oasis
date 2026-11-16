from odoo import fields, models


class CoffeeOrder(models.Model):
    _inherit = 'coffee.order'

    points = fields.Integer('Points')
    state = fields.Selection(selection_add=[('loyal', 'Loyal')], ondelete={'loyal': 'set default'})

    def action_done(self):
        return super().action_done()
