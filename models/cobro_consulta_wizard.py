from odoo import models, fields, _
from odoo.exceptions import UserError

class CobroMensualConsultaWizard(models.TransientModel):
    _name = "asovec.cobro_mensual_consulta_wizard"
    _description = "Consulta Cobros Mensuales por Proyecto y Residencia"

    proyecto_aso_id = fields.Many2one(
        "asovec.proyecto_aso",
        string="Proyecto",
        required=True,
    )

    residencia_id = fields.Many2one(
        "asovec.residencia",
        string="Residencia",
        required=True,
        domain="[('proyecto_aso_id', '=', proyecto_aso_id)]",
    )

    cliente_id = fields.Many2one(related="residencia_id.cliente_id", string="Cliente", store=True, readonly=True)
    solo_residente_actual = fields.Boolean(string="Solo movimientos del residente actual", default=True)


    # -------------------------
    # Abrir estado de cuenta
    # -------------------------
    def action_consultar(self):
        self.ensure_one()

        if self.residencia_id.proyecto_aso_id != self.proyecto_aso_id:
            raise UserError(_("La residencia no pertenece al proyecto seleccionado."))
        
        domain = [("proyecto_aso_id", "=", self.proyecto_aso_id.id),
                  ("residencia_id", "=", self.residencia_id.id),
                  ("cobro_id.state", "=", "posted")]

        # ✅ nuevo filtro según checkbox
        if self.solo_residente_actual and self.cliente_id:
            domain.append(("cliente_id", "=", self.cliente_id.id))

        return {"type": "ir.actions.act_window",
                "name": _("Estado de cuenta: %s / %s") % (self.proyecto_aso_id.display_name,
                                                          self.residencia_id.display_name),
                "res_model": "asovec.proyecto_cobro_mensual_line",
                "view_mode": "tree,form",
                "target": "current",
                "domain": domain}

    # -------------------------
    # Imprimir PDF
    # -------------------------
    def action_print_pdf(self):
        self.ensure_one()

        if self.residencia_id.proyecto_aso_id != self.proyecto_aso_id:
            raise UserError(_("La residencia no pertenece al proyecto seleccionado."))

        # IMPORTANTE: pasar data={} fuerza a Odoo a usar docs (recordset)
        return self.env.ref("iit_asovec.action_report_estado_cuenta_pdf").report_action(self, data={})

    # -------------------------
    # Líneas del estado de cuenta
    # -------------------------
    """ def _get_estado_cuenta_lines(self):
        self.ensure_one()
        return self.env["asovec.proyecto_cobro_mensual_line"].search([
            ("proyecto_aso_id", "=", self.proyecto_aso_id.id),
            ("residencia_id", "=", self.residencia_id.id),
            ("cobro_id.state", "=", "posted"),
        ], order="year desc, month desc, id desc")
     """
    def _get_estado_cuenta_lines(self):
        self.ensure_one()

        domain = [
            ("proyecto_aso_id", "=", self.proyecto_aso_id.id),
            ("residencia_id", "=", self.residencia_id.id),
            ("cobro_id.state", "=", "posted"),
        ]
        if self.solo_residente_actual and self.cliente_id:
            domain.append(("cliente_id", "=", self.cliente_id.id))

        return self.env["asovec.proyecto_cobro_mensual_line"].search(domain, order="year desc, month desc, id desc")
