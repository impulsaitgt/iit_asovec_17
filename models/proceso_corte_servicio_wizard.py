# -*- coding: utf-8 -*-
import base64
import io
from datetime import date, timedelta

import xlsxwriter

from odoo import api, models, fields, _
from odoo.exceptions import UserError

from .contador import MONTH_SELECTION

_INVALID_FILENAME_CHARS = set('\\/:*?"<>|')


def _sumar_dias_habiles(fecha, dias):
    """Suma `dias` días hábiles (lunes a viernes) a `fecha`. No considera feriados:
    el módulo no tiene hoy ningún calendario de días feriados configurado."""
    actual = fecha
    restantes = dias
    while restantes > 0:
        actual += timedelta(days=1)
        if actual.weekday() < 5:  # 0=lunes ... 6=domingo
            restantes -= 1
    return actual


class ProcesoCorteServicioWizard(models.TransientModel):
    _name = "asovec.proceso_corte_servicio_wizard"
    _description = "Notificación de Corte de Servicio de Agua"

    proyecto_aso_id = fields.Many2one(
        "asovec.proyecto_aso", string="Proyecto",
        help="Déjelo vacío para incluir todos los proyectos.",
    )
    mes = fields.Selection(MONTH_SELECTION, string="Mes", required=True)
    anio = fields.Integer(string="Año", required=True)
    meses_atraso = fields.Integer(
        string="Meses de atraso mínimo", required=True, default=2,
        help="Solo se listan residencias cuya deuda impaga viene acumulándose desde "
             "hace al menos esta cantidad de meses, contados hacia atrás desde el mes "
             "seleccionado (usando la fecha de creación de cada cargo, no su período "
             "contable ni la fecha de pago).",
    )
    dias_habiles_corte = fields.Integer(
        string="Días hábiles de anticipación", required=True, default=5,
        help="Días hábiles (lunes a viernes) entre la fecha de impresión y la fecha en "
             "que se efectuará el corte de servicio.",
    )
    fecha_impresion = fields.Date(string="Fecha de impresión", required=True, default=fields.Date.context_today)
    fecha_corte = fields.Date(string="Fecha de corte", compute="_compute_fecha_corte")

    line_ids = fields.One2many(
        "asovec.proceso_corte_servicio_wizard_line", "wizard_id", string="Residencias",
    )
    line_count = fields.Integer(string="Residencias encontradas", compute="_compute_line_count")

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

    @api.depends("fecha_impresion", "dias_habiles_corte")
    def _compute_fecha_corte(self):
        for rec in self:
            if rec.fecha_impresion and rec.dias_habiles_corte:
                rec.fecha_corte = _sumar_dias_habiles(rec.fecha_impresion, rec.dias_habiles_corte)
            else:
                rec.fecha_corte = False

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def _reload_form(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }

    # -------------------------
    # Deuda migrada (facturas sueltas, sin línea de cobro mensual)
    # -------------------------
    def _get_moves_migrados(self, residencias):
        """Facturas de "Deuda Migrada" (cargadas con el proceso de Migración de Deuda):
        no tienen asovec.proyecto_cobro_mensual_line (son facturas sueltas), así que no
        las ve la búsqueda normal por línea. Mismo criterio que ya usa
        proceso_estado_cuenta_csv_wizard._get_moves_migrados_por_residencia."""
        return self.env["account.move"].search([
            ("residencia_id", "in", residencias.ids),
            ("state", "=", "posted"),
            ("amount_residual", ">", 0),
            ("invoice_line_ids.product_id.product_tmpl_id.tipo_servicio_aso_id.aso_migrado", "=", True),
        ])

    # -------------------------
    # Buscar residencias atrasadas
    # -------------------------
    def action_buscar(self):
        self.ensure_one()
        if self.meses_atraso < 1:
            raise UserError(_("Los meses de atraso mínimo deben ser al menos 1."))
        if not self.mes or not self.anio:
            raise UserError(_("Seleccione Mes y Año."))

        domain = [("no_paga_servicios", "=", False)]
        if self.proyecto_aso_id:
            domain.append(("proyecto_aso_id", "=", self.proyecto_aso_id.id))
        residencias = self.env["asovec.residencia"].search(domain)

        self.line_ids.unlink()
        if not residencias:
            return self._reload_form()

        anio_ref, mes_ref = int(self.anio), int(self.mes)
        primer_dia_mes_ref = date(anio_ref, mes_ref, 1)
        limite = primer_dia_mes_ref.strftime("%Y-%m-%d 00:00:00")

        # Cargos normales (Cobros Mensuales): el mes se determina por create_date (la
        # fecha real de creación del cargo en el sistema), no por su período contable.
        lineas_cobro = self.env["asovec.proyecto_cobro_mensual_line"].search([
            ("residencia_id", "in", residencias.ids),
            ("move_id.state", "=", "posted"),
            ("amount_balance", ">", 0),
            ("create_date", "<", limite),
        ])

        # Deuda migrada: no tiene línea de cobro mensual, así que create_date no sirve
        # para ubicarla en el mes correcto (todo un lote de migración se crea el mismo
        # día, aunque represente meses distintos). Para esta sí se usa invoice_date, la
        # fecha que se asignó manualmente a cada mes histórico al migrarlo.
        moves_migrados = self._get_moves_migrados(residencias)
        moves_migrados = moves_migrados.filtered(
            lambda m: m.invoice_date and m.invoice_date < primer_dia_mes_ref
        )

        por_residencia = {}
        for linea in lineas_cobro:
            por_residencia.setdefault(linea.residencia_id.id, []).append(
                (linea.create_date.year, linea.create_date.month, linea.amount_balance)
            )
        for move in moves_migrados:
            por_residencia.setdefault(move.residencia_id.id, []).append(
                (move.invoice_date.year, move.invoice_date.month, move.amount_residual)
            )

        meses_nombre = dict(MONTH_SELECTION)
        vals_list = []
        for residencia_id, periodos_residencia in por_residencia.items():
            periodos = sorted({(y, m) for (y, m, _monto) in periodos_residencia})
            anio_mas_antiguo, mes_mas_antiguo = periodos[0]
            atraso = (anio_ref * 12 + mes_ref) - (anio_mas_antiguo * 12 + mes_mas_antiguo)
            if atraso < self.meses_atraso:
                continue

            monto_total = sum(monto for (_y, _m, monto) in periodos_residencia)
            meses_detalle = ", ".join(
                "%s %s" % (meses_nombre.get(str(m), m), y) for (y, m) in periodos
            )

            vals_list.append({
                "wizard_id": self.id,
                "residencia_id": residencia_id,
                "meses_atraso": atraso,
                "monto_atraso": monto_total,
                "meses_detalle": meses_detalle,
                "seleccionado": True,
            })

        if vals_list:
            self.env["asovec.proceso_corte_servicio_wizard_line"].create(vals_list)

        return self._reload_form()

    def action_marcar_todos(self):
        self.ensure_one()
        self.line_ids.write({"seleccionado": True})
        return self._reload_form()

    def action_desmarcar_todos(self):
        self.ensure_one()
        self.line_ids.write({"seleccionado": False})
        return self._reload_form()

    # -------------------------
    # Excel (agrupado por proyecto)
    # -------------------------
    def action_generar_excel(self):
        self.ensure_one()
        lineas = self.line_ids.filtered("seleccionado")
        if not lineas:
            raise UserError(_("Seleccione al menos una residencia para generar el Excel."))

        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
        worksheet = workbook.add_worksheet("Cortes de Servicio")

        fmt_titulo = workbook.add_format({"bold": True, "font_size": 14})
        fmt_subtitulo = workbook.add_format({"italic": True, "font_color": "#666666"})
        fmt_proyecto = workbook.add_format({"bold": True, "bg_color": "#dddddd"})
        fmt_header = workbook.add_format({
            "bold": True, "bg_color": "#009999", "font_color": "#ffffff", "border": 1,
        })
        fmt_dinero = workbook.add_format({"num_format": "#,##0.00"})

        columnas = [
            ("Lote", 14), ("Propietario", 32), ("Dirección", 26),
            ("Atraso (meses)", 14), ("Monto a Cancelar", 16), ("Fecha", 14), ("Hora", 10),
        ]
        col = {nombre: idx for idx, (nombre, _ancho) in enumerate(columnas)}
        for idx, (_nombre, ancho) in enumerate(columnas):
            worksheet.set_column(idx, idx, ancho)

        proyecto_label = self.proyecto_aso_id.name if self.proyecto_aso_id else "Todos los proyectos"
        worksheet.write(0, 0, "Cortes de Servicio de Agua", fmt_titulo)
        worksheet.write(1, 0, "Proyecto: %s — Valuado al: %s" % (proyecto_label, self.fecha_impresion), fmt_subtitulo)

        lineas_por_proyecto = {}
        orden_proyectos = []
        for linea in lineas.sorted(lambda l: (l.proyecto_aso_id.name or "", l.residencia_id.name or "")):
            if linea.proyecto_aso_id.id not in lineas_por_proyecto:
                orden_proyectos.append(linea.proyecto_aso_id)
            lineas_por_proyecto.setdefault(linea.proyecto_aso_id.id, []).append(linea)

        row = 3
        for proyecto in orden_proyectos:
            worksheet.merge_range(row, 0, row, len(columnas) - 1, proyecto.name or "", fmt_proyecto)
            row += 1
            for idx, (nombre, _ancho) in enumerate(columnas):
                worksheet.write(row, idx, nombre, fmt_header)
            row += 1
            for linea in lineas_por_proyecto[proyecto.id]:
                worksheet.write(row, col["Lote"], linea.residencia_id.name or "")
                worksheet.write(row, col["Propietario"], linea.cliente_id.name or "")
                worksheet.write(row, col["Dirección"], linea.direccion_real or "")
                worksheet.write(row, col["Atraso (meses)"], linea.meses_atraso)
                worksheet.write(row, col["Monto a Cancelar"], linea.monto_atraso, fmt_dinero)
                worksheet.write(row, col["Fecha"], "")
                worksheet.write(row, col["Hora"], "")
                row += 1
            row += 1

        workbook.close()
        buffer.seek(0)

        nombre_proyecto = "".join(c for c in (proyecto_label or "Proyectos") if c not in _INVALID_FILENAME_CHARS)
        filename = "Cortes_Servicio_%s.xlsx" % nombre_proyecto
        self.write({
            "file_data": base64.b64encode(buffer.read()),
            "file_name": filename,
        })

        return self._reload_form()

    # -------------------------
    # PDF (cartas de aviso, 2 por hoja)
    # -------------------------
    def action_generar_pdf(self):
        self.ensure_one()
        lineas = self.line_ids.filtered("seleccionado")
        if not lineas:
            raise UserError(_("Seleccione al menos una residencia para generar el PDF."))
        return self.env.ref("iit_asovec.action_report_corte_servicio_notificacion").report_action(lineas, data={})


