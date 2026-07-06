# -*- coding: utf-8 -*-
import base64
import io

import xlsxwriter

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .contador import MONTH_SELECTION, mes_anio_anterior

ALCANCE_A_ESTADO = {
    "con_lectura": "Lectura Valida",
    "sin_lectura": "Sin Lectura",
    "inactivo": "Inactivo",
}


class ProcesoEstadoLecturasExcelWizard(models.TransientModel):
    _name = "asovec.proceso_estado_lecturas_excel_wizard"
    _description = "Generar Excel de Estado de Lecturas por Mes"

    mes = fields.Selection(MONTH_SELECTION, string="Mes", required=True)
    anio = fields.Integer(string="Año", required=True)
    todos_los_proyectos = fields.Boolean(string="Todos los proyectos", default=True)
    proyecto_aso_id = fields.Many2one(
        "asovec.proyecto_aso",
        string="Proyecto",
    )
    alcance = fields.Selection(
        [
            ("todos", "Todos"),
            ("con_lectura", "Con Lectura Válida"),
            ("sin_lectura", "Sin Lectura"),
            ("inactivo", "Inactivo"),
        ],
        string="Alcance",
        default="todos",
        required=True,
        help="Qué residencias incluir: las que tienen una lectura válida, las que no "
             "tienen lectura, las de contador inactivo, o todas juntas.",
    )
    file_data = fields.Binary(string="Archivo Excel", readonly=True)
    file_name = fields.Char(string="Nombre de archivo", readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        mes, anio = mes_anio_anterior(fields.Date.context_today(self))
        if "mes" in fields_list and not res.get("mes"):
            res["mes"] = mes
        if "anio" in fields_list and not res.get("anio"):
            res["anio"] = anio
        return res

    def _get_residencias(self):
        domain = []
        if not self.todos_los_proyectos:
            domain.append(("proyecto_aso_id", "=", self.proyecto_aso_id.id))
        return self.env["asovec.residencia"].search(domain, order="proyecto_aso_id, name")

    def _build_rows(self):
        """Recorre TODAS las residencias del alcance (con o sin cargo generado):
        el estado de lectura se calcula directamente de la lectura del contador, no
        depende de si ya se generó el cargo. Si no hay cargo, esas columnas quedan
        vacías, pero la residencia igual aparece en el listado."""
        self.ensure_one()

        residencias = self._get_residencias()
        if not residencias:
            raise UserError(_("No hay residencias para ese proyecto."))

        mes_plano = str(int(self.mes))
        mes_padded = str(self.mes).zfill(2)

        lecturas = self.env["asovec.contador.lines"].search([
            ("residencia_id", "in", residencias.ids),
            ("anio", "=", self.anio),
            ("mes", "=", mes_plano),
            ("es_inicial", "=", False),
        ])
        lectura_por_residencia = {l.residencia_id.id: l for l in lecturas}

        cobro_lines = self.env["asovec.proyecto_cobro_mensual_line"].search([
            ("residencia_id", "in", residencias.ids),
            ("month", "=", mes_padded),
            ("year", "=", self.anio),
            ("cobro_state", "!=", "cancel"),
        ])
        cobro_por_residencia = {cl.residencia_id.id: cl for cl in cobro_lines}

        rows = []
        for residencia in residencias:
            lectura = lectura_por_residencia.get(residencia.id)
            cobro_line = cobro_por_residencia.get(residencia.id)

            if not residencia.activo:
                estado = "Inactivo"
            elif lectura:
                estado = "Lectura Valida"
            else:
                estado = "Sin Lectura"

            if self.alcance != "todos" and estado != ALCANCE_A_ESTADO[self.alcance]:
                continue

            rows.append({
                "proyecto": residencia.proyecto_aso_id.name or "",
                "residencia": residencia.name,
                "cliente": residencia.cliente_id.name or "",
                "estado": estado,
                "lectura_anterior": lectura.lectura_anterior if lectura else None,
                "lectura_actual": lectura.lectura if lectura else None,
                "metros_extra": lectura.metros_extras if lectura else None,
                "cargo": cobro_line.move_id.name if cobro_line and cobro_line.move_id else None,
                "estado_cargo": cobro_line.move_state if cobro_line else None,
                "total": cobro_line.amount_total if cobro_line else None,
                "pagado": cobro_line.amount_paid if cobro_line else None,
                "saldo": cobro_line.amount_balance if cobro_line else None,
            })

        return rows

    def _build_workbook(self, rows, proyecto_label):
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
        sheet = workbook.add_worksheet("Estado de Lecturas")

        title_fmt = workbook.add_format({"bold": True, "font_size": 12})
        header_fmt = workbook.add_format({
            "bold": True, "bg_color": "#009999", "font_color": "#FFFFFF", "border": 1,
        })
        money_fmt = workbook.add_format({"num_format": "#,##0.00"})
        number_fmt = workbook.add_format({"num_format": "#,##0.00"})
        badge_fmts = {
            "Lectura Valida": workbook.add_format({"bg_color": "#c8e6c9"}),
            "Sin Lectura": workbook.add_format({"bg_color": "#ffcdd2"}),
            "Inactivo": workbook.add_format({"bg_color": "#e0e0e0"}),
        }

        sheet.write(0, 0, "Proyecto: %s" % proyecto_label, title_fmt)

        mes_label = dict(MONTH_SELECTION).get(self.mes, self.mes)
        sheet.write(0, 5, "Período: %s %s" % (mes_label, self.anio), title_fmt)

        headers = [
            "Proyecto", "Residencia", "Cliente", "Estado Lectura",
            "Lectura anterior", "Lectura actual", "Metros extra",
            "Cargo", "Estado Cargo", "Total", "Pagado", "Saldo",
        ]
        for col, title in enumerate(headers):
            sheet.write(1, col, title, header_fmt)

        row = 2
        for data in rows:
            estado_fmt = badge_fmts.get(data["estado"])
            sheet.write(row, 0, data["proyecto"])
            sheet.write(row, 1, data["residencia"])
            sheet.write(row, 2, data["cliente"])
            sheet.write(row, 3, data["estado"], estado_fmt)
            sheet.write(row, 4, data["lectura_anterior"] if data["lectura_anterior"] is not None else "", number_fmt)
            sheet.write(row, 5, data["lectura_actual"] if data["lectura_actual"] is not None else "", number_fmt)
            sheet.write(row, 6, data["metros_extra"] if data["metros_extra"] is not None else "", number_fmt)
            sheet.write(row, 7, data["cargo"] or "")
            sheet.write(row, 8, data["estado_cargo"] or "")
            sheet.write(row, 9, data["total"] if data["total"] is not None else "", money_fmt)
            sheet.write(row, 10, data["pagado"] if data["pagado"] is not None else "", money_fmt)
            sheet.write(row, 11, data["saldo"] if data["saldo"] is not None else "", money_fmt)
            row += 1

        column_widths = [22, 12, 30, 16, 15, 14, 13, 16, 14, 12, 12, 12]
        for col, width in enumerate(column_widths):
            sheet.set_column(col, col, width)

        workbook.close()
        buffer.seek(0)
        return buffer.read()

    def action_generar(self):
        self.ensure_one()

        if not self.todos_los_proyectos and not self.proyecto_aso_id:
            raise UserError(_("Selecciona un proyecto, o marca 'Todos los proyectos'."))

        rows = self._build_rows()
        if not rows:
            raise UserError(_("No hay residencias para ese alcance seleccionado."))

        proyecto_label = "Todos" if self.todos_los_proyectos else self.proyecto_aso_id.name
        xlsx_bytes = self._build_workbook(rows, proyecto_label)

        mes_label = dict(MONTH_SELECTION).get(self.mes, self.mes)
        nombre_archivo_proyecto = proyecto_label.replace(" ", "_")
        self.write({
            "file_data": base64.b64encode(xlsx_bytes),
            "file_name": "Estado_Lecturas_%s_%s_%s.xlsx" % (nombre_archivo_proyecto, mes_label, self.anio),
        })

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }
