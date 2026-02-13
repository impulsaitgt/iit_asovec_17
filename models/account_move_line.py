# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    contador_line_id = fields.Many2one(
        comodel_name="asovec.contador.lines",
        string="Lectura de contador",
        index=True,
        ondelete="set null",
        help="Lectura de contador asociada a esta línea de factura.",
    )
