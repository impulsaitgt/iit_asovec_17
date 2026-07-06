# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


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
        default=lambda self: fields.Date.today().strftime("%m"),
        tracking=True,
    )
    year = fields.Integer(
        string="Año",
        required=True,
        default=lambda self: fields.Date.today().year,
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
            [("aso_es_servicio_aso", "=", True), ("aso_automatico", "=", True)]
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

    def _build_invoice_lines_residencia(self, residencia, servicios, lectura, productos_especiales=None):
        """Devuelve (invoice_lines, con_lectura) para una residencia, igual a la lógica
        original de action_generate."""
        ResidenciaLines = self.env["asovec.residencia.lines"]
        productos_especiales = productos_especiales or self._get_productos_especiales()

        invoice_lines = []
        for t in servicios:
            product = t.product_variant_id
            if not product:
                continue

            servicio_especial = ResidenciaLines.search([
                ("residencia_id", "=", residencia.id), ("producto_id", "=", t.id)
            ])
            precio = servicio_especial.precio if servicio_especial else t.list_price

            if precio > 0:
                invoice_lines.append((0, 0, {
                    "product_id": product.id,
                    "name": t.name,
                    "quantity": 1.0,
                    "price_unit": precio,
                    "tax_ids": [(6, 0, [])],   # sin impuestos
                }))

        if not residencia.activo:
            # Cuota para contadores inactivos
            con_lectura = "Inactivo"
            servicio = productos_especiales["inactivo"]
            invoice_lines.append((0, 0, {
                "product_id": servicio.product_variant_id.id,
                "name": servicio.name,
                "quantity": 1.0,
                "price_unit": residencia.proyecto_aso_id.cobro_inactivas,
                "tax_ids": [(6, 0, [])],   # sin impuestos
            }))
        else:
            con_lectura = "Lectura Valida" if lectura else "Sin Lectura"

            # Cuota base para contadores
            cobro_base = lectura.base if lectura else residencia.proyecto_aso_id.cobro_base
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
            invoice_lines.append((0, 0, vals_line))

            # Pago extra para contadores
            cobro_exceso = lectura.pago_extra if lectura else 0
            if cobro_exceso > 0:
                servicio = productos_especiales["exceso"]
                invoice_lines.append((0, 0, {
                    "product_id": servicio.product_variant_id.id,
                    "name": servicio.name,
                    "quantity": 1.0,
                    "price_unit": cobro_exceso,
                    "tax_ids": [(6, 0, [])],   # sin impuestos
                }))

        if not invoice_lines:
            raise UserError(_("No se pudieron generar líneas de cargo para la residencia '%s'.") % residencia.display_name)

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

        invoice_lines, con_lectura = self._build_invoice_lines_residencia(
            residencia, servicios, lectura, productos_especiales=productos_especiales
        )

        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "company_id": self.company_id.id,
            "journal_id": journal.id,
            "partner_id": residencia.cliente_id.id,
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
    # Igual que al confirmar: generar en lotes evita exceder el tiempo límite de una
    # sola petición web en proyectos con muchas residencias, y si se interrumpe a la
    # mitad, lo ya generado queda guardado (se puede volver a presionar para continuar).
    _GENERATE_CHUNK_SIZE = 50

    def action_generate(self):
        """Genera el cargo de cada residencia del proyecto que todavía no lo tenga, y regenera
        (borra y vuelve a crear) los que sigan en borrador o cancelados, por si hubo cambios
        (precios, lecturas corregidas, etc). Si alguna residencia ya tiene un cargo posteado,
        se detiene con error: eso ya no se puede regenerar desde aquí."""
        ContadorLine = self.env["asovec.contador.lines"]
        Residencia = self.env["asovec.residencia"]

        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Solo puedes generar en estado Borrador."))

            if not rec.proyecto_aso_id:
                raise UserError(_("Debes seleccionar un Proyecto."))

            residencias = Residencia.search([("proyecto_aso_id", "=", rec.proyecto_aso_id.id)], order="id")
            if not residencias:
                raise UserError(_("No hay residencias asociadas a este proyecto."))

            # Se buscan una sola vez (antes se repetían por cada residencia).
            journal = rec._get_journal_cargo()
            servicios = rec._get_servicios_automaticos()
            productos_especiales = rec._get_productos_especiales()
            mes_plano = str(int(rec.month))

            lecturas = ContadorLine.search([
                ("residencia_id", "in", residencias.ids),
                ("anio", "=", rec.year),
                ("mes", "=", mes_plano),
                ("es_inicial", "=", False),
            ])
            lectura_por_residencia = {l.residencia_id.id: l for l in lecturas}

            total = len(residencias)
            for i in range(0, total, self._GENERATE_CHUNK_SIZE):
                lote = residencias[i:i + self._GENERATE_CHUNK_SIZE]
                try:
                    for r in lote:
                        rec._generar_cargo_residencia(
                            r,
                            lectura=lectura_por_residencia.get(r.id),
                            journal=journal,
                            servicios=servicios,
                            productos_especiales=productos_especiales,
                        )
                except Exception as e:
                    raise UserError(_(
                        "Se generaron %s de %s residencias antes de encontrar un error. "
                        "Lo ya generado queda guardado: corrige el problema y vuelve a "
                        "presionar el botón para continuar con el resto.\n\nDetalle: %s"
                    ) % (i, total, str(e)))
                self.env.cr.commit()

        return True

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
    lectura_actual = fields.Float(related="contador_line_id.lectura", string="Lectura actual", readonly=True)
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
