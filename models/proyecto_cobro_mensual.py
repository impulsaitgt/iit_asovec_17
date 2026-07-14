# -*- coding: utf-8 -*-
import base64
import csv
import io

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from .contador import mes_anio_anterior


class ProyectoCobroMensual(models.Model):
    _name = "asovec.proyecto_cobro_mensual"
    _description = "Cobro mensual por Proyecto"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "year desc, month desc, id desc"

    name = fields.Char(string="Referencia", compute="_compute_name", store=True)
    proyecto_aso_id = fields.Many2one(
        comodel_name="asovec.proyecto_aso",
        string="Proyecto",
        required=True,
        index=True,
        tracking=True,
    )

    month = fields.Selection(
        selection=[
            ("01", "Enero"), ("02", "Febrero"), ("03", "Marzo"), ("04", "Abril"),
            ("05", "Mayo"), ("06", "Junio"), ("07", "Julio"), ("08", "Agosto"),
            ("09", "Septiembre"), ("10", "Octubre"), ("11", "Noviembre"), ("12", "Diciembre"),
        ],
        string="Mes",
        required=True,
        default=lambda self: mes_anio_anterior(fields.Date.today())[0].zfill(2),
        tracking=True,
    )
    year = fields.Integer(
        string="Año",
        required=True,
        default=lambda self: mes_anio_anterior(fields.Date.today())[1],
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Borrador"),
            ("posted", "Publicado"),
            ("cancel", "Cancelado"),
        ],
        string="Estado",
        default="draft",
        required=True,
        tracking=True,
    )

    fecha_confirmacion = fields.Date(
        string="Fecha de Confirmación",
        readonly=True,
        tracking=True,
        help="Fecha en la que se confirmó (posteó) este cobro mensual.",
    )

    line_ids = fields.One2many(
        comodel_name="asovec.proyecto_cobro_mensual_line",
        inverse_name="cobro_id",
        string="Detalle por Residencia",
        copy=False,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )

    total_to_charge = fields.Monetary(
        string="Total a cobrar",
        compute="_compute_totals",
        currency_field="currency_id",
        store=True,
        tracking=True,
    )

    # ✅ NUEVO: total pagado REAL (sumando lo pagado de las líneas)
    total_paid = fields.Monetary(
        string="Total pagado",
        compute="_compute_paid",
        currency_field="currency_id",
        store=True,
        tracking=True,
    )

    total_balance = fields.Monetary(
        string="Saldo",
        compute="_compute_balance",
        currency_field="currency_id",
        store=True,
        tracking=True,
    )

    # --------------------
    # Indicadores de avance (encabezado)
    # --------------------
    total_residencias = fields.Integer(string="Total residencias", compute="_compute_indicadores")
    residencias_con_lectura = fields.Integer(string="Con lectura", compute="_compute_indicadores")
    pct_con_lectura = fields.Float(string="% Con lectura", compute="_compute_indicadores")
    residencias_sin_lectura = fields.Integer(string="Sin lectura", compute="_compute_residencias_sin_lectura")
    pct_sin_lectura = fields.Float(string="% Sin lectura", compute="_compute_residencias_sin_lectura")
    residencias_inactivas = fields.Integer(string="Inactivas", compute="_compute_indicadores")
    pct_inactivas = fields.Float(string="% Inactivas", compute="_compute_indicadores")
    residencias_cargo_generado = fields.Integer(string="Cargos generados", compute="_compute_indicadores")
    pct_cargo_generado = fields.Float(string="% Cargos generados", compute="_compute_indicadores")
    # Distinto de "residencias_cargo_generado" (que exige un move_id real): una
    # residencia con lectura pero sin nada que cobrar ese mes (p. ej. proyecto que
    # solo cobra cuando hay exceso, y no hubo) también queda "resuelta" sin factura.
    # Usa el mismo criterio que "Completar Faltantes" (_residencias_pendientes_generar)
    # para no duplicar la definición de qué falta.
    residencias_pendientes = fields.Integer(string="Pendientes por generar", compute="_compute_indicadores")

    # Uso interno de "Regenerar Cargos": recuerda hasta qué residencia (por id) ya se
    # regeneró en la tanda en curso, para que el siguiente click continúe justo donde
    # se quedó sin repetir ni saltarse ninguna. Se reinicia a -1 (no 0: comparar un
    # Many2one con 0 en un domain de Odoo NO se comporta como comparación numérica
    # normal -devuelve vacío siempre-, así que -1 es el valor real de "sin cursor").
    regenerar_cargos_cursor = fields.Integer(string="Cursor de regeneración", default=-1)

    # --------------------
    # Leyenda de progreso (para el botón Confirmar): la operación se considera
    # completa cuando ya no queda ninguna residencia pendiente por generar.
    # --------------------
    progreso_label = fields.Char(string="Progreso", compute="_compute_progreso")
    progreso_tipo = fields.Selection(
        [("danger", "Danger"), ("success", "Success")],
        string="Tipo de progreso", compute="_compute_progreso",
    )

    @api.depends("state", "residencias_pendientes")
    def _compute_progreso(self):
        for rec in self:
            faltan = rec.residencias_pendientes or 0
            if rec.state == "posted":
                rec.progreso_label = _("Completo")
                rec.progreso_tipo = "success"
            elif faltan > 0:
                rec.progreso_label = _("%s Residencias sin información") % faltan
                rec.progreso_tipo = "danger"
            else:
                rec.progreso_label = _("Total de Residencias con información, puedes confirmar")
                rec.progreso_tipo = "success"

    def init(self):
        # Índice único parcial: solo cuando state != 'cancel'
        self._cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                asovec_cobro_uniq_proj_month_year_not_cancel
            ON asovec_proyecto_cobro_mensual (proyecto_aso_id, month, year)
            WHERE state != 'cancel';
        """)

    @api.depends("proyecto_aso_id", "month", "year")
    def _compute_name(self):
        for rec in self:
            if rec.proyecto_aso_id and rec.month and rec.year:
                rec.name = f"{rec.proyecto_aso_id.display_name} - {rec.month}/{rec.year}"
            else:
                rec.name = "Nuevo cobro mensual"

    @api.depends("line_ids.amount_total")
    def _compute_totals(self):
        for rec in self:
            rec.total_to_charge = sum(rec.line_ids.mapped("amount_total"))

    # ✅ reemplaza al dummy
    @api.depends("line_ids.amount_paid")
    def _compute_paid(self):
        for rec in self:
            rec.total_paid = sum(rec.line_ids.mapped("amount_paid"))

    @api.depends("total_to_charge", "total_paid")
    def _compute_balance(self):
        for rec in self:
            rec.total_balance = (rec.total_to_charge or 0.0) - (rec.total_paid or 0.0)

    # --------------------
    # Indicadores de avance (encabezado)
    # --------------------
    def _residencias_scope(self):
        """Residencias que cuentan para este cobro mensual: las del proyecto que no
        estén marcadas 'No paga servicios' (mismo criterio que `action_generate`)."""
        self.ensure_one()
        if not self.proyecto_aso_id:
            return self.env["asovec.residencia"]
        return self.env["asovec.residencia"].search([
            ("proyecto_aso_id", "=", self.proyecto_aso_id.id),
            ("no_paga_servicios", "=", False),
        ])

    def _residencias_con_lectura_ids(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.con_lectura == "Lectura Valida")
        return lines.mapped("residencia_id")

    @api.depends(
        "proyecto_aso_id", "line_ids.con_lectura", "line_ids.move_id",
        "line_ids.move_id.state", "line_ids.residencia_id",
    )
    def _compute_indicadores(self):
        for rec in self:
            residencias = rec._residencias_scope()
            total = len(residencias)

            inactivas = residencias.filtered(lambda r: not r.activo)
            activas = residencias - inactivas

            con_lectura = rec._residencias_con_lectura_ids() & activas

            cargo_generado = rec.line_ids.filtered(lambda l: l.move_id).mapped("residencia_id") & residencias

            rec.total_residencias = total
            rec.residencias_con_lectura = len(con_lectura)
            rec.residencias_inactivas = len(inactivas)
            rec.residencias_cargo_generado = len(cargo_generado)
            rec.residencias_pendientes = len(rec._residencias_pendientes_generar())

            total_activas = len(activas)
            rec.pct_con_lectura = (len(con_lectura) / total_activas) if total_activas else 0.0
            rec.pct_inactivas = (len(inactivas) / total) if total else 0.0
            rec.pct_cargo_generado = (len(cargo_generado) / total) if total else 0.0

    @api.depends("state", "proyecto_aso_id", "line_ids.con_lectura", "line_ids.residencia_id")
    def _compute_residencias_sin_lectura(self):
        """Separado de _compute_indicadores a propósito: una vez posteado o
        cancelado, 'sin lectura' ya no aporta nada (el ciclo quedó cerrado) y
        calcularlo de todas formas sería costoso para una lista con muchos cobros
        mensuales (columna "Lecturas pendientes"). Por eso corta ANTES de tocar
        residencias en vez de solo poner el resultado en cero al final."""
        for rec in self:
            if rec.state != "draft":
                rec.residencias_sin_lectura = 0
                rec.pct_sin_lectura = 0.0
                continue
            residencias = rec._residencias_scope()
            activas = residencias.filtered(lambda r: r.activo)
            con_lectura = rec._residencias_con_lectura_ids() & activas
            sin_lectura = activas - con_lectura
            rec.residencias_sin_lectura = len(sin_lectura)
            total_activas = len(activas)
            rec.pct_sin_lectura = (len(sin_lectura) / total_activas) if total_activas else 0.0

    def _action_ver_residencias(self, residencias, nombre):
        return {
            "type": "ir.actions.act_window",
            "name": nombre,
            "res_model": "asovec.residencia",
            "view_mode": "tree,form",
            "domain": [("id", "in", residencias.ids)],
        }

    def action_ver_residencias_total(self):
        self.ensure_one()
        return self._action_ver_residencias(self._residencias_scope(), _("Residencias del proyecto"))

    def action_ver_residencias_con_lectura(self):
        self.ensure_one()
        residencias = self._residencias_con_lectura_ids() & self._residencias_scope()
        return self._action_ver_residencias(residencias, _("Residencias con lectura"))

    def action_ver_residencias_sin_lectura(self):
        self.ensure_one()
        residencias = self._residencias_scope()
        activas = residencias.filtered(lambda r: r.activo)
        sin_lectura = activas - self._residencias_con_lectura_ids()
        return self._action_ver_residencias(sin_lectura, _("Residencias sin lectura este mes"))

    def action_ver_residencias_inactivas(self):
        self.ensure_one()
        inactivas = self._residencias_scope().filtered(lambda r: not r.activo)
        return self._action_ver_residencias(inactivas, _("Residencias/Contadores inactivos"))

    def action_ver_cargos_generados(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Cargos generados"),
            "res_model": "asovec.proyecto_cobro_mensual_line",
            "view_mode": "tree,form",
            "domain": [("id", "in", self.line_ids.filtered(lambda l: l.move_id).ids)],
        }

    def action_refrescar(self):
        """Vuelve a abrir este mismo registro (recalcula indicadores y estados de las
        líneas) sin recargar toda la página del navegador."""
        self.ensure_one()
        return self._reabrir_form_action()

    def action_exportar_csv(self):
        """Exporta a CSV las residencias CON LECTURA VÁLIDA este período (una fila por
        residencia/contador), con los datos calculados de la lectura y el importe de
        cada servicio automático como columna, para que se pueda revisar antes de
        confirmar."""
        self.ensure_one()
        return self._exportar_csv_categoria("Lectura Valida", "Lecturas_Validas")

    def action_exportar_csv_inactivas(self):
        """Exporta a CSV las residencias/contadores inactivos de este proyecto, para
        que se pueda revisar si alguna debe reactivarse."""
        self.ensure_one()
        return self._exportar_csv_categoria("Inactivo", "Lecturas_Inactivas")

    def action_exportar_csv_sin_lectura(self):
        """Exporta a CSV las residencias activas que todavía no tienen lectura este
        período, para que se pueda ver qué falta por recibir."""
        self.ensure_one()
        return self._exportar_csv_categoria("Sin Lectura", "Lecturas_SinLectura")

    def _exportar_csv_categoria(self, categoria, nombre_archivo):
        self.ensure_one()

        Line = self.env["asovec.proyecto_cobro_mensual_line"]
        residencias = self._residencias_scope()
        rows = [r for r in Line._lecturas_rows(residencias, self.month, self.year) if r[3] == categoria]
        if not rows:
            raise UserError(_("No hay residencias en esa categoría para %s.") % self.name)

        servicios = Line._csv_servicios()
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(Line._csv_header(servicios))
        for residencia, lectura, move, con_lectura, amount_total, move_state, payment_state in rows:
            writer.writerow(Line._csv_row(
                residencia, lectura, move, con_lectura, amount_total, move_state, payment_state, servicios,
            ))

        csv_data = ("﻿" + buffer.getvalue()).encode("utf-8")
        attachment = self.env["ir.attachment"].create({
            "name": f"{nombre_archivo}_{self.name}.csv",
            "type": "binary",
            "datas": base64.b64encode(csv_data),
            "mimetype": "text/csv",
        })
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    # --------------------
    # Helpers de generación de cargos (compartidos con la creación de lecturas)
    # --------------------
    @api.model
    def _get_or_create_cobro(self, proyecto, mes, anio):
        """Busca el cobro mensual (no cancelado) de ese proyecto/mes/año; si no existe, lo crea
        en borrador. `mes` puede venir como '1'..'12' (formato de asovec.contador.lines)."""
        mes_padded = str(mes or "").zfill(2)
        cobro = self.search([
            ("proyecto_aso_id", "=", proyecto.id),
            ("month", "=", mes_padded),
            ("year", "=", anio),
            ("state", "!=", "cancel"),
        ], limit=1)
        if not cobro:
            cobro = self.create({
                "proyecto_aso_id": proyecto.id,
                "month": mes_padded,
                "year": anio,
            })
        return cobro

    def _get_journal_cargo(self):
        self.ensure_one()
        journal = self.env["account.journal"].search(
            [("aso_cargo", "=", "Si"), ("company_id", "=", self.company_id.id)],
            limit=1,
        )
        if not journal:
            raise UserError(_("No existe un Diario contable con 'aso_cargo = Si'."))
        return journal

    def _get_servicios_automaticos(self):
        servicios = self.env["product.template"].search(
            [("aso_es_servicio_aso", "=", True), ("aso_automatico", "=", True), ("aso_activo", "=", True)]
        )
        if not servicios:
            raise UserError(_("No existen productos marcados como 'Servicio de Asociación'."))
        return servicios

    def _get_productos_especiales(self):
        """Busca una sola vez los productos de agua base/exceso/inactivo, para no repetir
        la misma búsqueda por cada residencia (antes se buscaban de nuevo en cada llamada)."""
        ProductTemplate = self.env["product.template"]

        base = ProductTemplate.search([("aso_agua_base", "=", True)], limit=1)
        if not base or not base.product_variant_id:
            raise UserError(_("No existe un producto marcado como 'Servicio Agua Base'."))

        exceso = ProductTemplate.search([("aso_agua_exceso", "=", True)], limit=1)
        if not exceso or not exceso.product_variant_id:
            raise UserError(_("No existe un producto marcado como 'Servicio Agua Exceso'."))

        inactivo = ProductTemplate.search([("aso_agua_inactivo", "=", True)], limit=1)
        if not inactivo or not inactivo.product_variant_id:
            raise UserError(_("No existe un producto marcado como 'Servicio Agua Inactivo'."))

        return {"base": base, "exceso": exceso, "inactivo": inactivo}

    def _cuenta_override_tipo_servicio(self, tipo_servicio_aso, proyecto_aso):
        """Cuenta contable configurada como excepción para este tipo de servicio en este
        proyecto (asovec.tipo_servicio_aso.proyecto.cuenta_contable_id). Si no hay
        configuración para este proyecto, o no se marcó cuenta, devuelve un recordset
        vacío: en ese caso se deja el vals de la línea sin 'account_id' y Odoo calcula
        la cuenta como de costumbre a partir del producto."""
        detalle = tipo_servicio_aso.proyecto_ids.filtered(
            lambda d: d.proyecto_aso_id.id == proyecto_aso.id
        )
        return detalle[:1].cuenta_contable_id

    def _build_invoice_lines_residencia(self, residencia, servicios, lectura, productos_especiales=None):
        """Devuelve (invoice_lines, con_lectura) para una residencia, igual a la lógica
        original de action_generate."""
        ResidenciaLines = self.env["asovec.residencia.lines"]
        productos_especiales = productos_especiales or self._get_productos_especiales()

        invoice_lines = []
        # "Sin contador": solo debe generarse la cuota de contador inactivo, sin los
        # servicios automáticos (basura, mantenimiento, etc.).
        servicios = servicios if not residencia.sin_contador else self.env["product.template"]
        for t in servicios:
            product = t.product_variant_id
            if not product:
                continue

            if not residencia.activo and not t.tipo_servicio_aso_id.aso_cobra_inactivas:
                # Este tipo de servicio no se cobra para residencias inactivas.
                continue

            detalle_proyecto = t.tipo_servicio_aso_id.proyecto_ids.filtered(
                lambda d: d.proyecto_aso_id.id == residencia.proyecto_aso_id.id
            )

            servicio_especial = ResidenciaLines.search([
                ("residencia_id", "=", residencia.id), ("producto_id", "=", t.id)
            ])
            if servicio_especial:
                precio = servicio_especial.precio
            else:
                if not detalle_proyecto:
                    # No aplica a este proyecto: no hay precio configurado para él.
                    continue
                precio = detalle_proyecto[0].precio

            if precio > 0:
                vals_line = {
                    "product_id": product.id,
                    "name": t.name,
                    "quantity": 1.0,
                    "price_unit": precio,
                    "tax_ids": [(6, 0, [])],   # sin impuestos
                }
                cuenta = detalle_proyecto[:1].cuenta_contable_id
                if cuenta:
                    vals_line["account_id"] = cuenta.id
                invoice_lines.append((0, 0, vals_line))

        if not residencia.activo:
            # Cuota para contadores inactivos
            con_lectura = "Inactivo"
            servicio = productos_especiales["inactivo"]
            vals_line_inactivo = {
                "product_id": servicio.product_variant_id.id,
                "name": servicio.name,
                "quantity": 1.0,
                "price_unit": residencia.proyecto_aso_id.cobro_inactivas,
                "tax_ids": [(6, 0, [])],   # sin impuestos
            }
            cuenta = self._cuenta_override_tipo_servicio(servicio.tipo_servicio_aso_id, residencia.proyecto_aso_id)
            if cuenta:
                vals_line_inactivo["account_id"] = cuenta.id
            invoice_lines.append((0, 0, vals_line_inactivo))
        else:
            con_lectura = "Lectura Valida" if lectura else "Sin Lectura"

            # Cuota base para contadores (se omite si es cero, p.ej. proyectos que solo
            # cobran cuando hay exceso). Si no hay lectura este mes, se usa el "Canon de
            # agua propio" de la residencia si está marcado, o si no el del proyecto.
            if lectura:
                cobro_base = lectura.base
            elif residencia.cobro_base_especial:
                cobro_base = residencia.cobro_base_especial_valor
            else:
                cobro_base = residencia.proyecto_aso_id.cobro_base
            base_generada = cobro_base > 0
            if base_generada:
                servicio = productos_especiales["base"]
                vals_line = {
                    "product_id": servicio.product_variant_id.id,
                    "name": servicio.name,
                    "quantity": 1.0,
                    "price_unit": cobro_base,
                    "tax_ids": [(6, 0, [])],   # sin impuestos
                }
                if lectura:
                    vals_line["contador_line_id"] = lectura.id
                cuenta = self._cuenta_override_tipo_servicio(servicio.tipo_servicio_aso_id, residencia.proyecto_aso_id)
                if cuenta:
                    vals_line["account_id"] = cuenta.id
                invoice_lines.append((0, 0, vals_line))

            # Pago extra para contadores
            cobro_exceso = lectura.pago_extra if lectura else 0
            if cobro_exceso > 0:
                servicio = productos_especiales["exceso"]
                vals_line_exceso = {
                    "product_id": servicio.product_variant_id.id,
                    "name": servicio.name,
                    "quantity": 1.0,
                    "price_unit": cobro_exceso,
                    "tax_ids": [(6, 0, [])],   # sin impuestos
                }
                if lectura and not base_generada:
                    # La cuota base no generó línea: enlazar la lectura aquí para que
                    # el seguimiento de facturación/pago siga funcionando.
                    vals_line_exceso["contador_line_id"] = lectura.id
                cuenta = self._cuenta_override_tipo_servicio(servicio.tipo_servicio_aso_id, residencia.proyecto_aso_id)
                if cuenta:
                    vals_line_exceso["account_id"] = cuenta.id
                invoice_lines.append((0, 0, vals_line_exceso))

        return invoice_lines, con_lectura

    def _generar_cargo_residencia(self, residencia, lectura=None, journal=None, servicios=None, productos_especiales=None):
        """Crea (o recrea) el cargo en borrador de una residencia dentro de este cobro mensual.

        Si ya existe un cargo posteado para esa residencia, lanza error (no se puede regenerar).
        Si existe uno en borrador, se borra y se vuelve a crear con los valores actuales.
        """
        self.ensure_one()

        if not residencia.cliente_id:
            raise UserError(_(
                "La residencia '%s' no tiene un cliente (partner_id) asignado."
            ) % residencia.display_name)

        journal = journal or self._get_journal_cargo()
        servicios = servicios or self._get_servicios_automaticos()
        productos_especiales = productos_especiales or self._get_productos_especiales()

        existing_line = self.line_ids.filtered(lambda l: l.residencia_id == residencia)
        if existing_line:
            move = existing_line.move_id
            if move and move.state == "posted":
                raise UserError(_(
                    "Ya existe un cargo posteado (%s) para la residencia '%s' en %s/%s. "
                    "No se puede regenerar."
                ) % (move.name, residencia.display_name, self.month, self.year))
            # En borrador o cancelado: se puede borrar y recrear sin problema.
            existing_line.unlink()
            if move:
                move.unlink()

        if lectura:
            # Antes de generar el cargo, refrescar el cálculo de la lectura con el
            # precio VIGENTE del proyecto, por si cambió desde que se guardó la
            # lectura (evita que "Completar Faltantes" facture con un precio viejo).
            lectura._refrescar_calculo_con_precio_actual()

        invoice_lines, con_lectura = self._build_invoice_lines_residencia(
            residencia, servicios, lectura, productos_especiales=productos_especiales
        )

        if not invoice_lines:
            # No hay nada que cobrar este período (por ejemplo, proyectos que solo
            # cobran cuando hay exceso y esta residencia no tuvo exceso). Se deja
            # constancia con una línea sin cargo asociado, para que no quede
            # "pendiente" indefinidamente en próximas corridas de este mismo mes.
            self.env["asovec.proyecto_cobro_mensual_line"].create({
                "cobro_id": self.id,
                "residencia_id": residencia.id,
                "con_lectura": con_lectura,
                "contador_line_id": lectura.id if lectura else False,
            })
            return False

        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "company_id": self.company_id.id,
            "journal_id": journal.id,
            "partner_id": residencia.cliente_id.id,
            "residencia_id": residencia.id,
            "invoice_date": fields.Date.context_today(self),
            "invoice_origin": self.name or "",
            "ref": f"{self.name or ''} - {residencia.display_name}",
            "invoice_line_ids": invoice_lines,
        })

        self.env["asovec.proyecto_cobro_mensual_line"].create({
            "cobro_id": self.id,
            "residencia_id": residencia.id,
            "move_id": move.id,
            "con_lectura": con_lectura,
            "amount_total": move.amount_total,
            "contador_line_id": lectura.id if lectura else False,
        })

        return move

    # --------------------
    # Acciones
    # --------------------
    # Generar en un solo click TODAS las residencias de un proyecto grande puede exceder
    # el tiempo límite de una petición web (los commits intermedios no evitan que la
    # petición completa se corte a la mitad). Por eso cada click de "Completar Faltantes"
    # procesa como máximo un lote de este tamaño y devuelve una notificación con el
    # avance: el usuario simplemente vuelve a presionar el botón hasta terminar, sin que
    # nunca se muestre un error de tiempo agotado.
    _GENERATE_CHUNK_SIZE = 150

    def _residencias_pendientes_generar(self, solo_inactivas=False):
        """Residencias del proyecto que todavía no tienen cargo, o cuyo cargo quedó
        cancelado (regenerable). Las que ya tienen un cargo en borrador o posteado se
        excluyen: un borrador ya generado cuenta como "hecho" para este botón (si cambia
        una lectura, el cargo se regenera solo al guardarla, sin necesidad de este
        proceso), así cada click avanza sobre residencias distintas en vez de repetir
        siempre las mismas.

        Con `solo_inactivas=True` (usado por "Completar Inactivas") se limita el mismo
        criterio a las residencias inactivas del proyecto."""
        self.ensure_one()
        Residencia = self.env["asovec.residencia"]
        residencias = Residencia.search([
            ("proyecto_aso_id", "=", self.proyecto_aso_id.id),
            ("no_paga_servicios", "=", False),
        ], order="id")
        if solo_inactivas:
            residencias = residencias.filtered(lambda r: not r.activo)
        existentes = {l.residencia_id.id: l for l in self.line_ids}

        pendientes = Residencia
        for r in residencias:
            line = existentes.get(r.id)
            if not line:
                pendientes |= r
            elif line.move_id and line.move_id.state == "cancel":
                pendientes |= r
        return pendientes

    def action_generate(self):
        """Genera el cargo de un lote acotado de residencias del proyecto que todavía no lo
        tengan (o que sigan en borrador/cancelado, por si hubo cambios de precios/lecturas).
        Si alguna del lote ya tiene un cargo posteado con otro problema, se detiene con
        error. Devuelve una notificación indicando cuántas quedan pendientes; hay que
        volver a presionar el botón hasta que no quede ninguna."""
        self.ensure_one()
        self._check_puede_generar()
        return self._generar_lote(self._residencias_pendientes_generar())

    def action_generate_inactivas(self):
        """Igual que "Completar Faltantes" (mismo motor, misma lógica de lotes/errores),
        pero limitado solo a las residencias inactivas pendientes del proyecto."""
        self.ensure_one()
        self._check_puede_generar()
        return self._generar_lote(self._residencias_pendientes_generar(solo_inactivas=True))

    def _check_puede_generar(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Solo puedes generar en estado Borrador."))
        if not self.proyecto_aso_id:
            raise UserError(_("Debes seleccionar un Proyecto."))

    def _generar_lote(self, pendientes):
        """Genera el cargo de un lote acotado (`_GENERATE_CHUNK_SIZE`) de `pendientes`.
        Cuerpo compartido por action_generate y action_generate_inactivas: cuáles
        residencias entran en `pendientes` es lo único que cambia entre ambos botones."""
        self.ensure_one()
        total_pendientes = len(pendientes)

        if not total_pendientes:
            self.message_post(body=_("No hay residencias pendientes por generar."))
            return self._reabrir_form_action()

        lote = pendientes[: self._GENERATE_CHUNK_SIZE]

        journal = self._get_journal_cargo()
        servicios = self._get_servicios_automaticos()
        productos_especiales = self._get_productos_especiales()
        mes_plano = str(int(self.month))

        lecturas = self.env["asovec.contador.lines"].search([
            ("residencia_id", "in", lote.ids),
            ("anio", "=", self.year),
            ("mes", "=", mes_plano),
            ("es_inicial", "=", False),
        ])
        lectura_por_residencia = {l.residencia_id.id: l for l in lecturas}

        generados = 0
        try:
            for r in lote:
                self._generar_cargo_residencia(
                    r,
                    lectura=lectura_por_residencia.get(r.id),
                    journal=journal,
                    servicios=servicios,
                    productos_especiales=productos_especiales,
                )
                generados += 1
        except Exception as e:
            self.env.cr.commit()
            raise UserError(_(
                "Se generaron %s residencias antes de encontrar un error (había %s "
                "pendientes en total). Lo ya generado queda guardado: corrige el problema "
                "y vuelve a presionar el botón para continuar con el resto.\n\nDetalle: %s"
            ) % (generados, total_pendientes, str(e)))

        self.env.cr.commit()

        faltan = total_pendientes - generados
        if faltan > 0:
            message = _(
                "Se generaron %s de %s residencias pendientes. Faltan %s: vuelve a "
                "presionar el botón para continuar."
            ) % (generados, total_pendientes, faltan)
        else:
            message = _("Se generaron las %s residencias pendientes. ¡Completo!") % generados

        self.message_post(body=message)
        return self._reabrir_form_action()

    # ~80s observados para 266 residencias en pruebas reales (~0.3s c/u). Con 150 por
    # tanda quedan ~45-50s por click, con margen bajo el límite de 120s del servidor
    # (limit_time_real) incluso para proyectos grandes (568 residencias = 4 clicks).
    _REGENERAR_CARGOS_CHUNK_SIZE = 150

    def action_regenerar_cargos(self):
        """Regenera (borra y vuelve a crear) el cargo de las residencias de este cobro
        mensual, con la configuración vigente (precios, cuentas contables por
        proyecto, etc.) - útil después de cambiar esa configuración para que los
        cargos ya generados la reflejen, sin corregir residencia por residencia.

        Blindado en dos frentes:
        - Por tiempo: procesa en tandas de `_REGENERAR_CARGOS_CHUNK_SIZE` residencias
          por click (usando `regenerar_cargos_cursor` para no repetir ni saltarse
          ninguna entre clicks), para no exceder el límite de tiempo de una petición
          web en proyectos grandes.
        - Por errores puntuales: cada residencia se regenera dentro de su propio
          savepoint; si una falla (dato faltante, configuración inválida, etc.), se
          revierte SOLO esa residencia y se sigue con las demás, en vez de perder
          toda la tanda. Las fallidas se listan al final para poder corregirlas."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Solo puedes regenerar cargos en estado Borrador."))

        Line = self.env["asovec.proyecto_cobro_mensual_line"]
        lineas = Line.search([
            ("cobro_id", "=", self.id),
            ("residencia_id", "!=", False),
            ("residencia_id", ">", self.regenerar_cargos_cursor),
        ], order="residencia_id asc", limit=self._REGENERAR_CARGOS_CHUNK_SIZE)

        if not lineas:
            self.regenerar_cargos_cursor = -1
            self.env.cr.commit()
            self.message_post(body=_("No queda ninguna residencia por regenerar en este ciclo. ¡Completo!"))
            return self._reabrir_form_action()

        # Capturar todo ANTES de regenerar: cada regeneración borra y recrea la línea.
        a_procesar = [(l.residencia_id, l.contador_line_id, l.move_id) for l in lineas]
        ultimo_residencia_id = max(r.id for r, _, _ in a_procesar)

        journal = self._get_journal_cargo()
        servicios = self._get_servicios_automaticos()
        productos_especiales = self._get_productos_especiales()

        regenerados = 0
        saltados = 0
        fallidos = []
        for residencia, lectura, move in a_procesar:
            if move and move.state == "posted":
                saltados += 1
                continue
            try:
                with self.env.cr.savepoint():
                    self._generar_cargo_residencia(
                        residencia, lectura=lectura, journal=journal,
                        servicios=servicios, productos_especiales=productos_especiales,
                    )
                regenerados += 1
            except Exception as e:
                fallidos.append(_("%s: %s") % (residencia.display_name, str(e)))

        restantes = Line.search_count([
            ("cobro_id", "=", self.id),
            ("residencia_id", "!=", False),
            ("residencia_id", ">", ultimo_residencia_id),
        ])
        self.regenerar_cargos_cursor = ultimo_residencia_id if restantes else -1
        self.env.cr.commit()

        message = _("Se regeneraron %s cargos.") % regenerados
        if saltados:
            message += _(" %s ya estaban posteados y se saltaron.") % saltados
        if restantes:
            message += _(" Quedan %s residencias más: vuelve a presionar el botón para continuar.") % restantes
        else:
            message += _(" ¡Completo!")
        if fallidos:
            message += "\n\n" + _("%s fallaron:") % len(fallidos) + "\n" + "\n".join(fallidos)

        self.message_post(body=message)
        return self._reabrir_form_action()

    def _reabrir_form_action(self):
        """Reabre este mismo registro en su vista de formulario. Se usa en vez de una
        acción de recarga genérica (p.ej. 'soft_reload') porque esa depende de que el
        cliente adivine cuál es el 'controlador actual', y en ciertos casos terminaba
        mostrando otro registro de cobro mensual en vez de quedarse en este."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "views": [(False, "form")],
            "res_id": self.id,
            "target": "current",
        }

    # Postear en lotes evita exceder el tiempo límite de una sola petición web
    # (el posteo de facturas de Odoo asigna el número de secuencia registro por
    # registro; con cientos de residencias esto puede tardar varios minutos).
    _CONFIRM_CHUNK_SIZE = 50

    def action_confirm(self):
        """Publica el cobro mensual y postea los cargos relacionados, en lotes.

        Si se interrumpe (o falla) a la mitad, los lotes ya posteados quedan
        confirmados: el cobro sigue en Borrador y se puede volver a presionar
        Confirmar para continuar solo con los cargos que faltan.
        """
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Solo puedes confirmar desde Borrador."))

            if rec.residencias_pendientes:
                raise UserError(_(
                    "Todavía faltan %s residencias por generar. Usa "
                    "'Completar Faltantes' antes de confirmar."
                ) % rec.residencias_pendientes)

            moves = rec.line_ids.mapped("move_id").filtered(lambda m: m)
            if not moves:
                raise UserError(_("No hay cargos relacionados para confirmar."))

            cancelled = moves.filtered(lambda m: m.state == "cancel")
            if cancelled:
                raise UserError(_(
                    "Hay cargos cancelados y no se pueden confirmar desde aquí:\n%s"
                ) % "\n".join(cancelled.mapped("name")))

            pendientes = moves.filtered(lambda m: m.state == "draft")

            total = len(pendientes)
            for i in range(0, total, self._CONFIRM_CHUNK_SIZE):
                lote = pendientes[i:i + self._CONFIRM_CHUNK_SIZE]
                try:
                    lote.action_post()
                except Exception as e:
                    raise UserError(_(
                        "Se confirmaron %s de %s cargos pendientes antes de encontrar un "
                        "error. Los ya confirmados quedan posteados: corrige el problema y "
                        "vuelve a presionar Confirmar para continuar con el resto.\n\n"
                        "Detalle: %s"
                    ) % (i, total, str(e)))
                self.env.cr.commit()

            rec.state = "posted"
            rec.fecha_confirmacion = fields.Date.context_today(rec)

        return True

    def action_set_draft(self):
        """Regresa el cobro mensual y sus cargos a borrador (solo desde publicado)."""
        for rec in self:
            if rec.state != "posted":
                raise UserError(_("Solo puedes regresar a Borrador desde Publicado."))

            moves = rec.line_ids.mapped("move_id").filtered(lambda m: m)

            try:
                posted_moves = moves.filtered(lambda m: m.state == "posted")
                if posted_moves:
                    posted_moves.button_draft()
            except Exception as e:
                raise UserError(_("No se pudieron revertir los cargos a borrador.\n\nDetalle: %s") % str(e))

            rec.state = "draft"
            rec.fecha_confirmacion = False

        return True


class ProyectoCobroMensualLine(models.Model):
    _name = "asovec.proyecto_cobro_mensual_line"
    _description = "Detalle cobro mensual por Residencia"
    _order = "id desc"

    cobro_id = fields.Many2one(
        comodel_name="asovec.proyecto_cobro_mensual",
        string="Cobro mensual",
        required=True,
        ondelete="cascade",
        index=True,
    )
    month = fields.Selection(related="cobro_id.month", string="Mes", store=True, readonly=True)
    year = fields.Integer(related="cobro_id.year", string="Año", store=True, readonly=True)
    cobro_state = fields.Selection(related="cobro_id.state", string="Estado cobro", store=True, readonly=True)

    proyecto_aso_id = fields.Many2one(related="cobro_id.proyecto_aso_id", string="Proyecto", store=True, readonly=True)
    residencia_id = fields.Many2one(comodel_name="asovec.residencia", string="Residencia", required=True, index=True)
    #cliente_id = fields.Many2one(related="residencia_id.cliente_id", string="Cliente", store=True, readonly=True)

    cliente_id = fields.Many2one(comodel_name="res.partner", string="Cliente", readonly=True, index=True)

    move_id = fields.Many2one(
        comodel_name="account.move",
        string="Cargo",
        help="Cargo contable asociado (se creará luego).",
        ondelete="set null",
    )

    # ✅ lo conservamos como lo tenías
    move_state = fields.Selection(related="move_id.state", string="Estado cargo", readonly=True, store=False)
    payment_state = fields.Selection(related="move_id.payment_state", string="Estado de pago", readonly=True, store=False)
    state = fields.Selection(related="cobro_id.state", string="Estado de cobro", readonly=True, store=False)

    currency_id = fields.Many2one("res.currency", related="move_id.currency_id", store=True, readonly=True)

    amount_total = fields.Monetary(
        string="Total",
        related="move_id.amount_total",
        currency_field="currency_id",
        store=True,
        readonly=True,
    )

    # ✅ este era tu “dummy”, pero en realidad ya estás usando residual real; lo dejamos intacto
    amount_balance = fields.Monetary(
        string="Saldo",
        compute="_compute_line_balance",
        currency_field="currency_id",
        store=True,
        readonly=True,
        help="Saldo (por move.amount_residual).",
    )

    amount_residual = fields.Monetary(
        string="Saldo real",
        related="move_id.amount_residual",
        currency_field="currency_id",
        store=True,
        readonly=True,
    )

    amount_paid = fields.Monetary(
        string="Pagado",
        compute="_compute_amount_paid",
        currency_field="currency_id",
        store=True,
        readonly=True,
    )

    con_lectura = fields.Char(string='Lectura de Contador', default="Sin Lectura")

    contador_line_id = fields.Many2one(
        comodel_name="asovec.contador.lines",
        string="Lectura",
        readonly=True,
        help="Lectura de contador usada para calcular este cargo (vacío si no hubo lectura ese mes).",
    )
    lectura_anterior = fields.Float(related="contador_line_id.lectura_anterior", string="Lectura anterior", readonly=True)
    # No editable aquí: corregir la lectura regenera el cargo (borra y recrea ESTA
    # misma línea vía _generar_cargo_mensual -> _generar_cargo_residencia), así que
    # escribir sobre este propio registro lo borra a mitad de su propio write() y
    # revierte toda la transacción. Ver action_corregir_lectura: la corrección se
    # hace desde el formulario normal de asovec.contador.lines, que sí sobrevive a
    # la regeneración del cargo.
    lectura_actual = fields.Float(related="contador_line_id.lectura", string="Lectura actual", readonly=True)
    consumo = fields.Float(related="contador_line_id.consumo", string="Consumo (m³)", readonly=True)
    exceso = fields.Float(
        string="Exceso (m³)",
        related="contador_line_id.metros_extras",
        readonly=True,
        help="Metros cúbicos consumidos por encima del derecho base.",
    )
    base = fields.Monetary(
        string="Base",
        related="contador_line_id.base",
        currency_field="currency_id",
        readonly=True,
    )
    pago_extra = fields.Monetary(
        string="Pago Extra",
        related="contador_line_id.pago_extra",
        currency_field="currency_id",
        readonly=True,
        help="Monto cobrado por el consumo en exceso.",
    )
    pago_total = fields.Monetary(
        string="Pago Total",
        related="contador_line_id.pago_total",
        currency_field="currency_id",
        readonly=True,
    )
    foto = fields.Binary(related="contador_line_id.foto", string="Foto", readonly=True)
    foto_filename = fields.Char(related="contador_line_id.foto_filename", string="Nombre foto", readonly=True)
    observaciones = fields.Text(related="contador_line_id.observaciones", string="Observaciones", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.residencia_id and rec.residencia_id.cliente_id:
                rec.cliente_id = rec.residencia_id.cliente_id.id
        return records

    def action_imprimir_recibo(self):
        self.ensure_one()
        if not self.contador_line_id:
            raise UserError(_(
                "Esta residencia no tiene una lectura asociada a este cargo; no se puede imprimir el recibo."
            ))
        return self.contador_line_id.action_imprimir_recibo()

    def action_imprimir_cargo(self):
        """Imprime el nuevo formato de recibo (nombre del diario y número del
        cargo si ya está posteado), sin importar el estado del cobro o del cargo."""
        self.ensure_one()
        return self.env.ref("iit_asovec.action_report_cargo_residencia").report_action(self)

    @api.depends("amount_total", "amount_residual")
    def _compute_line_balance(self):
        for line in self:
            line.amount_balance = line.amount_residual or 0.0

    @api.depends("move_id.amount_total", "move_id.amount_residual")
    def _compute_amount_paid(self):
        for line in self:
            total = line.move_id.amount_total if line.move_id else 0.0
            residual = line.move_id.amount_residual if line.move_id else 0.0
            line.amount_paid = total - residual

    def action_corregir_lectura(self):
        """Abre el formulario NORMAL de la lectura (asovec.contador.lines) para
        corregirla ahí. No se edita 'lectura_actual' en este propio formulario porque
        corregir la lectura regenera el cargo (borra y recrea esta misma línea), lo
        que revertiría la transacción si se editara desde aquí (ver comentario en el
        campo `lectura_actual`)."""
        self.ensure_one()
        if not self.contador_line_id:
            raise UserError(_("Esta línea no tiene una lectura de contador asociada."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Corregir Lectura"),
            "res_model": "asovec.contador.lines",
            "view_mode": "form",
            "res_id": self.contador_line_id.id,
            "target": "current",
            # Al presionar "💾 Guardar" en ese formulario, regresa aquí (ver
            # ContadorLine.action_save). Si ese mismo formulario se abre desde otro
            # lado (sin este contexto), Guardar se comporta como siempre.
            "context": {"cobro_mensual_return_id": self.cobro_id.id},
        }

    def action_regenerar_cargo(self):
        """Borra el cargo de esta residencia (si sigue en borrador o cancelado) y lo
        vuelve a generar con la configuración vigente (precios, cuentas contables por
        proyecto, etc.) - útil para validar cambios de configuración sin tener que
        tocar la lectura. Si el cargo ya está posteado, `_generar_cargo_residencia`
        lanza error y no hace nada.

        Los valores se capturan ANTES de regenerar porque _generar_cargo_residencia
        borra y recrea esta misma línea (self): leer self.* después de eso fallaría
        con MissingError (mismo caso que action_corregir_lectura)."""
        self.ensure_one()
        cobro = self.cobro_id
        residencia = self.residencia_id
        lectura = self.contador_line_id
        cobro._generar_cargo_residencia(residencia, lectura=lectura)
        return cobro._reabrir_form_action()

    # --------------------
    # Formato CSV compartido (usado por el cobro mensual individual y por el proceso
    # de consulta de lecturas de todos los proyectos, para que ambos exporten
    # exactamente las mismas columnas).
    # --------------------
    @api.model
    def _csv_servicios(self):
        return self.env["product.template"].search([
            ("aso_es_servicio_aso", "=", True),
            ("aso_automatico", "=", True),
            ("aso_activo", "=", True),
        ])

    @api.model
    def _csv_header(self, servicios):
        header = [
            "Residencia", "Cliente", "Proyecto", "Contador", "Estado residencia",
            "Con lectura", "Mes", "Año",
            "Lectura anterior", "Lectura actual", "Consumo (m3)", "Exceso (m3)",
            "Canon base", "Pago extra", "Pago total (agua)",
        ]
        header += [s.name for s in servicios]
        header += ["Total cargo", "Estado cargo", "Estado de pago", "Observaciones", "Con Foto"]
        return header

    @api.model
    def _csv_row(self, residencia, lectura, move, con_lectura, amount_total, move_state, payment_state, servicios):
        def fmt2(value):
            return f"{value or 0.0:.2f}"

        contador = residencia._get_contador_activo()
        row = [
            residencia.name,
            residencia.cliente_id.name or "",
            residencia.proyecto_aso_id.name or "",
            contador.name if contador else "",
            "Activo" if residencia.activo else "Inactivo",
            con_lectura or "",
            lectura.mes if lectura else "",
            lectura.anio if lectura else "",
            fmt2(lectura.lectura_anterior if lectura else 0.0),
            fmt2(lectura.lectura if lectura else 0.0),
            fmt2(lectura.consumo if lectura else 0.0),
            fmt2(lectura.metros_extras if lectura else 0.0),
            fmt2(lectura.base if lectura else 0.0),
            fmt2(lectura.pago_extra if lectura else 0.0),
            fmt2(lectura.pago_total if lectura else 0.0),
        ]

        for servicio in servicios:
            importe = 0.0
            if move:
                sline = move.invoice_line_ids.filtered(
                    lambda l: l.product_id.product_tmpl_id == servicio
                )[:1]
                importe = sline.price_subtotal if sline else 0.0
            row.append(fmt2(importe))

        row += [
            fmt2(amount_total), move_state or "", payment_state or "",
            lectura.observaciones or "" if lectura else "",
            "Con Foto" if (lectura and lectura.foto) else "",
        ]
        return row

    @api.model
    def _lecturas_rows(self, residencias, mes, anio):
        """Para cada una de las `residencias` dadas, arma la tupla (residencia,
        lectura, move, con_lectura, amount_total, move_state, payment_state) para el
        mes/año pedido, leyendo directamente la lectura del contador y el cargo
        asociado si ya existe. No depende de que 'Completar Faltantes' se haya
        corrido: refleja el estado real de las lecturas en cualquier momento."""
        if not residencias:
            return []

        mes_plano = str(int(mes))
        mes_padded = str(mes).zfill(2)

        lecturas = self.env["asovec.contador.lines"].search([
            ("residencia_id", "in", residencias.ids),
            ("anio", "=", anio),
            ("mes", "=", mes_plano),
            ("es_inicial", "=", False),
        ])
        lectura_por_residencia = {l.residencia_id.id: l for l in lecturas}

        cobro_lines = self.search([
            ("residencia_id", "in", residencias.ids),
            ("month", "=", mes_padded),
            ("year", "=", anio),
            ("cobro_state", "!=", "cancel"),
        ])
        cobro_por_residencia = {cl.residencia_id.id: cl for cl in cobro_lines}

        rows = []
        for residencia in residencias.sorted(lambda r: r.name or ""):
            lectura = lectura_por_residencia.get(residencia.id)
            cobro_line = cobro_por_residencia.get(residencia.id)

            if not residencia.activo:
                con_lectura = "Inactivo"
            elif lectura:
                con_lectura = "Lectura Valida"
            else:
                con_lectura = "Sin Lectura"

            rows.append((
                residencia,
                lectura,
                cobro_line.move_id if cobro_line else False,
                con_lectura,
                cobro_line.amount_total if cobro_line else 0.0,
                cobro_line.move_state if cobro_line else False,
                cobro_line.payment_state if cobro_line else False,
            ))
        return rows
