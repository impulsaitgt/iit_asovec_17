from odoo import models, fields, api
from odoo.exceptions import ValidationError


class product_template(models.Model):
    _inherit = "product.template"

    aso_es_servicio_aso = fields.Boolean(string='Es Servicio de Asociacion', default=False)
    tipo_servicio_aso_id = fields.Many2one(string="Tipo Servicio Asociacion", comodel_name='asovec.tipo_servicio_aso', required=False)
    aso_automatico = fields.Boolean(related="tipo_servicio_aso_id.aso_automatico", string="Servicio Automatico", store=False, readonly=True)
    aso_agua_inactivo = fields.Boolean(related="tipo_servicio_aso_id.aso_agua_inactivo", string="Servicio Agua Inactivo", store=False, readonly=True)
    aso_agua_base = fields.Boolean(related="tipo_servicio_aso_id.aso_agua_base", string="Servicio Agua Base", store=False, readonly=True)
    aso_agua_exceso = fields.Boolean(related="tipo_servicio_aso_id.aso_agua_exceso", string="Servicio Agua Exceso", store=False, readonly=True)



    _sql_constraints = [
        ('no_servicio_no_aso', "CHECK (NOT aso_es_servicio_aso OR detailed_type = 'service')", 'No es permitido que un servicio de asociacion que no sea un servicio.')
    ]


    @api.constrains('aso_es_servicio_aso', 'detailed_type')
    def _check_aso_solo_servicio(self):
        for rec in self:
            if rec.aso_es_servicio_aso and rec.detailed_type != 'service':
                raise ValidationError(
                    'Para marcar "Servicio ASO", el producto debe ser de tipo Servicio.'
                )