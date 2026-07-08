# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .contador import MONTH_SELECTION


class LecturaOperadorWizard(models.TransientModel):
    _name = "asovec.lectura_operador_wizard"
    _description = "Registrar Lectura (Operador de Campo)"

    residencia_id = fields.Many2one(
        "asovec.residencia", string="Residencia", required=True,
        domain=[
            ("no_paga_servicios", "=", False),
            ("sin_contador", "=", False),
            ("activo", "=", True),
        ],
    )
    # Calculados por el onchange de residencia_id, no editables por el usuario. La vista
    # los marca "force_save" para que se guarden aunque sean readonly (si no, Odoo los
    # excluye del create() al ser de solo lectura).
    contador_id = fields.Many2one("asovec.contador", string="Contador", readonly=True)
    mes = fields.Selection(MONTH_SELECTION, string="Mes (sugerido)", readonly=True)
    anio = fields.Integer(string="Año (sugerido)", readonly=True)

    currency_id = fields.Many2one(related="residencia_id.currency_id", readonly=True)

    # Solo informativos, para que el operador confirme que está en la residencia correcta.
    cliente_id = fields.Many2one(related="residencia_id.cliente_id", string="Residente", readonly=True)
    proyecto_aso_id = fields.Many2one(related="residencia_id.proyecto_aso_id", string="Proyecto", readonly=True)
    direccion_real = fields.Char(related="residencia_id.direccion_real", string="Dirección", readonly=True)

    # Se lee en action_guardar para la validación de "no puede ser menor a la anterior".
    lectura_anterior = fields.Float(string="Lectura anterior", readonly=True)
    lectura = fields.Float(string="Lectura actual")
    consumo = fields.Float(string="Consumo", readonly=True)
    metros_extras = fields.Float(string="Exceso (m³)", readonly=True)
    pago_extra = fields.Monetary(string="Pago extra", currency_field="currency_id", readonly=True)
    pago_total = fields.Monetary(string="Pago total", currency_field="currency_id", readonly=True)

    foto = fields.Binary(string="Foto")
    foto_filename = fields.Char(string="Nombre foto")

    def _limpiar_preview(self):
        for rec in self:
            rec.contador_id = False
            rec.mes = False
            rec.anio = False
            rec.lectura_anterior = 0.0
            rec.lectura = 0.0
            rec.consumo = 0.0
            rec.metros_extras = 0.0
            rec.pago_extra = 0.0
            rec.pago_total = 0.0

    @api.onchange("residencia_id")
    def _onchange_residencia_id(self):
        self._limpiar_preview()
        if not self.residencia_id:
            return

        Line = self.env["asovec.contador.lines"]
        contador = self.residencia_id._get_contador_activo()
        if not contador or not contador.active:
            return {
                "warning": {
                    "title": _("Sin contador activo"),
                    "message": _(
                        "Esta residencia no tiene un contador activo. Créelo (y actívelo) "
                        "antes de ingresar lecturas."
                    ),
                }
            }

        self.contador_id = contador
        next_mes, next_anio = Line._next_period_for_contador(contador.id)
        self.mes = next_mes
        self.anio = next_anio

        last = Line._last_mensual(contador.id)
        if last:
            self.lectura_anterior = last.lectura or 0.0
        else:
            ini = Line._get_inicial(contador.id)
            self.lectura_anterior = (ini.lectura or 0.0) if ini else 0.0

        self._recalcular_preview()

    @api.onchange("lectura")
    def _onchange_lectura(self):
        self._recalcular_preview()

    def _recalcular_preview(self):
        Line = self.env["asovec.contador.lines"]
        for rec in self:
            if not rec.contador_id:
                continue
            calc = Line._calcular_campos_linea(
                rec.contador_id, rec.lectura or 0.0, rec.lectura_anterior or 0.0, es_inicial=False
            )
            rec.consumo = calc["consumo"]
            rec.metros_extras = calc["metros_extras"]
            rec.pago_extra = calc["pago_extra"]
            rec.pago_total = calc["pago_total"]

    def action_guardar(self):
        self.ensure_one()
        if not self.contador_id:
            raise UserError(_("Selecciona una residencia con contador activo."))
        if (self.lectura or 0.0) < (self.lectura_anterior or 0.0):
            raise UserError(_(
                "La lectura (%s) no puede ser menor que la lectura anterior (%s)."
            ) % (self.lectura, self.lectura_anterior))

        self.env["asovec.contador.lines"].create({
            "contador_id": self.contador_id.id,
            "mes": self.mes,
            "anio": self.anio,
            "es_inicial": False,
            "lectura": self.lectura,
            "foto": self.foto,
            "foto_filename": self.foto_filename,
        })

        # Reabre un asistente nuevo y vacío para seguir con la siguiente residencia,
        # sin volver a pasar por el listado de residencias.
        return self._action_nuevo_formulario()

    def action_cancelar(self):
        # El "special=cancel" genérico de Odoo se queda pegado aquí: como el botón
        # Guardar ya deja este asistente guardado (con id) antes de fallar la
        # validación dentro de action_guardar, "descartar" no tiene nada que
        # descartar y no navega a ningún lado. Por eso Cancelar siempre reabre un
        # formulario nuevo en blanco, sin importar el estado actual.
        return self._action_nuevo_formulario()

    def _action_nuevo_formulario(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Registrar Lectura"),
            "res_model": "asovec.lectura_operador_wizard",
            "view_mode": "form",
            "views": [(self.env.ref("iit_asovec.view_asovec_lectura_operador_wizard_form").id, "form")],
            "target": "current",
        }
