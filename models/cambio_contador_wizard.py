# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CambioContadorWizard(models.TransientModel):
    _name = "asovec.cambio_contador_wizard"
    _description = "Cambio de Contador"

    residencia_id = fields.Many2one(
        "asovec.residencia", string="Residencia", required=True,
        domain=[
            ("no_paga_servicios", "=", False),
            ("sin_contador", "=", False),
        ],
    )

    # Solo informativos, para que quien hace el cambio confirme que está en la
    # residencia correcta antes de dar de baja el contador actual.
    cliente_id = fields.Many2one("res.partner", string="Residente", related="residencia_id.cliente_id", readonly=True)
    proyecto_aso_id = fields.Many2one("asovec.proyecto_aso", string="Proyecto", related="residencia_id.proyecto_aso_id", readonly=True)
    direccion_real = fields.Char(string="Dirección", related="residencia_id.direccion_real", readonly=True)

    # Contador activo actual, cargado por el onchange de residencia_id. Se guarda
    # (readonly + force_save en la vista) para poder comparar en action_confirmar que
    # sigue siendo el mismo contador que cuando se abrió el asistente, por si alguien
    # más lo cambió mientras tanto.
    contador_actual_id = fields.Many2one("asovec.contador", string="Contador actual", readonly=True)
    tiene_contador_actual = fields.Boolean(string="Tiene contador actual", readonly=True)
    ultima_lectura = fields.Float(related="contador_actual_id.ultima_lectura", string="Última lectura registrada", readonly=True)
    ultimo_consumo = fields.Float(related="contador_actual_id.ultimo_consumo", string="Último consumo", readonly=True)
    ultima_fecha = fields.Date(related="contador_actual_id.ultima_fecha", string="Último período leído", readonly=True)

    contador_nuevo_nombre = fields.Char(string="Número/Nombre de contador nuevo")
    lectura_inicial = fields.Float(string="Lectura inicial", default=0.0)

    @api.onchange("residencia_id")
    def _onchange_residencia_id(self):
        self.contador_actual_id = False
        self.tiene_contador_actual = False
        self.contador_nuevo_nombre = False
        self.lectura_inicial = 0.0
        if not self.residencia_id:
            return
        self.contador_actual_id = self.env["asovec.contador"].search([
            ("residencia_id", "=", self.residencia_id.id),
            ("active", "=", True),
        ], limit=1)
        self.tiene_contador_actual = bool(self.contador_actual_id)

    def action_confirmar(self):
        self.ensure_one()

        if self.residencia_id.no_paga_servicios or self.residencia_id.sin_contador:
            raise UserError(_(
                "Esta residencia no usa contador (No paga servicios / Sin contador)."
            ))
        if not self.contador_nuevo_nombre:
            raise UserError(_("Indique el número/nombre del contador nuevo."))
        if self.lectura_inicial < 0:
            raise UserError(_("La lectura inicial no puede ser negativa."))

        Contador = self.env["asovec.contador"]
        contador_actual = Contador.search([
            ("residencia_id", "=", self.residencia_id.id),
            ("active", "=", True),
        ], limit=1)
        if contador_actual != self.contador_actual_id:
            raise UserError(_(
                "El contador activo de esta residencia cambió desde que se abrió este "
                "asistente. Vuelva a abrirlo para continuar con la información actual."
            ))

        if contador_actual:
            contador_actual.write({"active": False})

        contador_nuevo = Contador.create({
            "residencia_id": self.residencia_id.id,
            "name": self.contador_nuevo_nombre,
            "active": True,
        })

        self.env["asovec.contador.lines"].create({
            "contador_id": contador_nuevo.id,
            "es_inicial": True,
            "lectura": self.lectura_inicial,
        })

        return {
            "type": "ir.actions.act_window",
            "name": _("Contador"),
            "res_model": "asovec.contador",
            "view_mode": "form",
            "res_id": contador_nuevo.id,
            "target": "current",
        }
