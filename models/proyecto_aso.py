from odoo import models,fields

class ProyectoAso(models.Model):
    _name = 'asovec.proyecto_aso'

    name = fields.Char(string="Nombre",required=True)
    direccion = fields.Char(string="Direccion")
    detalle = fields.Text(string="Informacion Detallada")
    cobro_base = fields.Float(string="Cobro Base", default=0, required=True)
    precio_metro = fields.Float(string="Precio Metro", default=0, required=True)
    metro_base = fields.Integer(string="Metros base (derecho)", default=0, required=True)
    cobro_inactivas = fields.Float(string="Cobro por Inactivas", required=True, default=0.00)
    

    _sql_constraints = [
        ('referencia_unica', 'unique(name)', "Este proyecto ya existe, por favor especifica otro Nombre")
    ]

