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

    # OJO: NO usar "reconciled_invoice_ids.residencia_id" aquí. reconciled_invoice_ids
    # es un campo computado NO almacenado de account.payment (core): cuando el ORM
    # necesita invertir ese depends (p.ej. al escribir residencia_id en un
    # account.move) no puede resolverlo con SQL y cae a un fallback que trata TODOS
    # los account.payment de la base como candidatos a recalcular (ver
    # "Non-stored field account.payment.reconciled_invoice_ids cannot be searched" en
    # logs/odoo.log). Con miles de pagos eso hacía carísimo cualquier escritura masiva
    # de residencia_id en facturas (p.ej. "Regenerar Cargos" en proyecto_cobro_mensual.py).
    #
    # En su lugar se depende directamente de la misma cadena real (almacenada e
    # indexada) que usa el propio reconciled_invoice_ids del core
    # (_compute_stat_buttons_from_reconciliation: move_id.line_ids.matched_debit_ids /
    # matched_credit_ids, ambos One2many sobre account.partial.reconcile con inverse
    # Many2one almacenado), extendida un paso más hasta el residencia_id de la factura
    # conciliada. Todos los pasos son Many2one/One2many con columna real, así que el
    # ORM puede invertir el depends con SQL en vez de recorrer Python.
    @api.depends(
        "move_id.line_ids.matched_debit_ids.debit_move_id.move_id.residencia_id",
        "move_id.line_ids.matched_credit_ids.credit_move_id.move_id.residencia_id",
    )
    def _compute_residencia_id(self):
        for pay in self:
            residencias = pay.reconciled_invoice_ids.residencia_id
            pay.residencia_id = residencias if len(residencias) == 1 else False
