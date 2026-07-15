# -*- coding: utf-8 -*-
import base64

from odoo import api, fields, models
from odoo.tools import image_process

LOGO_MAX_HEIGHT = 90


class ReportEstadoCuenta(models.AbstractModel):
    _name = "report.iit_asovec.report_estado_cuenta_document"
    _description = "Estado de Cuenta (documento)"

    def _tipo_label_cargo(self, journal):
        if journal.aso_cargo_migrado == "Si":
            return "Cargo Migrado"
        if journal.aso_cargo_automatico == "Si":
            return "Cargo Automático"
        return "Cargo"

    def _movimiento_cargo(self, move, residencia, cliente):
        return {
            "date": move.invoice_date or move.date,
            "datetime": move.create_date,
            "tipo": "Cargo",
            "tipo_label": self._tipo_label_cargo(move.journal_id),
            "residencia": residencia,
            "move": move,
            "move_name": move.name,
            "referencia_cliente": move.ref or "",
            "pago_ref": False,
            "pago_move": False,
            "pago_payment": False,
            "journal": move.journal_id,
            "aso_cargo": "Si" if (move.journal_id.aso_cargo_migrado == "Si" or move.journal_id.aso_cargo_automatico == "Si") else "No",
            "aso_cargo_automatico": move.journal_id.aso_cargo_automatico,
            "cliente": cliente,
            "currency": move.currency_id,
            "debe": move.amount_total,
            "haber": 0.0,
            "state": move.state,
            "aplicado": True,
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
                "datetime": aml.create_date,
                "tipo": "Pago",
                "tipo_label": "Pago",
                "residencia": residencia,
                "move": move,
                "move_name": move.name,
                "referencia_cliente": aml.payment_id.payment_reference or aml.move_id.ref or "",
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
                "aplicado": True,
            })
        return movimientos

    def _movimientos_credito_sin_aplicar(self, wizard, residencia):
        """Recibos/pagos ya posteados que no están conciliados contra ninguna
        factura (crédito a favor del residente): p.ej. se operó el recibo del
        banco pero todavía no se le asoció ningún cargo. No hay un campo que
        ligue el pago a una residencia específica (solo al cliente), así que el
        llamador debe incluir esto una sola vez por reporte, no por residencia."""
        cliente = wizard.cliente_id
        if not cliente:
            return []
        pagos = self.env["account.payment"].search([
            ("partner_id", "=", cliente.id),
            ("payment_type", "=", "inbound"),
            ("state", "=", "posted"),
            ("is_reconciled", "=", False),
        ])
        movimientos = []
        for pago in pagos:
            movimientos.append({
                "date": pago.date,
                "datetime": pago.create_date,
                "tipo": "Pago",
                "tipo_label": "Pago",
                "residencia": residencia,
                "move": False,
                "move_name": "",
                "referencia_cliente": pago.payment_reference or "",
                "pago_ref": pago.name,
                "pago_move": pago.move_id,
                "pago_payment": pago,
                "journal": pago.journal_id,
                "aso_cargo": False,
                "aso_cargo_automatico": False,
                "cliente": cliente,
                "currency": pago.currency_id,
                "debe": 0.0,
                "haber": pago.amount,
                "state": "posted",
                "aplicado": False,
            })
        return movimientos

    def _movimientos_residencia(self, wizard, residencia, incluir_creditos_sueltos=False):
        """Arma el libro de movimientos (cargos y pagos reales) de una residencia,
        ordenados cronológicamente (fecha y, dentro del mismo día, por hora real de
        creación), con saldo acumulado, para poder ver todo el historial aunque el
        saldo final sea cero."""
        entradas = []
        moves_incluidos = self.env["account.move"]

        for line in wizard._get_cobro_lines_residencia(residencia):
            move = line.move_id
            entradas.append(self._movimiento_cargo(move, residencia, line.cliente_id))
            moves_incluidos |= move

        # Solo facturas reales (no notas de crédito): una nota de crédito no es un
        # cargo nuevo, es un abono/reversión que ya aparece como "Pago" al conciliarse
        # contra la factura que afecta (más abajo, vía _movimientos_pago).
        domain_migradas = [
            ("residencia_id", "=", residencia.id),
            ("state", "=", "posted"),
            ("move_type", "=", "out_invoice"),
            ("id", "not in", moves_incluidos.ids),
        ]
        if wizard.solo_residente_actual and wizard.cliente_id:
            domain_migradas.append(("partner_id", "=", wizard.cliente_id.id))
        moves_migrados = self.env["account.move"].search(domain_migradas, order="invoice_date, id")
        for move in moves_migrados:
            entradas.append(self._movimiento_cargo(move, residencia, move.partner_id))
            moves_incluidos |= move

        for move in moves_incluidos:
            entradas += self._movimientos_pago(move, residencia)

        if incluir_creditos_sueltos:
            entradas += self._movimientos_credito_sin_aplicar(wizard, residencia)

        entradas.sort(key=lambda e: (e["date"] or fields.Date.today(), e["datetime"] or fields.Datetime.now()))

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
        for index, residencia in enumerate(residencias):
            movimientos += self._movimientos_residencia(wizard, residencia, incluir_creditos_sueltos=(index == 0))

        cargos = [m for m in movimientos if m["tipo"] == "Cargo"]
        resumen = {
            "cantidad_residencias": len(residencias),
            "cantidad_cargos": len(cargos),
            "total_facturado": sum(m["debe"] for m in movimientos),
            "total_pagado": sum(m["haber"] for m in movimientos),
            "total_saldo": sum(m["debe"] - m["haber"] for m in movimientos),
            "cantidad_asociacion": len([m for m in cargos if m["aso_cargo"] == "Si"]),
            "cantidad_automatico": len([m for m in cargos if m["aso_cargo_automatico"] == "Si"]),
            "cantidad_sin_aplicar": len([m for m in movimientos if m["tipo"] == "Pago" and not m["aplicado"]]),
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
