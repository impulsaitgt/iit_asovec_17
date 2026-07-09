# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    residencia_id = fields.Many2one(
        comodel_name="asovec.residencia",
        string="Residencia",
        index=True,
        help="Residencia de la Asociación a la que corresponde este cargo (cobro "
             "mensual o deuda migrada). Permite distinguir cargos de residencias "
             "distintas aunque compartan el mismo cliente.",
    )
