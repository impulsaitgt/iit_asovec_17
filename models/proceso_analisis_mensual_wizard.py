# -*- coding: utf-8 -*-
import base64
import io

import xlsxwriter

from odoo import models, fields, api

from .contador import MONTH_SELECTION

_INVALID_SHEET_CHARS = set('[]:*?/\\')


class ProcesoAnalisisMensualWizard(models.TransientModel):
    _name = "asovec.proceso_analisis_mensual_wizard"
    _description = "Análisis Mensual de la Asociación"

    mes = fields.Selection(MONTH_SELECTION, string="Mes", required=True)
    anio = fields.Integer(string="Año", required=True)
    file_data = fields.Binary(string="Archivo Excel", readonly=True)
    file_name = fields.Char(string="Nombre de archivo", readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        if "mes" in fields_list and not res.get("mes"):
            res["mes"] = str(today.month)
        if "anio" in fields_list and not res.get("anio"):
            res["anio"] = today.year
        return res

    def action_generar(self):
        self.ensure_one()
        return self.env.ref("iit_asovec.action_report_analisis_mensual").report_action(self)

    # -------------------------
    # Exportación a Excel
    # -------------------------
    @api.model
    def _sheet_name(self, nombre, usados):
        """Nombre de hoja válido para Excel (máx. 31 caracteres, sin [ ] : * ? / \\) y
        sin repetirse dentro del mismo libro."""
        limpio = "".join(c for c in (nombre or "Proyecto") if c not in _INVALID_SHEET_CHARS).strip()
        limpio = (limpio or "Proyecto")[:31]

        base = limpio
        i = 2
        while limpio in usados:
            sufijo = " (%s)" % i
            limpio = base[: 31 - len(sufijo)] + sufijo
            i += 1
        usados.add(limpio)
        return limpio

    def _escribir_fila_resumen(self, worksheet, row, resumen, fmt_label, fmt_int, fmt_money):
        filas = [
            ("Residencias con cargo", resumen["cantidad_residencias"], fmt_int),
            ("Total facturado", resumen["total_facturado"], fmt_money),
            ("Total pagado", resumen["total_pagado"], fmt_money),
            ("Saldo pendiente", resumen["total_saldo"], fmt_money),
            ("Con lectura válida", resumen["lectura_valida"], fmt_int),
            ("Sin lectura", resumen["sin_lectura"], fmt_int),
            ("Inactivas", resumen["inactivo"], fmt_int),
        ]
        for label, value, fmt in filas:
            worksheet.write(row, 0, label, fmt_label)
            worksheet.write(row, 1, value, fmt)
            row += 1
        return row

    def _escribir_tabla_servicios(self, worksheet, row, resumen, servicios_nombres, fmt_header, fmt_money, col=0):
        worksheet.write(row, col, "Servicio", fmt_header)
        worksheet.write(row, col + 1, "Monto", fmt_header)
        row += 1
        for nombre in servicios_nombres:
            worksheet.write(row, col, nombre)
            worksheet.write(row, col + 1, resumen["por_servicio"].get(nombre, 0.0), fmt_money)
            row += 1
        return row

    def _escribir_hoja_resumen(self, workbook, datos, formatos):
        worksheet = workbook.add_worksheet(self._sheet_name("Resumen General", set()))
        worksheet.set_column(0, 0, 28)
        worksheet.set_column(1, 7, 16)

        company = self.env.company
        worksheet.write(0, 0, "Análisis Mensual de la Asociación", formatos["titulo"])
        worksheet.write(1, 0, "%s %s — %s" % (datos["mes_label"], datos["anio"], company.name), formatos["subtitulo"])

        row = 3
        worksheet.write(row, 0, "Resumen general — todos los proyectos", formatos["seccion"])
        row += 1
        row = self._escribir_fila_resumen(
            worksheet, row, datos["resumen_global"], formatos["label"], formatos["entero"], formatos["dinero"]
        )

        row += 1
        worksheet.write(row, 0, "Totales por servicio", formatos["seccion"])
        row += 1
        row = self._escribir_tabla_servicios(
            worksheet, row, datos["resumen_global"], datos["servicios_nombres"], formatos["header"], formatos["dinero"]
        )

        row += 1
        worksheet.write(row, 0, "Resumen por proyecto", formatos["seccion"])
        row += 1
        encabezados = [
            "Proyecto", "Residencias con cargo", "Total facturado", "Total pagado",
            "Saldo pendiente", "Con lectura válida", "Sin lectura", "Inactivas",
        ]
        for col, texto in enumerate(encabezados):
            worksheet.write(row, col, texto, formatos["header"])
        row += 1
        for proy_data in datos["proyectos_data"]:
            resumen = proy_data["resumen"]
            worksheet.write(row, 0, proy_data["proyecto"].name)
            worksheet.write(row, 1, resumen["cantidad_residencias"], formatos["entero"])
            worksheet.write(row, 2, resumen["total_facturado"], formatos["dinero"])
            worksheet.write(row, 3, resumen["total_pagado"], formatos["dinero"])
            worksheet.write(row, 4, resumen["total_saldo"], formatos["dinero"])
            worksheet.write(row, 5, resumen["lectura_valida"], formatos["entero"])
            worksheet.write(row, 6, resumen["sin_lectura"], formatos["entero"])
            worksheet.write(row, 7, resumen["inactivo"], formatos["entero"])
            row += 1

    def _escribir_hoja_proyecto(self, workbook, proy_data, datos, nombre_hoja, formatos):
        worksheet = workbook.add_worksheet(nombre_hoja)
        servicios_nombres = datos["servicios_nombres"]

        # Residencia, Cliente, Total, Pagado, Saldo, Estado cargo, Lectura, Lectura
        # anterior, Lectura actual, Consumo (m³), Exceso (m³)
        columnas_fijas = 11
        col_servicios = 3  # deja la columna 2 vacía como separación con "Resumen del proyecto"
        col_observaciones = columnas_fijas + len(servicios_nombres)
        col_con_foto = col_observaciones + 1
        worksheet.set_column(0, 1, 28)
        worksheet.set_column(2, 2, 14)
        worksheet.set_column(3, 3, 26)
        worksheet.set_column(4, 4, 14)
        worksheet.set_column(5, 6, 16)
        worksheet.set_column(7, 10, 14)
        if servicios_nombres:
            worksheet.set_column(columnas_fijas, columnas_fijas + len(servicios_nombres) - 1, 16)
        worksheet.set_column(col_observaciones, col_observaciones, 40)
        worksheet.set_column(col_con_foto, col_con_foto, 12)

        worksheet.write(0, 0, proy_data["proyecto"].name, formatos["titulo"])
        worksheet.write(1, 0, "%s %s" % (datos["mes_label"], datos["anio"]), formatos["subtitulo"])

        # "Resumen del proyecto" y "Totales por servicio" van lado a lado (en vez de uno
        # debajo del otro) para que el encabezado de la hoja no quede tan largo.
        row_titulos = 3
        worksheet.write(row_titulos, 0, "Resumen del proyecto", formatos["seccion"])
        fin_resumen = self._escribir_fila_resumen(
            worksheet, row_titulos + 1, proy_data["resumen"], formatos["label"], formatos["entero"], formatos["dinero"]
        )

        worksheet.write(row_titulos, col_servicios, "Totales por servicio", formatos["seccion"])
        fin_servicios = self._escribir_tabla_servicios(
            worksheet, row_titulos + 1, proy_data["resumen"], servicios_nombres,
            formatos["header"], formatos["dinero"], col=col_servicios,
        )

        row = max(fin_resumen, fin_servicios) + 1
        worksheet.write(row, 0, "Detalle de residencias", formatos["seccion"])
        row += 1

        encabezados = [
            "Residencia", "Cliente", "Total", "Pagado", "Saldo", "Estado cargo", "Lectura",
            "Lectura anterior", "Lectura actual", "Consumo (m³)", "Exceso (m³)",
        ] + servicios_nombres + ["Observaciones", "Con Foto"]
        for col, texto in enumerate(encabezados):
            worksheet.write(row, col, texto, formatos["header"])
        header_row = row
        row += 1

        for fila in proy_data["filas"]:
            line = fila["line"]
            worksheet.write(row, 0, line.residencia_id.name or "")
            worksheet.write(row, 1, line.cliente_id.name or "")
            worksheet.write(row, 2, line.amount_total, formatos["dinero"])
            worksheet.write(row, 3, line.amount_paid, formatos["dinero"])
            worksheet.write(row, 4, line.amount_balance, formatos["dinero"])
            worksheet.write(row, 5, line.move_state or "Sin cargo")
            worksheet.write(row, 6, line.con_lectura or "")
            if line.contador_line_id:
                worksheet.write(row, 7, line.lectura_anterior, formatos["dinero"])
                worksheet.write(row, 8, line.lectura_actual, formatos["dinero"])
                worksheet.write(row, 9, line.consumo, formatos["dinero"])
                worksheet.write(row, 10, line.exceso, formatos["dinero"])
            for i, nombre in enumerate(servicios_nombres):
                valor = fila["servicios"].get(nombre)
                if valor is not None:
                    worksheet.write(row, columnas_fijas + i, valor, formatos["dinero"])
            worksheet.write(row, col_observaciones, line.observaciones or "")
            worksheet.write(row, col_con_foto, "Con Foto" if line.foto else "")
            row += 1

        worksheet.freeze_panes(header_row + 1, 2)

    def action_generar_excel(self):
        self.ensure_one()
        datos = self.env["report.iit_asovec.report_analisis_mensual_document"]._build_analisis_data(self)

        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})

        formatos = {
            "titulo": workbook.add_format({"bold": True, "font_size": 14}),
            "subtitulo": workbook.add_format({"italic": True, "font_color": "#666666"}),
            "seccion": workbook.add_format({"bold": True, "font_size": 11, "font_color": "#009999"}),
            "header": workbook.add_format({
                "bold": True, "bg_color": "#009999", "font_color": "#ffffff", "border": 1,
            }),
            "label": workbook.add_format({"bold": True}),
            "entero": workbook.add_format({"num_format": "#,##0"}),
            "dinero": workbook.add_format({"num_format": "#,##0.00"}),
        }

        self._escribir_hoja_resumen(workbook, datos, formatos)

        nombres_usados = {"Resumen General"}
        for proy_data in datos["proyectos_data"]:
            nombre_hoja = self._sheet_name(proy_data["proyecto"].name, nombres_usados)
            self._escribir_hoja_proyecto(workbook, proy_data, datos, nombre_hoja, formatos)

        workbook.close()
        buffer.seek(0)

        filename = "Analisis_Mensual_%s_%s.xlsx" % (datos["mes_label"], self.anio)
        self.write({
            "file_data": base64.b64encode(buffer.read()),
            "file_name": filename,
        })

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }
