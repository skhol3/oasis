from odoo import api, fields, models


class CoffeeOrder(models.Model):
    _name = 'coffee.order'
    _description = 'Coffee Order'
    _inherit = ['mail.thread']
    _order = 'date desc, id'

    name = fields.Char('Reference', required=True, readonly=True, default=lambda self: 'New')
    partner_id = fields.Many2one('res.partner', 'Customer', required=True, index=True)
    line_ids = fields.One2many('coffee.order.line', 'order_id', string='Lines')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft', tracking=True)
    amount = fields.Float(compute='_compute_amount', store=True)
    total = fields.Float(compute='_compute_amount')
    note = fields.Text('Internal note for the barista and the counter staff', groups='base.group_user', readonly=False)

    @api.depends('line_ids.price', 'line_ids.qty')
    def _compute_amount(self):
        for order in self:
            order.amount = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)

    def action_done(self):
        self.state = 'done'


class CoffeeOrderLine(models.Model):
    _name = 'coffee.order.line'
    _description = 'Coffee Order Line'

    order_id = fields.Many2one('coffee.order')
    price = fields.Float()
