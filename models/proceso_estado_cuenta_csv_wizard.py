# -*- coding: utf-8 -*-
import base64
import csv
import io

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
        return res

    def _get_direccion(self, residencia, proyecto):
        return " ".join(filter(None, [
            residencia.calle,
            residencia.no_casa,
            proyecto.name,
        ]))

    def _build_rows(self):
        self.ensure_one()
        mes_padded = str(self.mes).zfill(2)

        journal = self.env["account.journal"].search([
            ("aso_cargo", "=", "Si"),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not journal:
            raise UserError(_("No existe un Diario contable con 'aso_cargo = Si'."))

        CobroLine = self.env["asovec.proyecto_cobro_mensual_line"]
        residencias = self.env["asovec.residencia"].search([], order="proyecto_aso_id, name")

        rows = []
        for residencia in residencias:
            proyecto = residencia.proyecto_aso_id

            lineas = CobroLine.search([
                ("residencia_id", "=", residencia.id),
                ("move_id.journal_id", "=", journal.id),
                ("move_id.state", "=", "posted"),
                ("cobro_id.state", "!=", "cancel"),
            ])

            del_mes = lineas.filtered(lambda l: l.month == mes_padded and l.year == self.anio)
            anteriores = lineas - del_mes

            saldo_mes = sum(del_mes.mapped("amount_residual"))
            saldo_anterior = sum(anteriores.mapped("amount_residual"))

            rows.append([
                residencia.name,
                residencia.cliente_id.name or "",
                self._get_direccion(residencia, proyecto),
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
