# -*- coding: utf-8 -*-
import base64

from odoo import models, fields, api
from odoo.tools import image_process

CARTAS_POR_HOJA = 2
LOGO_MAX_HEIGHT = 140


class ReportCorteServicioNotificacion(models.AbstractModel):
    _name = "report.iit_asovec.report_corte_servicio_notificacion"
    _description = "Notificación de Corte de Servicio de Agua (2 por hoja)"

    @api.model
    def _get_cartas_data(self, lineas):
        cartas = []
        logos_cache = {}
        for linea in lineas:
            residencia = linea.residencia_id
            company = residencia.proyecto_aso_id.company_id or self.env.company

            if company.id not in logos_cache:
                if company.logo:
                    resized = image_process(base64.b64decode(company.logo), size=(0, LOGO_MAX_HEIGHT))
                    logos_cache[company.id] = base64.b64encode(resized) if resized else False
                else:
                    logos_cache[company.id] = False

            cartas.append({
                "proyecto": linea.proyecto_aso_id,
                "vecino": linea.cliente_id.name or "",
                "direccion": linea.direccion_real or "",
                "cuenta": residencia.name,
                "meses_atraso": linea.meses_atraso,
                "meses_detalle": linea.meses_detalle,
                "monto_atraso": linea.monto_atraso,
                "currency": linea.currency_id,
                "fecha_impresion": linea.fecha_impresion,
                "fecha_corte": linea.fecha_corte,
                "dias_habiles_corte": linea.dias_habiles_corte,
                "company": company,
                "logo": logos_cache[company.id],
                "leyenda": linea.proyecto_aso_id.leyenda_notificacion_corte,
            })
        return cartas

    @api.model
    def _get_report_values(self, docids, data=None):
        lineas = self.env["asovec.proceso_corte_servicio_wizard_line"].browse(docids)
        cartas = self._get_cartas_data(lineas)
        paginas = [
            cartas[i:i + CARTAS_POR_HOJA]
            for i in range(0, len(cartas), CARTAS_POR_HOJA)
        ]

        return {
            "doc_ids": docids,
            "doc_model": "asovec.proceso_corte_servicio_wizard_line",
            "docs": lineas,
            "paginas": paginas,
            "fecha_generacion": fields.Date.context_today(self),
        }
