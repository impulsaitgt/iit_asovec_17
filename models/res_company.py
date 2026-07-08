# -*- coding: utf-8 -*-
from odoo import models, fields
from .contador import MONTH_SELECTION


class ResCompany(models.Model):
    _inherit = 'res.company'

    aso_calculos_mes = fields.Selection(
        MONTH_SELECTION, string="Cálculos a partir de (Mes)",
        help="Junto con 'Cálculos a partir de (Año)', define desde qué período "
             "(mes/año) se generan cargos automáticamente al guardar una lectura. Las "
             "lecturas de períodos anteriores a este mes/año se guardan normalmente, "
             "pero no generan cargo (útil para cargar historial sin facturarlo). Si se "
             "deja vacío, no aplica ninguna restricción.",
    )
    aso_calculos_anio = fields.Integer(string="Cálculos a partir de (Año)")
