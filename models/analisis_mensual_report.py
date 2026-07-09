# -*- coding: utf-8 -*-
import base64
from collections import defaultdict

from odoo import models, api
from odoo.tools import image_process

from .contador import MONTH_SELECTION

LOGO_MAX_HEIGHT = 90


class ReportAnalisisMensual(models.AbstractModel):
    _name = "report.iit_asovec.report_analisis_mensual_document"
    _description = "Análisis Mensual de la Asociación (documento)"

    def _resumen_vacio(self):
        return {
            "total_facturado": 0.0,
            "total_pagado": 0.0,
            "total_saldo": 0.0,
            "cantidad_residencias": 0,
            "lectura_valida": 0,
            "sin_lectura": 0,
            "inactivo": 0,
            "por_servicio": defaultdict(float),
        }

    def _acumular_resumen(self, resumen, line, move_lines_de_la_linea):
        resumen["total_facturado"] += line.amount_total
        resumen["total_pagado"] += line.amount_paid
        resumen["total_saldo"] += line.amount_balance
        resumen["cantidad_residencias"] += 1
        if line.con_lectura == "Lectura Valida":
            resumen["lectura_valida"] += 1
        elif line.con_lectura == "Inactivo":
            resumen["inactivo"] += 1
        else:
            resumen["sin_lectura"] += 1
        for ml in move_lines_de_la_linea:
            resumen["por_servicio"][ml.product_id.name] += ml.price_unit

    @api.model
    def _build_analisis_data(self, wizard):
        """Arma el resumen global, el resumen y detalle por proyecto para el mes/año del
        wizard. Se comparte entre el reporte HTML y la exportación a Excel, para que
        ambos siempre muestren exactamente los mismos números."""
        wizard.ensure_one()
        mes = wizard.mes
        anio = wizard.anio
        mes_padded = str(mes).zfill(2)
        mes_label = dict(MONTH_SELECTION).get(mes, mes)

        CobroLine = self.env["asovec.proyecto_cobro_mensual_line"]
        lines = CobroLine.search([
            ("month", "=", mes_padded),
            ("year", "=", anio),
        ], order="proyecto_aso_id, residencia_id")

        moves = lines.mapped("move_id")
        move_lines = self.env["account.move.line"].search([
            ("move_id", "in", moves.ids),
            ("display_type", "=", "product"),
            ("product_id", "!=", False),
        ])
        move_lines_por_move = defaultdict(lambda: self.env["account.move.line"])
        for ml in move_lines:
            move_lines_por_move[ml.move_id.id] |= ml

        servicios_nombres = sorted(set(move_lines.mapped("product_id.name")))

        resumen_global = self._resumen_vacio()
        proyectos_data = []

        proyectos = lines.mapped("proyecto_aso_id").sorted("name")
        for proyecto in proyectos:
            lineas_proyecto = lines.filtered(lambda l, p=proyecto: l.proyecto_aso_id == p)
            resumen_proyecto = self._resumen_vacio()
            filas = []
            for line in lineas_proyecto:
                mls = move_lines_por_move.get(line.move_id.id, self.env["account.move.line"]) if line.move_id else self.env["account.move.line"]
                servicios_linea = {ml.product_id.name: ml.price_unit for ml in mls}
                filas.append({
                    "line": line,
                    "servicios": servicios_linea,
                })
                self._acumular_resumen(resumen_proyecto, line, mls)
                self._acumular_resumen(resumen_global, line, mls)

            proyectos_data.append({
                "proyecto": proyecto,
                "resumen": resumen_proyecto,
                "filas": filas,
            })

        return {
            "mes_label": mes_label,
            "anio": anio,
            "servicios_nombres": servicios_nombres,
            "resumen_global": resumen_global,
            "proyectos_data": proyectos_data,
        }

    @api.model
    def _get_report_values(self, docids, data=None):
        wizard = self.env["asovec.proceso_analisis_mensual_wizard"].browse(docids)
        wizard.ensure_one()
        datos = self._build_analisis_data(wizard)

        company = self.env.company
        logo_b64 = False
        if company.logo:
            resized = image_process(base64.b64decode(company.logo), size=(0, LOGO_MAX_HEIGHT))
            if resized:
                logo_b64 = base64.b64encode(resized).decode()

        return {
            "doc_ids": docids,
            "doc_model": "asovec.proceso_analisis_mensual_wizard",
            "docs": wizard,
            "company": company,
            "logo_b64": logo_b64,
            **datos,
        }
