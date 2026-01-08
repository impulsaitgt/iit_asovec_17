from odoo import models, fields


class product_template(models.Model):
    _inherit = "product.template"

    aso_es_servicio_aso = fields.Boolean(string='Es Servicio de Asociacion', default=False)
    