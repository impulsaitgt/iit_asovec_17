from odoo import models,fields,api
from psycopg2 import sql

class TipoProyectoAso(models.Model):
    _name = 'asovec.tipo_servicio_aso'

    name = fields.Char(string="Nombre",required=True)
    """     aso_tipo_servicio = fields.Selection([
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
    ], string="Tipo de Servicio ASO")  """
    aso_automatico = fields.Boolean(string='Automatico Mensual', default=False)
    aso_agua = fields.Boolean(string='Depende de lecturas de Contador', default=False)
    aso_agua_inactivo = fields.Boolean(string='Cobro para Contadores Inactivos', default=False)
    aso_agua_base = fields.Boolean(string='Cobro base por uso de Agua', default=False)
    aso_agua_exceso = fields.Boolean(string='Cobro por exceso de Agua', default=False)


    _sql_constraints = [
        ('referencia_unica', 'unique(name)', "Este tipo de servicio ya existe, por favor especifica otro Nombre"),
        ('no_automatico_y_agua', 'CHECK (NOT (aso_automatico = TRUE AND aso_agua = TRUE))', 'No es permitido que un servicio sea Automático y de Agua al mismo tiempo.')
    ]

    def init(self):
        self._cr.execute(sql.SQL("""
            CREATE UNIQUE INDEX IF NOT EXISTS unico_aso_agua_inactivo
            ON {table} (aso_agua_inactivo)
            WHERE aso_agua_inactivo IS TRUE
        """).format(table=sql.Identifier(self._table)))

        self._cr.execute(sql.SQL("""
            CREATE UNIQUE INDEX IF NOT EXISTS unico_aso_agua_base
            ON {table} (aso_agua_base)
            WHERE aso_agua_base IS TRUE
        """).format(table=sql.Identifier(self._table)))

        self._cr.execute(sql.SQL("""
            CREATE UNIQUE INDEX IF NOT EXISTS unico_aso_agua_exceso
            ON {table} (aso_agua_exceso)
            WHERE aso_agua_exceso IS TRUE
        """).format(table=sql.Identifier(self._table)))

    def _unset_otros_base(self, keep_field):
        for rec in self:
            for f in ('aso_automatico', 'aso_agua'):
                if f != keep_field:
                    rec[f] = False


    @api.onchange('aso_automatico')
    def _onchange_aso_automatico_check(self):
        for rec in self:
            if rec.aso_automatico:
                rec._unset_otros_base('aso_automatico')

    @api.onchange('aso_agua')
    def _onchange_aso_agua_check(self):
        for rec in self:
            if rec.aso_agua:
                rec._unset_otros_base('aso_agua')


    def _unset_otros(self, keep_field):
        for rec in self:
            for f in ('aso_agua_inactivo', 'aso_agua_base', 'aso_agua_exceso'):
                if f != keep_field:
                    rec[f] = False


    @api.onchange('aso_agua_inactivo')
    def _onchange_aso_agua_inactivo_check(self):
        for rec in self:
            if rec.aso_agua_inactivo:
                rec._unset_otros('aso_agua_inactivo')

    @api.onchange('aso_agua_base')
    def _onchange_aso_agua_base_check(self):
        for rec in self:
            if rec.aso_agua_base:
                rec._unset_otros('aso_agua_base')

    @api.onchange('aso_agua_exceso')
    def _onchange_aso_agua_exceso_check(self):
        for rec in self:
            if rec.aso_agua_exceso:
                rec._unset_otros('aso_agua_exceso')
