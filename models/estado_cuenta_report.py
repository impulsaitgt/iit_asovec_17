# -*- coding: utf-8 -*-
import base64

from odoo import api, fields, models
from odoo.tools import image_process

LOGO_MAX_HEIGHT = 90


class ReportEstadoCuenta(models.AbstractModel):
    _name = "report.iit_asovec.report_estado_cuenta_document"
    _description = "Estado de Cuenta (documento)"

    def _movimiento_cargo(self, move, origen, residencia, cliente):
        return {
            "date": move.invoice_date or move.date,
            "tipo": "Cargo",
            "origen": origen,
            "residencia": residencia,
            "move": move,
            "move_name": move.name,
            "pago_ref": False,
            "pago_move": False,
            "pago_payment": False,
            "journal": move.journal_id,
            "aso_cargo": move.journal_id.aso_cargo,
            "aso_cargo_automatico": move.journal_id.aso_cargo_automatico,
            "cliente": cliente,
            "currency": move.currency_id,
            "debe": move.amount_total,
            "haber": 0.0,
            "state": move.state,
        }

    def _movimientos_pago(self, move, residencia):
        """Pagos realmente aplicados a `move` (vía conciliación real, igual a lo que
        Odoo muestra en el widget "Payments" de la factura), no un simple total-residual."""
        movimientos = []
        for reconciled in move.sudo()._get_all_reconciled_invoice_partials():
            if reconciled.get("is_exchange"):
                continue
            aml = reconciled["aml"]
            movimientos.append({
                "date": aml.date,
                "tipo": "Pago",
                "origen": "Pago",
                "residencia": residencia,
                "move": move,
                "move_name": move.name,
                "pago_ref": aml.move_id.name,
                "pago_move": aml.move_id,
                "pago_payment": aml.payment_id,
                "journal": aml.journal_id,
                "aso_cargo": False,
                "aso_cargo_automatico": False,
                "cliente": move.partner_id,
                "currency": move.currency_id,
                "debe": 0.0,
                "haber": abs(reconciled["amount"]),
                "state": "posted",
            })
        return movimientos

    def _movimientos_residencia(self, wizard, residencia):
        """Arma el libro de movimientos (cargos y pagos reales) de una residencia,
        ordenados cronológicamente, con saldo acumulado, para poder ver todo el
        historial aunque el saldo final sea cero."""
        entradas = []
        moves_incluidos = self.env["account.move"]

        for line in wizard._get_cobro_lines_residencia(residencia):
            move = line.move_id
            entradas.append(self._movimiento_cargo(move, "Cargo Mensual", residencia, line.cliente_id))
            moves_incluidos |= move

        domain_migradas = [
            ("residencia_id", "=", residencia.id),
            ("state", "=", "posted"),
            ("id", "not in", moves_incluidos.ids),
        ]
        if wizard.solo_residente_actual and wizard.cliente_id:
            domain_migradas.append(("partner_id", "=", wizard.cliente_id.id))
        moves_migrados = self.env["account.move"].search(domain_migradas, order="invoice_date, id")
        for move in moves_migrados:
            entradas.append(self._movimiento_cargo(move, "Deuda Migrada", residencia, move.partner_id))
            moves_incluidos |= move

        for move in moves_incluidos:
            entradas += self._movimientos_pago(move, residencia)

        entradas.sort(key=lambda e: (e["date"] or fields.Date.today(), 0 if e["tipo"] == "Cargo" else 1))

        saldo = 0.0
        for entrada in entradas:
            saldo += entrada["debe"] - entrada["haber"]
            entrada["saldo_acumulado"] = saldo

        return entradas

    @api.model
    def _build_estado_cuenta_data(self, wizard):
        """Arma el libro de movimientos y el resumen del estado de cuenta para el
        wizard. Se comparte entre el reporte HTML, el PDF y la exportación a Excel,
        para que los tres siempre muestren exactamente los mismos números y la misma
        fecha de generación.

        A diferencia de una vista de "un renglón por factura", esto explota cada
        cargo (Cargo Mensual o Deuda Migrada) y cada pago realmente conciliado contra
        él en movimientos separados con saldo acumulado, para poder revisar todo el
        historial de un residente aunque su saldo final sea cero."""
        wizard.ensure_one()
        residencias = wizard.residencia_ids

        movimientos = []
        for residencia in residencias:
            movimientos += self._movimientos_residencia(wizard, residencia)

        cargos = [m for m in movimientos if m["tipo"] == "Cargo"]
        resumen = {
            "cantidad_residencias": len(residencias),
            "cantidad_cargos": len(cargos),
            "total_facturado": sum(m["debe"] for m in movimientos),
            "total_pagado": sum(m["haber"] for m in movimientos),
            "total_saldo": sum(m["debe"] - m["haber"] for m in movimientos),
            "cantidad_asociacion": len([m for m in cargos if m["aso_cargo"] == "Si"]),
            "cantidad_automatico": len([m for m in cargos if m["aso_cargo_automatico"] == "Si"]),
            "cantidad_migrada": len([m for m in cargos if m["origen"] == "Deuda Migrada"]),
        }

        currency = (movimientos[0]["currency"] if movimientos else False) or wizard.env.company.currency_id
        generated_at_dt = fields.Datetime.context_timestamp(wizard, fields.Datetime.now())

        return {
            "proyecto": residencias[:1].proyecto_aso_id,
            "residencias": residencias,
            "cliente": wizard.cliente_id,
            "solo_residente_actual": wizard.solo_residente_actual,
            "generated_at": generated_at_dt.strftime("%d/%m/%Y %H:%M"),
            "movimientos": movimientos,
            "resumen": resumen,
            "currency": currency,
        }

    @api.model
    def _get_report_values(self, docids, data=None):
        wizard = self.env["asovec.cobro_mensual_consulta_wizard"].browse(docids)
        wizard.ensure_one()
        datos = self._build_estado_cuenta_data(wizard)

        company = self.env.company
        logo_b64 = False
        if company.logo:
            resized = image_process(base64.b64decode(company.logo), size=(0, LOGO_MAX_HEIGHT))
            if resized:
                logo_b64 = base64.b64encode(resized).decode()

        return {
            "doc_ids": docids,
            "doc_model": "asovec.cobro_mensual_consulta_wizard",
            "docs": wizard,
            "company": company,
            "logo_b64": logo_b64,
            **datos,
        }


class ReportEstadoCuentaPdf(models.AbstractModel):
    _name = "report.iit_asovec.estado_cuenta_pdf"
    _description = "Estado de Cuenta (PDF)"

    @api.model
    def _get_report_values(self, docids, data=None):
        return self.env["report.iit_asovec.report_estado_cuenta_document"]._get_report_values(docids, data=data)
