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
    residencia_count = fields.Integer(string="Residencias", compute="_compute_residencia_count")

    _sql_constraints = [
        ('referencia_unica', 'unique(name)', "Este proyecto ya existe, por favor especifica otro Nombre")
    ]
    
    def _compute_residencia_count(self):
        Residencia = self.env['asovec.residencia'].sudo()
        for rec in self:
            rec.residencia_count = Residencia.search_count([('proyecto_aso_id', '=', rec.id)])

    def action_ver_residencias(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Residencias',
            'res_model': 'asovec.residencia',
            'view_mode': 'tree,form',
            'domain': [('proyecto_aso_id', '=', self.id)],
            'context': {
                'default_proyecto_aso_id': self.id,
                #'search_default_group_proyecto': 1,  # opcional si ya tenés group by
            },
        }
    


