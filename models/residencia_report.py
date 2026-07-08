# -*- coding: utf-8 -*-
from odoo import models, api, fields


class Residencia(models.Model):
    _inherit = "asovec.residencia"

    def _get_contador_activo(self):
        self.ensure_one()
        # 'contadores_ids' filtra automáticamente los inactivos (campo 'active' del
        # modelo), por lo que hay que buscar con active_test=False para poder llegar
        # al fallback cuando el único contador que existe está inactivo.
        Contador = self.env['asovec.contador'].with_context(active_test=False)
        contador = Contador.search([('residencia_id', '=', self.id), ('active', '=', True)], limit=1)
        if contador:
            return contador
        # fallback: el último si no hay activo
        return Contador.search([('residencia_id', '=', self.id)], order='id desc', limit=1)

    def action_print_estado_cuenta_lecturas(self):
        self.ensure_one()
        return self.env.ref("iit_asovec.action_report_estado_cuenta_residencia_lecturas").report_action(self)


class ReportEstadoCuentaResidenciaLecturas(models.AbstractModel):
    _name = "report.iit_asovec.report_estado_cuenta_residencia_lecturas"
    _description = "Estado de cuenta por Residencia (Lecturas)"

    @api.model
    def _get_report_values(self, docids, data=None):
        residencias = self.env["asovec.residencia"].browse(docids)

        report_docs = []
        fecha_min = fields.Date.from_string("1900-01-01")

        for res in residencias:
            contador = res._get_contador_activo()

            lecturas = (
                contador.line_ids.sorted(
                    lambda l: (l.periodo_date or fecha_min, l.id),
                    reverse=True
                )
                if contador else self.env["asovec.contador.lines"]
            )

            saldo_pendiente = 0.0
            lineas = []
            for l in lecturas:
                monto = l.pago_total or 0.0
                pagado = (l.payment_status_badge in ("paid", "migrado"))
                if not pagado:
                    saldo_pendiente += monto

                lineas.append({
                    "lectura": l,
                    "monto": monto,
                    "pagado": pagado,
                })

            report_docs.append({
                "residencia": res,
                "direccion": res.direccion_real or "",
                "proyecto": res.proyecto_aso_id,
                "contador": contador,
                "lineas": lineas,
                "saldo_pendiente": saldo_pendiente,
                "currency": res.env.company.currency_id,
            })

        return {
            "doc_ids": docids,
            "doc_model": "asovec.residencia",
            "docs": residencias,
            "report_docs": report_docs,
        }
