# -*- coding: utf-8 -*-
import base64
import io

import xlsxwriter

from odoo import api, models, fields, _
from odoo.exceptions import UserError

_INVALID_FILENAME_CHARS = set('\\/:*?"<>|')


class CobroMensualConsultaWizard(models.TransientModel):
    _name = "asovec.cobro_mensual_consulta_wizard"
    _description = "Consulta Cobros Mensuales por Proyecto y Residencia"

    proyecto_aso_id = fields.Many2one(
        "asovec.proyecto_aso",
        string="Proyecto",
        help="Filtro opcional para la lista de Residencia. Se completa solo si busca "
             "por Residente y sus residencias pertenecen a un mismo proyecto.",
    )

    residencia_ids = fields.Many2many(
        "asovec.residencia",
        string="Residencia(s)",
        required=True,
        domain="[('cliente_id', '=', buscar_cliente_id)] if buscar_cliente_id "
               "else ([('proyecto_aso_id', '=', proyecto_aso_id)] if proyecto_aso_id else [])",
        help="Un residente puede tener más de una residencia: todas las que seleccione "
             "deben pertenecer al mismo residente.",
    )

    buscar_cliente_id = fields.Many2one(
        "res.partner", string="Buscar por Residente",
        help="Si no conoce el proyecto o la residencia, busque aquí por el nombre del "
             "residente: se sugerirán automáticamente todas sus residencias (puede quitar "
             "las que no necesite).",
    )

    cliente_id = fields.Many2one(
        "res.partner", string="Residente", compute="_compute_cliente_id", store=True, readonly=True,
    )
    solo_residente_actual = fields.Boolean(string="Solo movimientos del residente actual", default=True)

    file_data = fields.Binary(string="Archivo Excel", readonly=True)
    file_name = fields.Char(string="Nombre de archivo", readonly=True)

    @api.depends("residencia_ids.cliente_id")
    def _compute_cliente_id(self):
        for rec in self:
            clientes = rec.residencia_ids.mapped("cliente_id")
            rec.cliente_id = clientes if len(clientes) == 1 else False

    @api.constrains("residencia_ids")
    def _check_residencias_mismo_cliente(self):
        for rec in self:
            if len(rec.residencia_ids.mapped("cliente_id")) > 1:
                raise UserError(_("Todas las residencias seleccionadas deben pertenecer al mismo residente."))

    @api.onchange("residencia_ids")
    def _onchange_residencia_ids(self):
        if not self.residencia_ids:
            return
        clientes = self.residencia_ids.mapped("cliente_id")
        if len(clientes) > 1:
            primero = self.residencia_ids[0].cliente_id
            self.residencia_ids = self.residencia_ids.filtered(lambda r: r.cliente_id == primero)
            return {"warning": {
                "title": _("Residente distinto"),
                "message": _("Solo puede agregar residencias del mismo residente. Se "
                             "quitaron las que no coinciden."),
            }}
        self.proyecto_aso_id = self.residencia_ids[0].proyecto_aso_id

    @api.onchange("buscar_cliente_id")
    def _onchange_buscar_cliente_id(self):
        if not self.buscar_cliente_id:
            return
        residencias = self.env["asovec.residencia"].search([("cliente_id", "=", self.buscar_cliente_id.id)])
        self.residencia_ids = residencias
        if residencias:
            self.proyecto_aso_id = residencias[0].proyecto_aso_id

    # -------------------------
    # Estado de cuenta (HTML, imprimible a PDF desde el navegador)
    # -------------------------
    def action_generar(self):
        self.ensure_one()
        return self.env.ref("iit_asovec.action_report_estado_cuenta_html").report_action(self)

    # -------------------------
    # Imprimir PDF (descarga directa)
    # -------------------------
    def action_print_pdf(self):
        self.ensure_one()
        # IMPORTANTE: pasar data={} fuerza a Odoo a usar docs (recordset)
        return self.env.ref("iit_asovec.action_report_estado_cuenta_pdf").report_action(self, data={})

    # -------------------------
    # Líneas de cobro mensual (con cargo) de una residencia. La deuda migrada y los
    # pagos se agregan aparte, ver
    # report.iit_asovec.report_estado_cuenta_document._movimientos_residencia
    # -------------------------
    def _get_cobro_lines_residencia(self, residencia):
        self.ensure_one()

        domain = [
            ("residencia_id", "=", residencia.id),
            ("cobro_id.state", "=", "posted"),
            ("move_id", "!=", False),
            # El estado del cobro mensual (el mes completo) no se sincroniza
            # automáticamente si alguien resetea a borrador o cancela una factura
            # individual desde Contabilidad, así que se revisa también el estado
            # real de la factura de esta línea, no solo el del cobro.
            ("move_id.state", "=", "posted"),
        ]
        if self.solo_residente_actual and self.cliente_id:
            domain.append(("cliente_id", "=", self.cliente_id.id))

        return self.env["asovec.proyecto_cobro_mensual_line"].search(domain, order="year, month, id")

    # -------------------------
    # Exportación a Excel
    # -------------------------
    def action_generar_excel(self):
        self.ensure_one()
        datos = self.env["report.iit_asovec.report_estado_cuenta_document"]._build_estado_cuenta_data(self)

        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
        worksheet = workbook.add_worksheet("Estado de Cuenta")

        fmt_titulo = workbook.add_format({"bold": True, "font_size": 14})
        fmt_subtitulo = workbook.add_format({"italic": True, "font_color": "#666666"})
        fmt_header = workbook.add_format({
            "bold": True, "bg_color": "#009999", "font_color": "#ffffff", "border": 1,
        })
        fmt_dinero = workbook.add_format({"num_format": "#,##0.00"})
        fmt_fecha = workbook.add_format({"num_format": "dd/mm/yyyy"})
        fmt_dot = workbook.add_format({"font_color": "#c62828", "bold": True})

        worksheet.set_column(0, 0, 12)
        worksheet.set_column(1, 1, 22)
        worksheet.set_column(2, 2, 16)
        worksheet.set_column(3, 3, 18)
        worksheet.set_column(4, 4, 16)
        worksheet.set_column(5, 5, 26)
        worksheet.set_column(6, 9, 14)

        worksheet.write(0, 0, "Estado de Cuenta", fmt_titulo)
        worksheet.write(1, 0, "%s — Generado: %s" % (datos["cliente"].name or "", datos["generated_at"]), fmt_subtitulo)
        row = 2
        if datos["resumen"]["cantidad_sin_aplicar"]:
            worksheet.write_rich_string(row, 0, fmt_dot, "●", "  Pago no conciliado a ningún cargo (crédito a favor).", fmt_subtitulo)

        row = 3
        encabezados = [
            "Fecha", "Residencia", "Tipo", "Cargo/Pago", "Diario",
            "Referencia Cliente", "Debe", "Haber", "Saldo Acumulado", "Estado",
        ]
        for col, texto in enumerate(encabezados):
            worksheet.write(row, col, texto, fmt_header)
        header_row = row
        row += 1

        for mov in datos["movimientos"]:
            worksheet.write_datetime(row, 0, mov["date"], fmt_fecha) if mov["date"] else worksheet.write(row, 0, "")
            worksheet.write(row, 1, mov["residencia"].name or "")
            worksheet.write(row, 2, mov["tipo_label"])
            ref = mov["move_name"] or mov.get("pago_ref") or ""
            if mov["tipo"] == "Pago" and not mov["aplicado"]:
                worksheet.write_rich_string(row, 3, ref + "  ", fmt_dot, "●")
            else:
                worksheet.write(row, 3, ref)
            worksheet.write(row, 4, mov["journal"].name if mov["journal"] else "")
            worksheet.write(row, 5, mov["referencia_cliente"] or "")
            worksheet.write(row, 6, mov["debe"], fmt_dinero)
            worksheet.write(row, 7, mov["haber"], fmt_dinero)
            worksheet.write(row, 8, mov["saldo_acumulado"], fmt_dinero)
            worksheet.write(row, 9, mov["state"] or "")
            row += 1

        worksheet.freeze_panes(header_row + 1, 0)
        workbook.close()
        buffer.seek(0)

        nombre_cliente = "".join(c for c in (self.cliente_id.name or "Residente") if c not in _INVALID_FILENAME_CHARS)
        filename = "Estado_Cuenta_%s.xlsx" % nombre_cliente
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
