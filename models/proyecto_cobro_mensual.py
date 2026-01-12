# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ProyectoCobroMensual(models.Model):
    _name = "asovec.proyecto_cobro_mensual"
    _description = "Cobro mensual por Proyecto"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "year desc, month desc, id desc"

    name = fields.Char(string="Referencia", compute="_compute_name", store=True)
    project_id = fields.Many2one(comodel_name="asovec.proyecto_aso", string="Proyecto", required=True, index=True, tracking=True)

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
    total_to_charge = fields.Float(string="Total a cobrar", compute="_compute_totals", store=True, tracking=True)
    total_paid_dummy = fields.Float(string="Pagos realizados (dummy)", compute="_compute_paid_dummy", store=False, help="Por ahora es un cálculo dummy. Luego lo conectamos a pagos reales.", )
    total_balance = fields.Float(string="Saldo", compute="_compute_balance", store=True)

    _sql_constraints = [("uniq_project_month_year", "unique(project_id, month, year)", "Ya existe un cobro mensual para ese proyecto y período.")]

    @api.depends("project_id", "month", "year")
    def _compute_name(self):
        for rec in self:
            if rec.project_id and rec.month and rec.year:
                rec.name = f"{rec.project_id.display_name} - {rec.month}/{rec.year}"
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
    # Acciones (dummy)
    # --------------------
    def action_generate(self):
        """Genera líneas por cada residencia del proyecto. Deja en borrador."""
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Solo puedes generar en estado Borrador."))

            # Limpia líneas previas
            rec.line_ids.unlink()

            # Asunción: asovec.residencia tiene project_id = asovec.proyecto_aso
            residencias = self.env["asovec.residencia"].search([("project_id", "=", rec.project_id.id)])

            lines_vals = []
            for r in residencias:
                # Dummy: monto ejemplo (luego lo calculas según reglas)
                amount = 0.0
                lines_vals.append((0, 0, {
                    "residencia_id": r.id,
                    "amount_total": amount,
                    "amount_balance": amount,  # dummy saldo igual al total
                    "move_id": False,          # luego lo crearemos y lo linkeamos
                }))

            rec.write({"line_ids": lines_vals})
        return True

    def action_confirm(self):
        """Pasa a publicado."""
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Solo puedes confirmar desde Borrador."))
            rec.state = "posted"
        return True

    def action_cancel(self):
        """Cancela solo si está en borrador."""
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Solo puedes cancelar si está en Borrador."))
            rec.state = "cancel"
        return True

    def action_set_draft(self):
        """Opcional: volver a borrador desde cancelado."""
        for rec in self:
            if rec.state != "posted":
                raise UserError(_("Solo puedes regresar a Borrador desde Confirmado."))
            rec.state = "draft"
        return True


class ProyectoCobroMensualLine(models.Model):
    _name = "asovec.proyecto_cobro_mensual_line"
    _description = "Detalle cobro mensual por Residencia"
    _order = "id desc"

    cobro_id = fields.Many2one(comodel_name="asovec.proyecto_cobro_mensual", string="Cobro mensual", required=True, ondelete="cascade", index=True)
    project_id = fields.Many2one(related="cobro_id.project_id", string="Proyecto", store=True, readonly=True)
    residencia_id = fields.Many2one(comodel_name="asovec.residencia", string="Residencia", required=True, index=True)
    move_id = fields.Many2one(comodel_name="account.move", string="Cargo (Factura/Asiento)", help="Cargo contable asociado (se creará luego).", ondelete="set null")
    amount_total = fields.Float(string="Total", required=True, default=0.0)
    amount_balance = fields.Float(string="Saldo", compute="_compute_line_balance", store=False, help="Por ahora dummy: saldo = total. Luego se lee del move/pagos.")

    @api.depends("amount_total")
    def _compute_line_balance(self):
        for line in self:
            # Dummy: saldo igual al total.
            line.amount_balance = line.amount_total
