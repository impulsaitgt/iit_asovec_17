from odoo import models, fields, api
from odoo.exceptions import ValidationError


class product_template(models.Model):
    _inherit = "product.template"

    aso_es_servicio_aso = fields.Boolean(string='Es Servicio de Asociacion', default=False)
    aso_tipo_servicio = fields.Selection([
        ('canon', 'Canon de agua'),
        ('inactiva', 'Cuota Inactiva'),
        ('exceso', 'Exceso'),
        ('reconexion', 'Reconexión'),
        ('cambio_contador', 'Cambio de Contador'),
        ('infraestructura', 'Infraestructura y drenajes'),
        ('derecho_media_paja', 'Derecho de media paja de agua SNJ'),
        ('cuota_extra', 'Cuota Extraordinaria GDIII'),
        ('varios', 'Varios'),
        ('promejora', 'Promejoramiento'),
        ('asoveguas', 'ASOVEGUAS'),
        ('siretgua', 'SIRETGUA'),
    ], string="Tipo de Servicio ASO")

    @api.constrains('aso_es_servicio_aso', 'aso_tipo_servicio')
    def _check_tipo_servicio_aso(self):
        for rec in self:
            if rec.aso_es_servicio_aso and not rec.aso_tipo_servicio:
                raise ValidationError(
                    "Debe seleccionar un Tipo de Servicio ASO cuando el producto es un Servicio de Asociación."
                )

            if not rec.aso_es_servicio_aso and rec.aso_tipo_servicio:
                raise ValidationError(
                    "El Tipo de Servicio ASO solo puede usarse si 'Es Servicio de Asociación' está activo."
                )
