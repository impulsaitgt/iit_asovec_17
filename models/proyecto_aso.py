from odoo import models,fields

class ProyectoAso(models.Model):
    _name = 'asovec.proyecto_aso'

    name = fields.Char(string="Nombre",required=True)
    direccion = fields.Char(string="Direccion")
    detalle = fields.Text(string="Informacion Detallada")
    company_id = fields.Many2one("res.company", string="Compañía", required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one("res.currency", string="Moneda", related="company_id.currency_id", store=True, readonly=True)
    cobro_base = fields.Monetary(string="Cobro Base", currency_field="currency_id", default=0, required=True)
    precio_metro = fields.Monetary(string="Precio Metro", currency_field="currency_id", default=0, required=True)
    metro_base = fields.Integer(string="Metros base (derecho)", default=0, required=True)
    cobro_inactivas = fields.Monetary(string="Cobro por Inactivas", currency_field="currency_id", required=True, default=0.00)
    residencia_count = fields.Integer(string="Residencias", compute="_compute_residencia_count")
    leyenda_recibo = fields.Html(
        string="Leyenda del Recibo",
        sanitize=True,
        default="<p>Cualquier consulta relacionada</p>",
        help="Texto que se muestra en el recibo mensual de las residencias, en lugar de 'Cualquier consulta relacionada'.",
    )
    dia_tentativo_carga = fields.Integer(
        string="Día tentativo de carga de datos",
        default=6,
        required=True,
        help="Día del mes usado para calcular la fecha a partir de la cual se puede pagar, "
             "cuando el cobro mensual todavía no ha sido confirmado.",
    )

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

    def action_abrir_recibo_masivo_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Generar Recibos Mensuales',
            'res_model': 'asovec.proceso_recibo_masivo_wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_proyecto_aso_id': self.id},
        }


