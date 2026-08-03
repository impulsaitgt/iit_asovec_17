# -*- coding: utf-8 -*-
from odoo import models, fields, api


class OrdenTrabajo(models.Model):
    _name = "asovec.orden_trabajo"
    _description = "Orden de Trabajo (personal de campo)"
    _order = "fecha_creacion desc, id desc"
    _rec_name = "name"

    name = fields.Char(string="Correlativo", required=True, copy=False, readonly=True, default="Nuevo")

    residencia_id = fields.Many2one(
        "asovec.residencia", string="Residencia", required=True,
        help="Al seleccionar la residencia se completan automáticamente Proyecto, "
             "Nombre, Dirección y Teléfono.",
    )
    proyecto_aso_id = fields.Many2one(
        related="residencia_id.proyecto_aso_id", string="Proyecto", store=True, readonly=True,
    )
    cliente_id = fields.Many2one(
        related="residencia_id.cliente_id", string="Nombre", store=True, readonly=True,
    )
    direccion = fields.Char(
        related="residencia_id.direccion_real", string="Dirección", store=True, readonly=True,
    )
    telefono = fields.Char(
        related="cliente_id.phone", string="Teléfono", store=True, readonly=True,
    )

    fecha_creacion = fields.Date(string="Fecha Creación", required=True, default=fields.Date.context_today)
    creador_id = fields.Many2one(
        "res.users", string="Colaborador creador de la orden",
        default=lambda self: self.env.user, readonly=True, required=True,
    )
    concepto = fields.Text(
        string="Concepto", required=True,
        help="Ej. Realizar reconexión, corte de servicio, revisión por fuga, cambio "
             "de contador.",
    )
    colaborador_id = fields.Many2one(
        "hr.employee", string="Colaborador",
        help="Personal de campo asignado para ejecutar la orden.",
    )

    reporte = fields.Text(string="Reporte", help="Se completa al finalizar el trabajo en campo.")
    fecha_finalizacion = fields.Date(string="Fecha Finalización")

    company_id = fields.Many2one(
        "res.company", string="Compañía", required=True, default=lambda self: self.env.company,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == "Nuevo":
                vals["name"] = self.env["ir.sequence"].next_by_code("asovec.orden_trabajo") or "Nuevo"
        return super().create(vals_list)

    def action_imprimir(self):
        return self.env.ref("iit_asovec.action_report_orden_trabajo").report_action(self)
