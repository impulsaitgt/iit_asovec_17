from odoo import models, fields, api
from odoo.exceptions import ValidationError


class product_template(models.Model):
    _inherit = "product.template"

    aso_es_servicio_aso = fields.Boolean(string='Es Servicio de Asociacion', default=False)
    aso_activo = fields.Boolean(
        string='Activo',
        default=True,
        help="Indica si este servicio de asociación está actualmente vigente. "
             "Desmárquelo cuando ya no se deba seguir generando/ofreciendo (por ejemplo, al "
             "terminar el período estimado de una cuota especial), sin afectar los cargos ya "
             "generados con este servicio.",
    )
    tipo_servicio_aso_id = fields.Many2one(string="Tipo Servicio Asociacion", comodel_name='asovec.tipo_servicio_aso', required=False)
    aso_automatico = fields.Boolean(related="tipo_servicio_aso_id.aso_automatico", string="Servicio Automatico", store=False, readonly=True)
    aso_agua_inactivo = fields.Boolean(related="tipo_servicio_aso_id.aso_agua_inactivo", string="Servicio Agua Inactivo", store=False, readonly=True)
    aso_agua_base = fields.Boolean(related="tipo_servicio_aso_id.aso_agua_base", string="Servicio Agua Base", store=False, readonly=True)
    aso_agua_exceso = fields.Boolean(related="tipo_servicio_aso_id.aso_agua_exceso", string="Servicio Agua Exceso", store=False, readonly=True)
    aso_migrado = fields.Boolean(related="tipo_servicio_aso_id.aso_migrado", string="Servicio Migrado", store=False, readonly=True)
    aso_convenio = fields.Boolean(
        string='Servicio de Convenio',
        default=False,
        help="Marca este Servicio de Asociación como el usado para los cargos de "
             "Convenio (menú Movimientos > Convenio). Solo puede haber un Servicio "
             "con este flag activo por compañía.",
    )



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

    @api.constrains('aso_convenio', 'aso_es_servicio_aso')
    def _check_aso_convenio_solo_servicio_aso(self):
        for rec in self:
            if rec.aso_convenio and not rec.aso_es_servicio_aso:
                raise ValidationError(
                    'Para marcar "Servicio de Convenio", el producto debe ser un Servicio de Asociación.'
                )

    @api.constrains('aso_convenio', 'company_id')
    def _check_aso_convenio_unico(self):
        for rec in self:
            if not rec.aso_convenio:
                continue
            domain = [('aso_convenio', '=', True), ('id', '!=', rec.id)]
            if rec.company_id:
                domain += ['|', ('company_id', '=', rec.company_id.id), ('company_id', '=', False)]
            otros = self.search(domain)
            if otros:
                raise ValidationError(
                    'Ya existe el Servicio "%s" marcado como "Servicio de Convenio" para esta compañía. '
                    'Solo puede haber uno.' % otros[0].name
                )