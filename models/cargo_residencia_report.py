# -*- coding: utf-8 -*-
import base64

from odoo import models, fields, api
from odoo.tools import image_process

LOGO_MAX_HEIGHT = 120


class ReportCargoResidencia(models.AbstractModel):
    _name = "report.iit_asovec.report_cargo_residencia"
    _description = "Recibo de Cargo por Residencia (Cobro Mensual)"

    @api.model
    def _get_servicios(self, move):
        if not move:
            return []
        return [
            {"nombre": line.name or (line.product_id.name if line.product_id else ""), "valor": line.price_subtotal}
            for line in move.invoice_line_ids
        ]

    @api.model
    def _get_cargo_data(self, lines):
        datos = []
        logos_cache = {}

        for line in lines:
            company = line.cobro_id.company_id or self.env.company
            if company.id not in logos_cache:
                if company.logo:
                    resized = image_process(base64.b64decode(company.logo), size=(0, LOGO_MAX_HEIGHT))
                    logos_cache[company.id] = base64.b64encode(resized) if resized else False
                else:
                    logos_cache[company.id] = False

            move = line.move_id
            residencia = line.residencia_id
            contador = residencia._get_contador_activo()

            meses = dict(self.env["asovec.proyecto_cobro_mensual"]._fields["month"].selection)
            periodo = "%s %s" % (meses.get(line.month, line.month or ""), line.year or "")

            datos.append({
                "line": line,
                "company": company,
                "logo": logos_cache[company.id],
                "diario": move.journal_id.name if move else "",
                "numero": move.name if (move and move.state == "posted") else "",
                "fecha": move.invoice_date if (move and move.invoice_date) else fields.Date.context_today(self),
                "cliente": residencia.cliente_id.name or "",
                "direccion": residencia.direccion_real or "",
                "nit": residencia.cliente_id.vat or "",
                "cuenta": residencia.name,
                "periodo": periodo,
                "contador": contador.name if contador else "",
                "lectura_anterior": line.lectura_anterior,
                "lectura_actual": line.lectura_actual,
                "servicios": self._get_servicios(move),
                "total": move.amount_total if move else (line.amount_total or 0.0),
                "currency": line.currency_id or company.currency_id,
            })
        return datos

    @api.model
    def _get_report_values(self, docids, data=None):
        lines = self.env["asovec.proyecto_cobro_mensual_line"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "asovec.proyecto_cobro_mensual_line",
            "docs": lines,
            "cargos": self._get_cargo_data(lines),
        }
