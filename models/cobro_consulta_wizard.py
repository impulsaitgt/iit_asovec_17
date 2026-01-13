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

    def action_consultar(self):
        self.ensure_one()

        if self.residencia_id.proyecto_aso_id != self.proyecto_aso_id:
            raise UserError(_("La residencia no pertenece al proyecto seleccionado."))

        return {
            "type": "ir.actions.act_window",
            "name": _("Cobros mensuales"),
            "res_model": "asovec.proyecto_cobro_mensual_line",
            "view_mode": "tree,form",
            "target": "current",
            "domain": [
                ("proyecto_aso_id", "=", self.proyecto_aso_id.id),
                ("residencia_id", "=", self.residencia_id.id),
                ("cobro_id.state", "!=", "cancel"),
            ],
        }
