# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ConvenioWizard(models.TransientModel):
    _name = "asovec.convenio_wizard"
    _description = "Crear Cargo de Convenio"

    residencia_id = fields.Many2one(
        "asovec.residencia", string="Residencia", required=True,
        domain=[("cliente_id", "!=", False)],
    )
    cliente_id = fields.Many2one(
        "res.partner", string="Residente", related="residencia_id.cliente_id", readonly=True,
    )
    proyecto_aso_id = fields.Many2one(
        "asovec.proyecto_aso", string="Proyecto", related="residencia_id.proyecto_aso_id", readonly=True,
    )
    direccion = fields.Char(string="Dirección", related="residencia_id.direccion_real", readonly=True)
    currency_id = fields.Many2one(
        "res.currency", string="Moneda", related="residencia_id.currency_id", readonly=True,
    )
    monto = fields.Monetary(string="Monto", required=True, currency_field="currency_id")
    fecha = fields.Date(string="Fecha", required=True, default=fields.Date.context_today)

    def _get_journal_convenio(self):
        journal = self.env["account.journal"].search([
            ("aso_convenio", "=", "Si"),
            ("company_id", "=", self.env.company.id),
        ])
        if not journal:
            raise UserError(_("No existe un Diario contable marcado como 'Convenio' para esta compañía."))
        if len(journal) > 1:
            raise UserError(_(
                "Existe más de un Diario contable marcado como 'Convenio': %s. Solo debe haber uno."
            ) % ", ".join(journal.mapped("name")))
        return journal

    def _get_servicio_convenio(self):
        servicio = self.env["product.template"].search([("aso_convenio", "=", True)])
        if not servicio:
            raise UserError(_("No existe un Servicio de Asociación marcado como 'Servicio de Convenio'."))
        if len(servicio) > 1:
            raise UserError(_(
                "Existe más de un Servicio marcado como 'Servicio de Convenio': %s. Solo debe haber uno."
            ) % ", ".join(servicio.mapped("name")))
        if not servicio.product_variant_id:
            raise UserError(_("El Servicio de Convenio no tiene una variante de producto válida."))
        return servicio

    def action_crear_cargo(self):
        self.ensure_one()

        if not self.residencia_id.cliente_id:
            raise UserError(_(
                "La residencia '%s' no tiene un residente (contacto) asignado."
            ) % self.residencia_id.display_name)

        if self.monto <= 0:
            raise UserError(_("El monto debe ser mayor a cero."))

        journal = self._get_journal_convenio()
        servicio = self._get_servicio_convenio()

        pendiente = self.env["account.move"]._get_convenio_pendiente(self.residencia_id)
        if pendiente:
            raise UserError(_(
                "La Residencia '%(residencia)s' ya tiene un cargo de Convenio pendiente de pago "
                "(%(cargo)s). No se puede crear otro hasta liquidarlo."
            ) % {"residencia": self.residencia_id.display_name, "cargo": pendiente.name})

        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "company_id": self.env.company.id,
            "journal_id": journal.id,
            "partner_id": self.residencia_id.cliente_id.id,
            "residencia_id": self.residencia_id.id,
            "invoice_date": self.fecha,
            "invoice_line_ids": [(0, 0, {
                "product_id": servicio.product_variant_id.id,
                "name": servicio.name,
                "quantity": 1.0,
                "price_unit": self.monto,
                "tax_ids": [(6, 0, [])],
            })],
        })

        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": move.id,
            "target": "current",
        }
