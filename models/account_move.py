# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_MOVE_TYPES_CON_RESIDENCIA = ("out_invoice", "out_refund")

# Contexto que usa internamente el proceso de Cobros Mensuales (ver
# proyecto_cobro_mensual.py: _generar_cargo_residencia) al crear el account.move: en
# ese momento el account.move se crea ANTES que el asovec.proyecto_cobro_mensual_line
# que lo referencia (por eso no puede validarse en el mismo create()), así que ese
# único punto se exime explícitamente de _check_diario_cargo_automatico.
CTX_SKIP_CARGO_AUTOMATICO_CHECK = "iit_asovec_skip_cargo_automatico_check"

# Contexto que usa internamente el proceso de Migración de Deuda (en iit_asogua) al
# crear cargos en un diario marcado 'Cargo Migrado = Si': ese diario está reservado
# para ese proceso y no se puede operar manualmente desde Facturación.
CTX_SKIP_CARGO_MIGRADO_CHECK = "iit_asovec_skip_cargo_migrado_check"


class AccountMove(models.Model):
    _inherit = "account.move"

    residencia_id = fields.Many2one(
        comodel_name="asovec.residencia",
        string="Residencia",
        index=True,
        help="Residencia de la Asociación a la que corresponde este cargo (cobro "
             "mensual o deuda migrada). Permite distinguir cargos de residencias "
             "distintas aunque compartan el mismo cliente.",
    )

    @api.onchange("partner_id", "journal_id")
    def _onchange_partner_id_residencia(self):
        for move in self:
            if move.move_type not in _MOVE_TYPES_CON_RESIDENCIA or not move.journal_id.aso_valida_residencia:
                continue
            residencia = self.env["asovec.residencia"].search(
                [("cliente_id", "=", move.partner_id.id)], limit=1, order="id",
            ) if move.partner_id else self.env["asovec.residencia"]
            move.residencia_id = residencia

    @api.constrains("residencia_id", "partner_id", "move_type", "journal_id")
    def _check_residencia_del_residente(self):
        for move in self:
            if move.move_type not in _MOVE_TYPES_CON_RESIDENCIA or not move.partner_id:
                continue
            if not move.journal_id.aso_valida_residencia:
                continue
            tiene_residencias = self.env["asovec.residencia"].search_count(
                [("cliente_id", "=", move.partner_id.id)],
            )
            if not tiene_residencias:
                # El cliente de esta factura no es un residente conocido (p.ej.
                # facturas a terceros), no aplica la validación.
                continue
            if not move.residencia_id:
                raise ValidationError(_(
                    "Debe indicar la Residencia de este cargo antes de grabarlo."
                ))
            if move.residencia_id.cliente_id != move.partner_id:
                raise ValidationError(_(
                    "La Residencia '%(residencia)s' no pertenece al residente '%(cliente)s'."
                ) % {
                    "residencia": move.residencia_id.display_name,
                    "cliente": move.partner_id.name,
                })

    @api.constrains("journal_id", "move_type")
    def _check_diario_cargo_automatico(self):
        if self.env.context.get(CTX_SKIP_CARGO_AUTOMATICO_CHECK):
            return
        for move in self:
            if move.move_type != "out_invoice" or move.journal_id.aso_cargo_automatico != "Si":
                continue
            tiene_detalle = self.env["asovec.proyecto_cobro_mensual_line"].search_count(
                [("move_id", "=", move.id)],
            )
            if not tiene_detalle:
                raise ValidationError(_(
                    "El diario '%(diario)s' está reservado para los cargos que genera "
                    "automáticamente el proceso de Cobros Mensuales. Esta factura no está "
                    "asociada a ningún detalle de cobro mensual: use otro diario."
                ) % {"diario": move.journal_id.name})

    @api.constrains("journal_id", "move_type")
    def _check_diario_cargo_migrado_reservado(self):
        """Un diario marcado 'Cargo Migrado = Si' solo se puede cargar desde el proceso
        de Migración de Deuda (en iit_asogua, que marca CTX_SKIP_CARGO_MIGRADO_CHECK),
        nunca operando manualmente una factura desde Facturación."""
        if self.env.context.get(CTX_SKIP_CARGO_MIGRADO_CHECK):
            return
        for move in self:
            if move.move_type != "out_invoice" or move.journal_id.aso_cargo_migrado != "Si":
                continue
            raise ValidationError(_(
                "El diario '%(diario)s' está marcado como 'Cargo Migrado': solo se puede "
                "cargar desde el proceso de Migración de Deuda, no operando una factura "
                "manualmente desde Facturación. Use otro diario."
            ) % {"diario": move.journal_id.name})
