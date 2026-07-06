# -*- coding: utf-8 -*-
from odoo import models, fields, api

RECIBOS_POR_HOJA = 4


class ReportReciboResidenciaMensualMasivo(models.AbstractModel):
    _name = "report.iit_asovec.report_recibo_residencia_mensual_masivo"
    _description = "Recibos Mensuales por Proyecto (Proceso Masivo, 4 por hoja)"

    @api.model
    def _get_report_values(self, docids, data=None):
        lecturas = self.env["asovec.contador.lines"].browse(docids)

        card_report = self.env["report.iit_asovec.report_recibo_residencia_mensual"]
        recibos = card_report._get_recibo_data(lecturas)

        paginas = [
            recibos[i:i + RECIBOS_POR_HOJA]
            for i in range(0, len(recibos), RECIBOS_POR_HOJA)
        ]

        return {
            "doc_ids": docids,
            "doc_model": "asovec.contador.lines",
            "docs": lecturas,
            "paginas": paginas,
            "fecha_generacion": fields.Date.context_today(self),
        }
