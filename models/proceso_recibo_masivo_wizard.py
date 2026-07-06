# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .contador import MONTH_SELECTION, mes_anio_anterior


class ProcesoReciboMasivoWizard(models.TransientModel):
    _name = "asovec.proceso_recibo_masivo_wizard"
    _description = "Generar Recibos Mensuales por Proyecto (Masivo)"

    proyecto_aso_id = fields.Many2one("asovec.proyecto_aso", string="Proyecto", required=True)
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

        residencias = self.env["asovec.residencia"].search([
            ("proyecto_aso_id", "=", self.proyecto_aso_id.id),
        ], order="name")

        contadores = self.env["asovec.contador"]
        for residencia in residencias:
            contador = residencia._get_contador_activo()
            if contador:
                contadores |= contador

        if not contadores:
            raise UserError(_("Ninguna residencia de este proyecto tiene un contador activo."))

        lecturas = self.env["asovec.contador.lines"].search([
            ("contador_id", "in", contadores.ids),
            ("es_inicial", "=", False),
            ("mes", "=", self.mes),
            ("anio", "=", self.anio),
        ])

        if not lecturas:
            mes_label = dict(MONTH_SELECTION).get(self.mes, self.mes)
            raise UserError(_("No hay lecturas registradas para %s/%s en este proyecto.") % (mes_label, self.anio))

        # Ordenar los recibos según el orden de las residencias (por nombre).
        lectura_por_residencia = {lectura.residencia_id.id: lectura for lectura in lecturas}
        ordered_ids = [
            lectura_por_residencia[residencia.id].id
            for residencia in residencias
            if residencia.id in lectura_por_residencia
        ]
        lecturas = self.env["asovec.contador.lines"].browse(ordered_ids)

        return self.env.ref("iit_asovec.action_report_recibo_residencia_mensual_masivo").report_action(lecturas)
