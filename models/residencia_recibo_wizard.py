# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .contador import MONTH_SELECTION, mes_anio_anterior


class ResidenciaReciboWizard(models.TransientModel):
    _name = "asovec.residencia_recibo_wizard"
    _description = "Imprimir Recibo de Residencia por Mes/Año"

    residencia_id = fields.Many2one("asovec.residencia", string="Residencia", required=True)
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

    def action_imprimir(self):
        self.ensure_one()

        contador = self.residencia_id._get_contador_activo()
        if not contador:
            raise UserError(_("Esta residencia no tiene un contador activo."))

        lectura = self.env["asovec.contador.lines"].search([
            ("contador_id", "=", contador.id),
            ("es_inicial", "=", False),
            ("mes", "=", self.mes),
            ("anio", "=", self.anio),
        ], limit=1)

        if not lectura:
            mes_label = dict(MONTH_SELECTION).get(self.mes, self.mes)
            raise UserError(_("No existe una lectura registrada para %s/%s en esta residencia.") % (mes_label, self.anio))

        return self.env.ref("iit_asovec.action_report_recibo_residencia_mensual").report_action(lectura)
