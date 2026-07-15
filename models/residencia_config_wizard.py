# -*- coding: utf-8 -*-
import base64
import io

import xlsxwriter

from odoo import api, models, fields

_INVALID_FILENAME_CHARS = set('\\/:*?"<>|')


class ResidenciaConfigWizard(models.TransientModel):
    _name = "asovec.residencia_config_wizard"
    _description = "Configuración de Residencias"

    proyecto_aso_ids = fields.Many2many(
        "asovec.proyecto_aso", string="Proyectos",
        help="Por defecto se incluyen todos los proyectos.",
    )

    file_data = fields.Binary(string="Archivo Excel", readonly=True)
    file_name = fields.Char(string="Nombre de archivo", readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "proyecto_aso_ids" in fields_list and not res.get("proyecto_aso_ids"):
            res["proyecto_aso_ids"] = [(6, 0, self.env["asovec.proyecto_aso"].search([]).ids)]
        return res

    # -------------------------
    # Configuración de Residencias (HTML, imprimible desde el navegador)
    # -------------------------
    def action_generar(self):
        self.ensure_one()
        return self.env.ref("iit_asovec.action_report_residencia_config_html").report_action(self)

    # -------------------------
    # Exportación a Excel
    # -------------------------
    def action_generar_excel(self):
        self.ensure_one()
        datos = self.env["report.iit_asovec.report_residencia_config_document"]._build_residencia_config_data(self)

        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
        worksheet = workbook.add_worksheet("Configuración Residencias")

        fmt_titulo = workbook.add_format({"bold": True, "font_size": 14})
        fmt_subtitulo = workbook.add_format({"italic": True, "font_color": "#666666"})
        fmt_header = workbook.add_format({
            "bold": True, "bg_color": "#009999", "font_color": "#ffffff", "border": 1,
        })
        fmt_dinero = workbook.add_format({"num_format": "#,##0.00"})

        servicios_nombres = datos["servicios_nombres"]
        columnas_fijas = 9
        col_servicios = columnas_fijas

        worksheet.set_column(0, 1, 22)
        worksheet.set_column(2, 2, 30)
        worksheet.set_column(3, 3, 24)
        worksheet.set_column(4, 5, 14)
        worksheet.set_column(6, 6, 12)
        worksheet.set_column(7, 8, 20)
        if servicios_nombres:
            worksheet.set_column(col_servicios, col_servicios + len(servicios_nombres) - 1, 16)

        worksheet.write(0, 0, "Configuración de Residencias", fmt_titulo)
        worksheet.write(1, 0, "Generado: %s" % datos["generated_at"], fmt_subtitulo)

        row = 3
        encabezados = [
            "Proyecto", "Residencia", "Dirección", "Residente",
            "Canon de agua", "Valor Canon", "Exceso exonerado",
            "Cobra inactivo", "Contador",
        ] + servicios_nombres
        for col, texto in enumerate(encabezados):
            worksheet.write(row, col, texto, fmt_header)
        header_row = row
        row += 1

        for fila in datos["filas"]:
            worksheet.write(row, 0, fila["proyecto"].name or "")
            nombre_residencia = fila["residencia"].name or ""
            if fila["no_paga_servicios"]:
                nombre_residencia += " (No paga servicios)"
            worksheet.write(row, 1, nombre_residencia)
            worksheet.write(row, 2, fila["direccion"] or "")
            worksheet.write(row, 3, fila["residente"].name or "")
            worksheet.write(row, 4, "Sí (%s)" % ("propio" if fila["canon_propio"] else "proyecto") if fila["canon_paga"] else "No")
            worksheet.write(row, 5, fila["canon_valor"], fmt_dinero)
            worksheet.write(row, 6, "Sí" if fila["exonera_exceso"] else "No")
            worksheet.write(row, 7, "Sí (%.2f)" % fila["valor_inactivo"] if fila["cobra_inactivo"] else "No (activa)")
            worksheet.write(row, 8, fila["contador"].name if fila["contador"] else "")
            for i, nombre in enumerate(servicios_nombres):
                info = fila["servicios"].get(nombre, {})
                estado = info.get("estado")
                if estado == "paga":
                    worksheet.write(row, col_servicios + i, info["precio"], fmt_dinero)
                elif estado == "no_paga":
                    worksheet.write(row, col_servicios + i, "No")
                elif estado == "no_aplica":
                    worksheet.write(row, col_servicios + i, "No aplica (inactiva)")
                else:
                    worksheet.write(row, col_servicios + i, "—")
            row += 1

        worksheet.freeze_panes(header_row + 1, 2)
        workbook.close()
        buffer.seek(0)

        filename = "Configuracion_Residencias_%s.xlsx" % datos["generated_at"].replace("/", "-").replace(":", "-").replace(" ", "_")
        filename = "".join(c for c in filename if c not in _INVALID_FILENAME_CHARS)
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
