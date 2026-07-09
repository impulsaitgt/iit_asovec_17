# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    # Información complementaria del archivo CSV de "Carga de Pagos del Banco"
    # (columnas desde FECHA hasta PAGO CON TC), grabada tal cual como texto para
    # dejar trazabilidad del pago bancario que originó este pago, sin depender del
    # wizard (transitorio, se purga con el tiempo).
    aso_pago_banco_correlativo = fields.Char(string="Correlativo (CSV Banco)")
    aso_pago_banco_codigo = fields.Char(string="Código Residencia (CSV Banco)")
    aso_pago_banco_fecha = fields.Char(string="Fecha (CSV Banco)")
    aso_pago_banco_agencia = fields.Char(string="Agencia (CSV Banco)")
    aso_pago_banco_efectivo = fields.Char(string="Efectivo (CSV Banco)")
    aso_pago_banco_cheque_bi = fields.Char(string="Cheque BI (CSV Banco)")
    aso_pago_banco_cheque_ob = fields.Char(string="Cheque OB (CSV Banco)")
    aso_pago_banco_cheque_be = fields.Char(string="Cheque BE (CSV Banco)")
    aso_pago_banco_no_chq_ob = fields.Char(string="No. Cheque OB (CSV Banco)")
    aso_pago_banco_no_boleta = fields.Char(string="No. Boleta (CSV Banco)")
    aso_pago_banco_monto_total = fields.Char(string="Monto Total (CSV Banco)")
    aso_pago_banco_pago_con_tc = fields.Char(string="Pago con TC (CSV Banco)")
