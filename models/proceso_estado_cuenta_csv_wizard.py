# -*- coding: utf-8 -*-
import base64
import csv
import io
from collections import defaultdict

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .contador import MONTH_SELECTION, mes_anio_anterior


def _format_monto(value):
    """Replica el formato del archivo del banco: sin separador de miles, sin ceros
    decimales innecesarios (305.00 -> '305', 336.50 -> '336.5')."""
    value = round(value or 0.0, 2)
    if value == int(value):
        return str(int(value))
    return ("%.2f" % value).rstrip("0").rstrip(".")


class ProcesoEstadoCuentaCsvWizard(models.TransientModel):
    _name = "asovec.proceso_estado_cuenta_csv_wizard"
    _description = "Generar CSV de Estado de Cuenta (Banco) por Mes"

    mes = fields.Selection(MONTH_SELECTION, string="Mes", required=True)
    anio = fields.Integer(string="Año", required=True)
    journal_ids = fields.Many2many(
        "account.journal", string="Diarios", required=True,
        help="Diarios a considerar para calcular la deuda (mes y anteriores). Por "
             "defecto sugiere los diarios 'Cargo Automatico Asociacion = Si' y 'Cargo "
             "Migrado = Si', pero se puede cambiar o agregar otros.",
    )
    file_data = fields.Binary(string="Archivo CSV", readonly=True)
    file_name = fields.Char(string="Nombre de archivo", readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        mes, anio = mes_anio_anterior(fields.Date.context_today(self))
        if "mes" in fields_list and not res.get("mes"):
            res["mes"] = mes
        if "anio" in fields_list and not res.get("anio"):
            res["anio"] = anio
        if "journal_ids" in fields_list and not res.get("journal_ids"):
            journal_aso = self.env["account.journal"].search([
                "&", ("company_id", "=", self.env.company.id),
                "|", ("aso_cargo_migrado", "=", "Si"), ("aso_cargo_automatico", "=", "Si"),
            ])
            if journal_aso:
                res["journal_ids"] = [(6, 0, journal_aso.ids)]
        return res

    def _get_direccion(self, residencia):
        return residencia.direccion_real

    def _get_moves_migrados_por_residencia(self):
        """Facturas de deuda migrada (cargadas con 'Cargar Deudas/Facturas Anteriores'),
        agrupadas por residencia (campo `residencia_id` del cargo). No están ligadas a
        una residencia mediante proyecto_cobro_mensual_line (son facturas sueltas), así
        que se usa ese campo directo en vez de agrupar por cliente: un mismo cliente
        puede ser dueño de varias residencias, y agrupar por cliente mezclaba la deuda
        de una residencia con la de otra."""
        Move = self.env["account.move"]
        moves = Move.search([
            ("journal_id", "in", self.journal_ids.ids),
            ("state", "=", "posted"),
            ("invoice_line_ids.product_id.product_tmpl_id.tipo_servicio_aso_id.aso_migrado", "=", True),
        ])
        por_residencia = defaultdict(lambda: Move)
        for move in moves:
            if move.residencia_id:
                por_residencia[move.residencia_id.id] |= move
        return por_residencia

    def _build_rows(self):
        self.ensure_one()
        if not self.journal_ids:
            raise UserError(_("Debes seleccionar al menos un Diario."))

        mes_padded = str(self.mes).zfill(2)
        mes_int = int(self.mes)
        fecha_mes = fields.Date.from_string("%s-%02d-01" % (self.anio, mes_int))

        CobroLine = self.env["asovec.proyecto_cobro_mensual_line"]
        residencias = self.env["asovec.residencia"].search([], order="proyecto_aso_id, name")
        migradas_por_residencia = self._get_moves_migrados_por_residencia()

        rows = []
        for residencia in residencias:
            lineas = CobroLine.search([
                ("residencia_id", "=", residencia.id),
                ("move_id.journal_id", "in", self.journal_ids.ids),
                ("move_id.state", "=", "posted"),
                ("cobro_id.state", "!=", "cancel"),
            ])

            del_mes = lineas.filtered(lambda l: l.month == mes_padded and l.year == self.anio)
            anteriores = lineas.filtered(lambda l: (l.year, int(l.month)) < (self.anio, mes_int))

            saldo_mes = sum(del_mes.mapped("amount_residual"))
            saldo_anterior = sum(anteriores.mapped("amount_residual"))

            moves_migrados = migradas_por_residencia.get(residencia.id)
            if moves_migrados:
                del_mes_migrado = moves_migrados.filtered(lambda m: m.invoice_date == fecha_mes)
                anteriores_migrado = moves_migrados.filtered(lambda m: m.invoice_date and m.invoice_date < fecha_mes)
                saldo_mes += sum(del_mes_migrado.mapped("amount_residual"))
                saldo_anterior += sum(anteriores_migrado.mapped("amount_residual"))

            rows.append([
                residencia.name,
                residencia.cliente_id.name or "",
                self._get_direccion(residencia),
                _format_monto(saldo_mes),
                _format_monto(saldo_anterior),
                "0",
            ])

        return rows

    def action_generar(self):
        self.ensure_one()

        rows = self._build_rows()

        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=",", lineterminator="\r\n")
        for row in rows:
            writer.writerow([str(v).replace(",", " ") for v in row])

        csv_bytes = buffer.getvalue().encode("cp1252", errors="replace")

        mes_label = dict(MONTH_SELECTION).get(self.mes, self.mes)
        self.write({
            "file_data": base64.b64encode(csv_bytes),
            "file_name": "Estado_Cuenta_%s_%s.csv" % (mes_label, self.anio),
        })

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }
