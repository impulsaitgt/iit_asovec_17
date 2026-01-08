from odoo import models,fields,api

class Residencia(models.Model):
    _name = 'asovec.residencia'

    name = fields.Char(string="Nombre/Codigo",required=True)
    direccion = fields.Char(string="Direccion")
    detalle = fields.Text(string="Informacion Detallada")
    proyecto_aso_id = fields.Many2one(string="Proyecto", comodel_name='asovec.proyecto_aso', required=True)
    cliente_id = fields.Many2one(comodel_name='res.partner', string="Contacto", required=False)
    residencia_lines = fields.One2many(comodel_name="asovec.residencia.lines", inverse_name="residencia_id")

    
    _sql_constraints = [
        ('referencia_unica', 'unique(name)', "Esta residencia ya existe, por favor especifica otro Nombre/Codigo")
    ]

class ResidenciaLines(models.Model):
    _name = 'asovec.residencia.lines'

    producto_id = fields.Many2one(string="Servicio", comodel_name='product.template', required=True, domain=[('aso_es_servicio_aso', '=', True)])
    precio = fields.Float(string="Precio", default=0, required=True)
    residencia_id = fields.Many2one(comodel_name='asovec.residencia')


    @api.onchange('producto_id')
    def _onchange_product_id(self):
        for line in self:
            line.precio = self.producto_id.list_price