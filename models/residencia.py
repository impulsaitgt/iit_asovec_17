from odoo import models,fields,api

class Residencia(models.Model):
    _name = 'asovec.residencia'

    name = fields.Char(string="Nombre/Codigo",required=True)
    direccion = fields.Char(string="Direccion")
    detalle = fields.Text(string="Informacion Detallada")
    
    _sql_constraints = [
        ('referencia_unica', 'unique(name)', "Esta residencia ya existe, por favor especifica otro Nombre/Codigo")
    ]

