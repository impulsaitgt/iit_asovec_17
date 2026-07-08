# -*- coding: utf-8 -*-
from odoo import models, fields, api

from .contador import MONTH_SELECTION, mes_anio_anterior


class ProcesoAnalisisMensualWizard(models.TransientModel):
    _name = "asovec.proceso_analisis_mensual_wizard"
    _description = "Análisis Mensual de la Asociación"

    mes = fields.Selection(MONTH_SELECTION, string="Mes", required=True)
    anio = fields.Integer(string="Año", required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        mes, anio = mes_anio_anterior(fields.Date.context_today(self))
        if "mes" in fields_list and not res.get("mes"):
            res["mes"] = mes
        if "anio" in fields_list and not res.get("anio"):
            res["anio"] = anio
        return res

    def action_generar(self):
        self.ensure_one()
        return self.env.ref("iit_asovec.action_report_analisis_mensual").report_action(self)
