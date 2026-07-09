# -*- coding: utf-8 -*-
import base64
import csv
import io

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .contador import MONTH_SELECTION


class ProcesoLecturasCsvWizard(models.TransientModel):
    _name = "asovec.proceso_lecturas_csv_wizard"
    _description = "Generar CSV de Lecturas (Todos los Proyectos)"

    mes = fields.Selection(MONTH_SELECTION, string="Mes", required=True)
    anio = fields.Integer(string="Año", required=True)
    proyecto_aso_ids = fields.Many2many(
        "asovec.proyecto_aso",
        string="Proyectos",
        help="Por defecto se incluyen todos los proyectos; quita los que no necesites.",
    )

    file_data = fields.Binary(string="Archivo CSV", readonly=True)
    file_name = fields.Char(string="Nombre de archivo", readonly=True)

    # --------------------
    # Indicadores de avance (igual criterio que asovec.proyecto_cobro_mensual, pero
    # totalizados en vivo para todos los proyectos seleccionados, sin depender de que
    # se haya corrido "Completar Faltantes").
    # --------------------
    total_residencias = fields.Integer(string="Total residencias", compute="_compute_indicadores")
    residencias_con_lectura = fields.Integer(string="Con lectura", compute="_compute_indicadores")
    pct_con_lectura = fields.Float(string="% Con lectura", compute="_compute_indicadores")
    residencias_sin_lectura = fields.Integer(string="Sin lectura", compute="_compute_indicadores")
    pct_sin_lectura = fields.Float(string="% Sin lectura", compute="_compute_indicadores")
    residencias_inactivas = fields.Integer(string="Inactivas", compute="_compute_indicadores")
    pct_inactivas = fields.Float(string="% Inactivas", compute="_compute_indicadores")
    residencias_cargo_generado = fields.Integer(string="Cargos generados", compute="_compute_indicadores")
    pct_cargo_generado = fields.Float(string="% Cargos generados", compute="_compute_indicadores")

    def _residencias_kpi(self):
        """Residencias que cuentan para los indicadores: las de los proyectos
        seleccionados que no estén marcadas 'No paga servicios' (mismo criterio que
        asovec.proyecto_cobro_mensual._residencias_scope)."""
        self.ensure_one()
        if not self.proyecto_aso_ids:
            return self.env["asovec.residencia"]
        return self.env["asovec.residencia"].search([
            ("proyecto_aso_id", "in", self.proyecto_aso_ids.ids),
            ("no_paga_servicios", "=", False),
        ])

    @api.depends("mes", "anio", "proyecto_aso_ids")
    def _compute_indicadores(self):
        Line = self.env["asovec.proyecto_cobro_mensual_line"]
        for rec in self:
            residencias = rec._residencias_kpi() if (rec.proyecto_aso_ids and rec.mes and rec.anio) else self.env["asovec.residencia"]

            con_lectura = sin_lectura = inactivas = cargo_generado = 0
            if residencias:
                for _residencia, _lectura, move, con_lectura_estado, *_rest in Line._lecturas_rows(residencias, rec.mes, rec.anio):
                    if con_lectura_estado == "Lectura Valida":
                        con_lectura += 1
                    elif con_lectura_estado == "Inactivo":
                        inactivas += 1
                    else:
                        sin_lectura += 1
                    if move:
                        cargo_generado += 1

            total = len(residencias)
            activas = total - inactivas

            rec.total_residencias = total
            rec.residencias_con_lectura = con_lectura
            rec.residencias_sin_lectura = sin_lectura
            rec.residencias_inactivas = inactivas
            rec.residencias_cargo_generado = cargo_generado

            rec.pct_con_lectura = (con_lectura / activas) if activas else 0.0
            rec.pct_sin_lectura = (sin_lectura / activas) if activas else 0.0
            rec.pct_inactivas = (inactivas / total) if total else 0.0
            rec.pct_cargo_generado = (cargo_generado / total) if total else 0.0

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # A diferencia de otros procesos (que sugieren el mes ANTERIOR, ya cerrado),
        # esta consulta es para ver el panorama de lecturas del mes en curso mientras
        # se van recibiendo, por lo que sugiere el mes ACTUAL.
        today = fields.Date.context_today(self)
        if "mes" in fields_list and not res.get("mes"):
            res["mes"] = str(today.month)
        if "anio" in fields_list and not res.get("anio"):
            res["anio"] = today.year
        if "proyecto_aso_ids" in fields_list and not res.get("proyecto_aso_ids"):
            proyectos = self.env["asovec.proyecto_aso"].search([])
            res["proyecto_aso_ids"] = [(6, 0, proyectos.ids)]
        return res

    def _residencias(self):
        self.ensure_one()
        residencias = self.env["asovec.residencia"].search([
            ("proyecto_aso_id", "in", self.proyecto_aso_ids.ids),
        ], order="proyecto_aso_id, name")
        if not residencias:
            raise UserError(_("No hay residencias para los proyectos seleccionados."))
        return residencias

    def _generar_categoria(self, categoria, nombre_archivo):
        self.ensure_one()

        if not self.proyecto_aso_ids:
            raise UserError(_("Selecciona al menos un proyecto."))

        residencias = self._residencias()
        Line = self.env["asovec.proyecto_cobro_mensual_line"]
        rows = [
            r for r in Line._lecturas_rows(residencias, self.mes, self.anio)
            if r[3] == categoria
        ]
        if not rows:
            raise UserError(_(
                "No hay residencias en esa categoría para ese mes/año en los "
                "proyectos seleccionados."
            ))

        servicios = Line._csv_servicios()
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(Line._csv_header(servicios))
        for residencia, lectura, move, con_lectura, amount_total, move_state, payment_state in rows:
            writer.writerow(Line._csv_row(
                residencia, lectura, move, con_lectura, amount_total, move_state, payment_state, servicios,
            ))

        csv_data = ("﻿" + buffer.getvalue()).encode("utf-8")

        mes_label = dict(MONTH_SELECTION).get(self.mes, self.mes)
        self.write({
            "file_data": base64.b64encode(csv_data),
            "file_name": "%s_%s_%s.csv" % (nombre_archivo, mes_label, self.anio),
        })

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }

    def action_generar(self):
        """Solo residencias CON LECTURA VÁLIDA este período (excluye inactivas y sin
        lectura: para eso están los otros dos botones)."""
        return self._generar_categoria("Lectura Valida", "Lecturas_Validas")

    def action_generar_inactivos(self):
        """Residencias/contadores inactivos, para revisar si alguno debe reactivarse."""
        return self._generar_categoria("Inactivo", "Lecturas_Inactivas")

    def action_generar_sin_lectura(self):
        """Residencias activas que todavía no tienen lectura este período, para ver
        qué falta."""
        return self._generar_categoria("Sin Lectura", "Lecturas_SinLectura")
