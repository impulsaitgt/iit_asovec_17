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
        ],
    )
    # Calculados por el onchange de residencia_id, no editables por el usuario. La vista
    # los marca "force_save" para que se guarden aunque sean readonly (si no, Odoo los
    # excluye del create() al ser de solo lectura).
    contador_id = fields.Many2one("asovec.contador", string="Contador", readonly=True)
    mes = fields.Selection(MONTH_SELECTION, string="Mes (sugerido)", readonly=True)
    anio = fields.Integer(string="Año (sugerido)", readonly=True)

    # True cuando la residencia está inactiva o su contador está inactivo: en ese caso
    # se muestra un aviso y se bloquea el ingreso de una nueva lectura.
    es_inactivo = fields.Boolean(string="Inactivo", readonly=True)

    # True cuando se está corrigiendo la última lectura ya registrada (en vez de
    # ingresar una nueva). `line_id` guarda cuál es esa lectura para poder actualizarla
    # en `action_guardar` en vez de crear una nueva.
    modo_correccion = fields.Boolean(string="Corrigiendo lectura existente", readonly=True)
    line_id = fields.Many2one("asovec.contador.lines", string="Lectura a corregir", readonly=True)

    # Controla si se muestra el botón "Corregir última lectura": solo si existe una
    # lectura mensual y su cargo todavía está en borrador (no posteado).
    ultima_en_borrador = fields.Boolean(readonly=True)

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
            rec.es_inactivo = False
            rec.modo_correccion = False
            rec.line_id = False
            rec.ultima_en_borrador = False

    @api.onchange("residencia_id")
    def _onchange_residencia_id(self):
        self._limpiar_preview()
        if not self.residencia_id:
            return

        contador = self.residencia_id._get_contador_activo()
        if not contador:
            return {
                "warning": {
                    "title": _("Sin contador"),
                    "message": _(
                        "Esta residencia no tiene ningún contador registrado. Créelo (y "
                        "actívelo) antes de ingresar lecturas."
                    ),
                }
            }

        self.contador_id = contador
        self.es_inactivo = (not contador.active) or (not self.residencia_id.activo)
        self._cargar_modo_nueva()

        # Si se viene del Listado de Residencias por Proyecto y esta residencia ya
        # tenía lectura ese período, entra directo en modo corrección (en vez de
        # proponer el siguiente período y obligar a dar clic en "Corregir última
        # lectura"). Solo aplica con este contexto puntual: entrando directo a
        # "Registrar Lectura" el comportamiento normal no cambia.
        if self.env.context.get("listado_forzar_correccion") and self.ultima_en_borrador and not self.es_inactivo:
            self.action_corregir_ultima()

    @api.onchange("lectura")
    def _onchange_lectura(self):
        self._recalcular_preview()

    def _cargar_modo_nueva(self):
        """Prepara el formulario para ingresar una lectura nueva (período siguiente al
        último registrado), descartando cualquier corrección en curso."""
        self.ensure_one()
        Line = self.env["asovec.contador.lines"]

        self.modo_correccion = False
        self.line_id = False
        self.foto = False
        self.foto_filename = False

        next_mes, next_anio = Line._next_period_for_contador(self.contador_id.id)
        self.mes = next_mes
        self.anio = next_anio

        last = Line._last_mensual(self.contador_id.id)
        if last:
            self.lectura_anterior = last.lectura or 0.0
        else:
            ini = Line._get_inicial(self.contador_id.id)
            self.lectura_anterior = (ini.lectura or 0.0) if ini else 0.0

        self.ultima_en_borrador = bool(last) and last.invoice_status_badge == "borrador"

        self.lectura = 0.0
        self._recalcular_preview()

    def action_corregir_ultima(self):
        """Carga la última lectura mensual ya registrada de este contador para poder
        corregirla, en vez de crear una nueva. Solo se permite si su cargo todavía no
        está facturado (posteado); si lo está, `action_guardar` tampoco podría
        regenerarlo y quedaría inconsistente con la factura ya emitida."""
        self.ensure_one()
        if not self.contador_id:
            return

        Line = self.env["asovec.contador.lines"]
        last = Line._last_mensual(self.contador_id.id)
        if not last:
            raise UserError(_(
                "Este contador todavía no tiene ninguna lectura mensual registrada para corregir."
            ))
        if last.invoice_status_badge != "borrador":
            raise UserError(_(
                "No se puede corregir: el cargo de %s/%s ya no está en borrador (posteado, "
                "facturado o migrado)."
            ) % (last.mes, last.anio))

        anterior = Line._last_mensual(self.contador_id.id, exclude_id=last.id)
        if anterior:
            lectura_anterior = anterior.lectura or 0.0
        else:
            ini = Line._get_inicial(self.contador_id.id)
            lectura_anterior = (ini.lectura or 0.0) if ini else 0.0

        self.modo_correccion = True
        self.line_id = last
        self.mes = last.mes
        self.anio = last.anio
        self.lectura_anterior = lectura_anterior
        self.lectura = last.lectura
        self.foto = last.foto
        self.foto_filename = last.foto_filename
        self._recalcular_preview()

    def action_volver_nueva(self):
        self.ensure_one()
        if self.contador_id:
            self._cargar_modo_nueva()

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
        if self.es_inactivo:
            raise UserError(_(
                "No se puede registrar la lectura: la residencia o el contador está inactivo."
            ))
        if not self.modo_correccion and self.ultima_en_borrador:
            raise UserError(_(
                "No se puede registrar una nueva lectura: el cargo del mes anterior "
                "todavía está en borrador (sin confirmar/postear)."
            ))
        if (self.lectura or 0.0) < (self.lectura_anterior or 0.0):
            raise UserError(_(
                "La lectura (%s) no puede ser menor que la lectura anterior (%s)."
            ) % (self.lectura, self.lectura_anterior))

        if self.modo_correccion:
            if not self.line_id:
                raise UserError(_("No hay ninguna lectura seleccionada para corregir."))
            self.line_id.write({
                "lectura": self.lectura,
                "foto": self.foto,
                "foto_filename": self.foto_filename,
            })
        else:
            self.env["asovec.contador.lines"].create({
                "contador_id": self.contador_id.id,
                "mes": self.mes,
                "anio": self.anio,
                "es_inicial": False,
                "lectura": self.lectura,
                "foto": self.foto,
                "foto_filename": self.foto_filename,
            })

        # Si se llegó aquí desde el Listado de Residencias por Proyecto, se vuelve a
        # ese mismo listado (ya actualizado); si no, se abre un asistente nuevo y
        # vacío para seguir con la siguiente residencia a mano.
        return self._volver_a_listado_o_nuevo()

    def action_cancelar(self):
        # El "special=cancel" genérico de Odoo se queda pegado aquí: como el botón
        # Guardar ya deja este asistente guardado (con id) antes de fallar la
        # validación dentro de action_guardar, "descartar" no tiene nada que
        # descartar y no navega a ningún lado. Por eso Cancelar siempre reabre algo,
        # sin importar el estado actual.
        return self._volver_a_listado_o_nuevo()

    def _volver_a_listado_o_nuevo(self):
        """Si este wizard se abrió desde el Listado de Residencias por Proyecto
        (contexto `listado_proyecto_id`/`listado_mes`/`listado_anio`), vuelve a ese
        mismo listado recalculado; si no, se comporta como siempre (formulario nuevo
        en blanco)."""
        ctx = self.env.context
        proyecto_id = ctx.get("listado_proyecto_id")
        mes = ctx.get("listado_mes")
        anio = ctx.get("listado_anio")
        if proyecto_id and mes and anio:
            listado = self.env["asovec.lectura_listado_wizard"].create({
                "proyecto_aso_id": proyecto_id,
                "mes": mes,
                "anio": anio,
            })
            return listado.action_buscar()
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
