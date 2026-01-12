# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ProyectoCobroMensual(models.Model):
    _name = "asovec.proyecto_cobro_mensual"
    _description = "Cobro mensual por Proyecto"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "year desc, month desc, id desc"

    name = fields.Char(string="Referencia", compute="_compute_name", store=True)
    proyecto_aso_id = fields.Many2one(comodel_name="asovec.proyecto_aso", string="Proyecto", required=True, index=True, tracking=True)

    month = fields.Selection(selection=[("01", "Enero"), ("02", "Febrero"), ("03", "Marzo"), ("04", "Abril"),
            ("05", "Mayo"), ("06", "Junio"), ("07", "Julio"), ("08", "Agosto"),
            ("09", "Septiembre"), ("10", "Octubre"), ("11", "Noviembre"), ("12", "Diciembre")],
                             string="Mes", required=True, default=lambda self: fields.Date.today().strftime("%m"), tracking=True)
    year = fields.Integer(string="Año", required=True, default=lambda self: fields.Date.today().year, tracking=True)
    state = fields.Selection(selection=[
            ("draft", "Borrador"),
            ("posted", "Publicado"),
            ("cancel", "Cancelado"),
        ],
        string="Estado", default="draft", required=True, tracking=True)

    line_ids = fields.One2many(comodel_name="asovec.proyecto_cobro_mensual_line", inverse_name="cobro_id", string="Detalle por Residencia", copy=False)
    company_id = fields.Many2one("res.company", string="Compañía", required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one("res.currency", string="Moneda", related="company_id.currency_id", store=True, readonly=True)
    total_to_charge = fields.Monetary(string="Total a cobrar", compute="_compute_totals", currency_field="currency_id", store=True, tracking=True)
    total_paid_dummy = fields.Monetary(string="Pagos realizados (dummy)", compute="_compute_paid_dummy", currency_field="currency_id", store=False, help="Por ahora es un cálculo dummy. Luego lo conectamos a pagos reales.", )
    total_balance = fields.Monetary(string="Saldo", compute="_compute_balance", currency_field="currency_id", store=True)


    def init(self):
        # Índice único parcial: solo cuando state != 'cancel'
        self._cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                asovec_cobro_uniq_proj_month_year_not_cancel
            ON asovec_proyecto_cobro_mensual (proyecto_aso_id, month, year)
            WHERE state != 'cancel';
        """)

    # _sql_constraints = [("uniq_project_month_year", "unique(proyecto_aso_id, month, year)", "Ya existe un cobro mensual para ese proyecto y período.")]

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

    @api.depends("total_to_charge")
    def _compute_paid_dummy(self):
        # Dummy: asumimos que se pagó 0. Luego lo conectamos a pagos/accounting.
        for rec in self:
            rec.total_paid_dummy = 0.0

    @api.depends("total_to_charge", "total_paid_dummy")
    def _compute_balance(self):
        for rec in self:
            rec.total_balance = rec.total_to_charge - rec.total_paid_dummy

    # --------------------
    # Acciones 
    # --------------------
    def action_generate(self):
        """Genera cargos (account.move) en draft por cada residencia del proyecto."""
        AccountMove = self.env["account.move"]
        Journal = self.env["account.journal"]
        Residencia = self.env["asovec.residencia"]
        ProductTemplate = self.env["product.template"]

        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Solo puedes generar en estado Borrador."))

            if not rec.proyecto_aso_id:
                raise UserError(_("Debes seleccionar un Proyecto."))

            # 1️⃣ Buscar journal de cargos ASO
            journal = Journal.search([("aso_cargo", "=", 'Si'),("company_id", "=", rec.company_id.id)], limit=1)
            if not journal:
                raise UserError(_("No existe un Diario contable con 'aso_cargo = Si'."))

            # 2️⃣ Buscar residencias del proyecto
            residencias = Residencia.search([("proyecto_aso_id", "=", rec.proyecto_aso_id.id)])
            if not residencias:
                raise UserError(_("No hay residencias asociadas a este proyecto."))

            # 3️⃣ Buscar servicios ASO (product.template)
            servicios = ProductTemplate.search([("aso_es_servicio_aso", "=", True)])
            if not servicios:
                raise UserError(_("No existen productos marcados como 'Servicio de Asociación'."))

            # 4️⃣ Limpiar detalle previo
            rec.line_ids.unlink()

            lines_vals = []

            for r in residencias:
                if not r.cliente_id:
                    raise UserError(_(
                        "La residencia '%s' no tiene un cliente (partner_id) asignado."
                    ) % r.display_name)

                # 5️⃣ Construir líneas de factura (una por cada servicio ASO)
                invoice_lines = []
                for t in servicios:
                    product = t.product_variant_id
                    if not product:
                        continue

                    invoice_lines.append((0, 0, {
                        "product_id": product.id,
                        "name": t.name,
                        "quantity": 1.0,
                        "price_unit": t.list_price,
                        "tax_ids": [(6, 0, [])],   # sin impuestos
                    }))

                if not invoice_lines:
                    raise UserError(_("No se pudieron generar líneas de cargo."))

                # 6️⃣ Crear el account.move (cargo) en draft
                move = AccountMove.create({
                    "move_type": "out_invoice",
                    "company_id": rec.company_id.id,
                    "journal_id": journal.id,
                    "partner_id": r.cliente_id.id,
                    "invoice_date": fields.Date.context_today(rec),
                    "invoice_origin": rec.name or "",
                    "ref": f"{rec.name or ''} - {r.display_name}",
                    "invoice_line_ids": invoice_lines,
                })

                # 7️⃣ Registrar en el detalle del cobro mensual
                lines_vals.append((0, 0, {
                    "residencia_id": r.id,
                    "move_id": move.id,
                    "amount_total": move.amount_total,
                }))

            rec.write({"line_ids": lines_vals})

        return True
    
    def action_confirm(self):
        """Publica el cobro mensual y postea todos los cargos relacionados (todo o nada)."""
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Solo puedes confirmar desde Borrador."))

            moves = rec.line_ids.mapped("move_id").filtered(lambda m: m)
            if not moves:
                raise UserError(_("No hay cargos relacionados para confirmar."))

            # opcional: asegurar que todos estén en draft antes de intentar postear
            not_draft = moves.filtered(lambda m: m.state != "draft")
            if not_draft:
                raise UserError(_(
                    "Hay cargos que no están en borrador y no se pueden confirmar desde aquí:\n%s"
                ) % "\n".join(not_draft.mapped("name")))

            try:
                # Esto postea las facturas/asientos. Si una falla, se lanza excepción y se revierte todo.
                moves.action_post()
            except Exception as e:
                # Si falla cualquiera, no se cambia el estado del cobro mensual.
                # Al lanzar UserError, Odoo revierte toda la transacción (no quedan cargos a medias).
                raise UserError(_("No se pudieron confirmar todos los cargos. Se canceló la operación completa.\n\nDetalle: %s") % str(e))

            # Solo si todo OK
            rec.state = "posted"

        return True

    def action_cancel(self):
        """Cancela el cobro mensual y todos los cargos relacionados (solo desde borrador)."""
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Solo puedes cancelar si está en Borrador."))

            moves = rec.line_ids.mapped("move_id").filtered(lambda m: m)
            not_draft = moves.filtered(lambda m: m.state != "draft")
            if not_draft:
                raise UserError(_(
                    "No puedes cancelar porque hay cargos que ya no están en borrador:\n%s"
                ) % "\n".join(not_draft.mapped("name")))

            # Borra (o cancela) los cargos
            moves.unlink()

            rec.state = "cancel"

        return True
    
    def action_set_draft(self):
        """Regresa el cobro mensual y sus cargos a borrador (solo desde publicado)."""
        for rec in self:
            if rec.state != "posted":
                raise UserError(_("Solo puedes regresar a Borrador desde Publicado."))

            moves = rec.line_ids.mapped("move_id").filtered(lambda m: m)

            try:
                # 1️⃣ Revertir facturas publicadas a draft
                posted_moves = moves.filtered(lambda m: m.state == "posted")
                if posted_moves:
                    posted_moves.button_draft()

            except Exception as e:
                raise UserError(_("No se pudieron revertir los cargos a borrador.\n\nDetalle: %s") % str(e))

            # 2️⃣ Ahora todo está en draft → regresamos el cobro mensual
            rec.state = "draft"

        return True




class ProyectoCobroMensualLine(models.Model):
    _name = "asovec.proyecto_cobro_mensual_line"
    _description = "Detalle cobro mensual por Residencia"
    _order = "id desc"

    cobro_id = fields.Many2one(comodel_name="asovec.proyecto_cobro_mensual", string="Cobro mensual", required=True, ondelete="cascade", index=True)
    proyecto_aso_id = fields.Many2one(related="cobro_id.proyecto_aso_id", string="Proyecto", store=True, readonly=True)
    residencia_id = fields.Many2one(comodel_name="asovec.residencia", string="Residencia", required=True, index=True)
    move_id = fields.Many2one(comodel_name="account.move", string="Cargo", help="Cargo contable asociado (se creará luego).", ondelete="set null")
    move_state = fields.Selection(related="move_id.state", string="Estado cargo", readonly=True, store=False)
    currency_id = fields.Many2one("res.currency", related="move_id.currency_id", store=True, readonly=True)
    amount_total = fields.Monetary(string="Total", related="move_id.amount_total", currency_field="currency_id", store=True, readonly=True)
    amount_balance = fields.Monetary(string="Saldo", compute="_compute_line_balance", currency_field="currency_id", store=False, readonly=True, help="Por ahora dummy: saldo = total.")

    @api.depends("amount_total")
    def _compute_line_balance(self):
        for line in self:
            line.amount_balance = line.amount_total

