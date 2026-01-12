# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class Residencia(models.Model):
    _name = 'asovec.residencia'

    name = fields.Char(string="Nombre/Codigo", required=True)
    direccion = fields.Char(string="Direccion")
    detalle = fields.Text(string="Informacion Detallada")
    proyecto_aso_id = fields.Many2one(string="Proyecto", comodel_name='asovec.proyecto_aso', required=True)
    cliente_id = fields.Many2one(comodel_name='res.partner', string="Contacto", required=False)
    residencia_lines = fields.One2many(comodel_name="asovec.residencia.lines", inverse_name="residencia_id")
    contadores_ids = fields.One2many(comodel_name='asovec.contador', inverse_name='residencia_id', string='Contadores')
    contador_count = fields.Integer(string="Contadores", compute="_compute_contador_count")
    lectura_count = fields.Integer(string="Lecturas", compute="_compute_lectura_count")
    activo = fields.Boolean(string='Activo', default=True)

    _sql_constraints = [
        ('referencia_unica', 'unique(name)', "Esta residencia ya existe, por favor especifica otro Nombre/Codigo")
    ]

    def _compute_contador_count(self):
        Contador = self.env['asovec.contador'].sudo()
        for rec in self:
            rec.contador_count = Contador.search_count([('residencia_id', '=', rec.id)])

    def _compute_lectura_count(self):
        Line = self.env['asovec.contador.lines'].sudo()
        for rec in self:
            rec.lectura_count = Line.search_count([('residencia_id', '=', rec.id)])

    def action_ver_contadores(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Contadores',
            'res_model': 'asovec.contador',
            'view_mode': 'tree,form',
            'domain': [('residencia_id', '=', self.id)],
            'context': {'default_residencia_id': self.id},
        }

    def action_ver_lecturas(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lecturas',
            'res_model': 'asovec.contador.lines',
            'view_mode': 'tree,form',
            'domain': [('residencia_id', '=', self.id)],
            'context': {'default_residencia_id': self.id},
        }

    def action_nueva_lectura(self):
        self.ensure_one()

        Contador = self.env['asovec.contador']

        contador = Contador.search([
            ('residencia_id', '=', self.id),
            ('active', '=', True),
        ], limit=1)

        if not contador:
            contador = Contador.search([
                ('residencia_id', '=', self.id),
            ], order='id desc', limit=1)

        if not contador:
            raise ValidationError("Esta residencia no tiene contador. Cree uno (y actívelo) antes de ingresar lecturas.")

        return {
            'type': 'ir.actions.act_window',
            'name': 'Nueva Lectura',
            'res_model': 'asovec.contador.lines',
            'view_mode': 'form',
            'target': 'current',  # cambia a 'new' si lo querés en popup
            'context': {
                'default_contador_id': contador.id,
                'default_fecha_lectura': fields.Date.context_today(self),
            },
        }


class ResidenciaLines(models.Model):
    _name = 'asovec.residencia.lines'

    producto_id = fields.Many2one(string="Servicio", comodel_name='product.template', required=True, domain=[('aso_es_servicio_aso', '=', True)])
    company_id = fields.Many2one("res.company", string="Compañía", required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one("res.currency", string="Moneda", related="company_id.currency_id", store=True, readonly=True)
    precio = fields.Monetary(string="Precio", default=0, currency_field="currency_id", required=True)
    residencia_id = fields.Many2one(comodel_name='asovec.residencia')

    @api.onchange('producto_id')
    def _onchange_product_id(self):
        for line in self:
            line.precio = self.producto_id.list_price
