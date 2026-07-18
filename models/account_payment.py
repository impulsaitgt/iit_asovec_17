# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    residencia_id = fields.Many2one(
        comodel_name="asovec.residencia",
        string="Residencia",
        compute="_compute_residencia_id",
        store=True,
        index=True,
        help="Residencia del cargo (factura) que este pago concilia. Si el pago "
             "concilia facturas de más de una residencia, o no concilia ninguna "
             "factura ('pago sin cargo relacionado'), queda vacío.",
    )

    @api.depends("reconciled_invoice_ids.residencia_id")
    def _compute_residencia_id(self):
        for pay in self:
            residencias = pay.reconciled_invoice_ids.residencia_id
            pay.residencia_id = residencias if len(residencias) == 1 else False
