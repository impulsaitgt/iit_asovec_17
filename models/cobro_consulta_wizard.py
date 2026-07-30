# -*- coding: utf-8 -*-
import base64
import io

import xlsxwriter

from odoo import api, models, fields, _
from odoo.exceptions import UserError

from .contador import MONTH_SELECTION

_INVALID_FILENAME_CHARS = set('\\/:*?"<>|')
_MONTH_LABELS = dict(MONTH_SELECTION)


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

    filtrar_por_periodo = fields.Boolean(
        string="Filtrar por Período",
        default=False,
        help="Por defecto el Estado de Cuenta muestra todo el histórico. Actívelo para "
             "mostrar solo el Mes/Año indicados, con Saldo Inicial (lo acumulado antes "
             "del período) y Saldo Final (al cierre del período).",
    )
    mes_periodo = fields.Selection(
        MONTH_SELECTION, string="Mes",
        default=lambda self: str(fields.Date.context_today(self).month),
        help="Se sugiere el mes actual; cámbielo si necesita otro período. Solo aplica "
             "si 'Filtrar por Período' está activo.",
    )
    anio_periodo = fields.Integer(
        string="Año",
        default=lambda self: fields.Date.context_today(self).year,
    )
    aplicar_periodo_lecturas = fields.Boolean(
        string="Aplicar también al Historial de Lecturas",
        default=False,
        help="Por defecto el Período solo filtra los Movimientos (cargos y pagos); el "
             "Historial de Lecturas sigue mostrando todo el histórico. Actívelo para "
             "que el Historial de Lecturas también se limite al Mes/Año del Período.",
    )

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

    @api.constrains("filtrar_por_periodo", "mes_periodo", "anio_periodo")
    def _check_periodo_completo(self):
        for rec in self:
            if rec.filtrar_por_periodo and not (rec.mes_periodo and rec.anio_periodo):
                raise UserError(_("Para filtrar por Período debe indicar tanto el Mes como el Año."))

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
        fmt_total_label = workbook.add_format({"bold": True, "top": 2})
        fmt_total_dinero = workbook.add_format({"bold": True, "num_format": "#,##0.00", "top": 2})

        tiene_convenio = datos["tiene_convenio"]
        columnas = [("Fecha", 12), ("Residencia", 22), ("Tipo", 16), ("Cargo/Pago", 18), ("Diario", 16)]
        if tiene_convenio:
            columnas.append(("Convenio", 14))
        columnas += [
            ("Referencia Cliente", 26), ("Debe", 14), ("Haber", 14),
            ("Saldo Acumulado", 14), ("Estado", 14),
        ]
        col = {nombre: idx for idx, (nombre, _ancho) in enumerate(columnas)}
        for idx, (_nombre, ancho) in enumerate(columnas):
            worksheet.set_column(idx, idx, ancho)

        worksheet.write(0, 0, "Estado de Cuenta", fmt_titulo)
        worksheet.write(1, 0, "%s — Generado: %s" % (datos["cliente"].name or "", datos["generated_at"]), fmt_subtitulo)
        worksheet.write(2, 0, "Dirección(es): %s" % (datos["direcciones"] or ""), fmt_subtitulo)
        row = 3
        if datos["periodo_activo"]:
            worksheet.write(row, 0, "Período: %s" % datos["periodo_label"], fmt_subtitulo)
            row += 1
        if datos["resumen"]["cantidad_sin_aplicar"]:
            worksheet.write_rich_string(row, 0, fmt_dot, "●", "  Pago no conciliado a ningún cargo (crédito a favor).", fmt_subtitulo)
            row += 1

        for texto, _ancho in columnas:
            worksheet.write(row, col[texto], texto, fmt_header)
        header_row = row
        row += 1

        if datos["periodo_activo"]:
            worksheet.write(row, col["Referencia Cliente"], "Saldo Inicial", fmt_total_label)
            worksheet.write(row, col["Saldo Acumulado"], datos["saldo_inicial"], fmt_total_dinero)
            row += 1

        for mov in datos["movimientos"]:
            worksheet.write_datetime(row, col["Fecha"], mov["date"], fmt_fecha) if mov["date"] else worksheet.write(row, col["Fecha"], "")
            worksheet.write(row, col["Residencia"], mov["residencia"].name or "")
            worksheet.write(row, col["Tipo"], mov["tipo_label"])
            ref = mov["move_name"] or mov.get("pago_ref") or ""
            if mov["tipo"] == "Pago" and not mov["aplicado"]:
                worksheet.write_rich_string(row, col["Cargo/Pago"], ref + "  ", fmt_dot, "●")
            else:
                worksheet.write(row, col["Cargo/Pago"], ref)
            worksheet.write(row, col["Diario"], mov["journal"].name if mov["journal"] else "")
            if tiene_convenio:
                worksheet.write(row, col["Convenio"], mov["convenio"].numero if mov["convenio"] else "")
            worksheet.write(row, col["Referencia Cliente"], mov["referencia_cliente"] or "")
            worksheet.write(row, col["Debe"], mov["debe"], fmt_dinero)
            worksheet.write(row, col["Haber"], mov["haber"], fmt_dinero)
            worksheet.write(row, col["Saldo Acumulado"], mov["saldo_acumulado"], fmt_dinero)
            worksheet.write(row, col["Estado"], mov["state"] or "")
            row += 1

        worksheet.write(row, col["Referencia Cliente"], "Saldo Final" if datos["periodo_activo"] else "Totales", fmt_total_label)
        worksheet.write(row, col["Debe"], datos["resumen"]["total_facturado"], fmt_total_dinero)
        worksheet.write(row, col["Haber"], datos["resumen"]["total_pagado"], fmt_total_dinero)
        worksheet.write(row, col["Saldo Acumulado"], datos["resumen"]["total_saldo"], fmt_total_dinero)

        worksheet.freeze_panes(header_row + 1, 0)

        # --------------------
        # Hoja "Historial de Lecturas": Período, Lectura, Lectura anterior, Consumo,
        # Canon de agua, Exceso (pago extra) y Total, sin Facturación/Pago (es solo
        # consulta de lecturas). Igual orden que en HTML/por-residencia: más reciente
        # arriba, registro inicial siempre de último (ver
        # asovec.contador._historial_lecturas_ordenado).
        # --------------------
        ws2 = workbook.add_worksheet("Historial de Lecturas")
        columnas2 = [
            ("Residencia", 22), ("Período", 16), ("Lectura", 12), ("Lectura anterior", 16),
            ("Consumo", 12), ("Canon de agua", 16), ("Exceso (pago extra)", 18), ("Total", 14),
        ]
        col2 = {nombre: idx for idx, (nombre, _ancho) in enumerate(columnas2)}
        for idx, (_nombre, ancho) in enumerate(columnas2):
            ws2.set_column(idx, idx, ancho)

        ws2.write(0, 0, "Historial de Lecturas", fmt_titulo)
        if datos["lecturas_periodo_activo"]:
            ws2.write(1, 0, "Período: %s" % datos["periodo_label"], fmt_subtitulo)
        row2 = 2
        for texto, _ancho in columnas2:
            ws2.write(row2, col2[texto], texto, fmt_header)
        header_row2 = row2
        row2 += 1

        for bloque in datos["historial_lecturas"]:
            for ln in bloque["lineas"]:
                periodo = "Registro Inicial" if ln.es_inicial else "%s %s" % (_MONTH_LABELS.get(ln.mes, ln.mes or ""), ln.anio or "")
                ws2.write(row2, col2["Residencia"], bloque["residencia"].name or "")
                ws2.write(row2, col2["Período"], periodo)
                ws2.write(row2, col2["Lectura"], ln.lectura or 0.0, fmt_dinero)
                ws2.write(row2, col2["Lectura anterior"], ln.lectura_anterior or 0.0, fmt_dinero)
                ws2.write(row2, col2["Consumo"], ln.consumo or 0.0, fmt_dinero)
                ws2.write(row2, col2["Canon de agua"], ln.base or 0.0, fmt_dinero)
                ws2.write(row2, col2["Exceso (pago extra)"], ln.pago_extra or 0.0, fmt_dinero)
                ws2.write(row2, col2["Total"], ln.pago_total or 0.0, fmt_dinero)
                row2 += 1

        ws2.freeze_panes(header_row2 + 1, 0)

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
