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

    def _acumular_categoria(self, resumen, con_lectura):
        """Cuenta la categoría de lectura (Lectura Valida/Sin Lectura/Inactivo) según el
        estado REAL de la residencia (contador + activo), sin importar si ya existe una
        línea de cobro mensual para ella: 'Completar Faltantes' (que genera el cargo de
        las residencias Sin Lectura/Inactivo) se corre hasta el final del mes, así que
        estos conteos no pueden depender de que ese cargo ya exista."""
        if con_lectura == "Lectura Valida":
            resumen["lectura_valida"] += 1
        elif con_lectura == "Inactivo":
            resumen["inactivo"] += 1
        else:
            resumen["sin_lectura"] += 1

    def _acumular_dinero(self, resumen, line, move_lines_de_la_linea):
        """Acumula los montos (facturado/pagado/saldo/por servicio) de un cargo YA
        generado. Solo aplica a residencias que ya tienen línea de cobro mensual."""
        resumen["total_facturado"] += line.amount_total
        resumen["total_pagado"] += line.amount_paid
        resumen["total_saldo"] += line.amount_balance
        resumen["cantidad_residencias"] += 1
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

        # Residencias vigentes (no "No paga servicios"): se usan para contar Con
        # lectura/Sin lectura/Inactivas según su estado REAL este mes, sin importar si
        # "Completar Faltantes" ya generó su cargo o no.
        Residencia = self.env["asovec.residencia"]
        residencias_activas = Residencia.search([("no_paga_servicios", "=", False)])

        # Universo de proyectos: cualquiera con residencias vigentes, más cualquiera
        # que ya tenga líneas este mes (por si alguna residencia con línea ya no
        # califica en el filtro anterior), para no perder ningún proyecto.
        proyectos = (residencias_activas.mapped("proyecto_aso_id") | lines.mapped("proyecto_aso_id")).sorted("name")

        resumen_global = self._resumen_vacio()
        proyectos_data = []

        for proyecto in proyectos:
            residencias_proyecto = residencias_activas.filtered(lambda r, p=proyecto: r.proyecto_aso_id == p)
            lineas_proyecto = lines.filtered(lambda l, p=proyecto: l.proyecto_aso_id == p)

            resumen_proyecto = self._resumen_vacio()

            for _residencia, _lectura, _move, con_lectura, _total, _mstate, _pstate in CobroLine._lecturas_rows(
                residencias_proyecto, mes, anio
            ):
                self._acumular_categoria(resumen_proyecto, con_lectura)
                self._acumular_categoria(resumen_global, con_lectura)

            filas = []
            for line in lineas_proyecto:
                mls = move_lines_por_move.get(line.move_id.id, self.env["account.move.line"]) if line.move_id else self.env["account.move.line"]
                servicios_linea = {ml.product_id.name: ml.price_unit for ml in mls}
                filas.append({
                    "line": line,
                    "servicios": servicios_linea,
                })
                self._acumular_dinero(resumen_proyecto, line, mls)
                self._acumular_dinero(resumen_global, line, mls)

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