class ProcesoCorteServicioWizardLine(models.TransientModel):
    _name = "asovec.proceso_corte_servicio_wizard_line"
    _description = "Línea de Notificación de Corte (residencia con atraso)"
    _order = "proyecto_aso_id, residencia_id"

    wizard_id = fields.Many2one(
        "asovec.proceso_corte_servicio_wizard", string="Wizard", required=True, ondelete="cascade",
    )
    residencia_id = fields.Many2one("asovec.residencia", string="Residencia", required=True, readonly=True)
    proyecto_aso_id = fields.Many2one(
        related="residencia_id.proyecto_aso_id", string="Proyecto", store=True, readonly=True,
    )
    cliente_id = fields.Many2one(
        related="residencia_id.cliente_id", string="Propietario", store=True, readonly=True,
    )
    direccion_real = fields.Char(
        related="residencia_id.direccion_real", string="Dirección", store=True, readonly=True,
    )
    currency_id = fields.Many2one(related="residencia_id.currency_id", readonly=True)

    meses_atraso = fields.Integer(string="Atraso (meses)", readonly=True)
    monto_atraso = fields.Monetary(string="Monto a Cancelar", currency_field="currency_id", readonly=True)
    meses_detalle = fields.Char(string="Meses adeudados", readonly=True)

    fecha_impresion = fields.Date(related="wizard_id.fecha_impresion", readonly=True)
    fecha_corte = fields.Date(related="wizard_id.fecha_corte", readonly=True)
    dias_habiles_corte = fields.Integer(related="wizard_id.dias_habiles_corte", readonly=True)

    seleccionado = fields.Boolean(string="Imprimir", default=True)
