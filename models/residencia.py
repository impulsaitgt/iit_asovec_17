# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError


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

    def write(self, vals):
        # Solo validar si están intentando cambiar el cliente
        if "cliente_id" in vals:
            # Solo para residencias donde realmente cambia
            residencias_a_validar = self.filtered(lambda r: r.cliente_id.id != vals.get("cliente_id"))

            if residencias_a_validar:
                # Suma saldo pendiente: asovec.proyecto_cobro_mensual con total_balance > 0
                domain = [
                    ("residencia_id", "in", residencias_a_validar.ids),
                    ("amount_balance", ">", 0),
                ]

                data = self.env["asovec.proyecto_cobro_mensual_line"].read_group(
                    domain=domain,
                    fields=["amount_balance:sum", "residencia_id"],
                    groupby=["residencia_id"],
                )

                saldo_por_res = {d["residencia_id"][0]: d["amount_balance"] for d in data}

                # Si cualquiera tiene saldo, bloquear
                con_saldo = [r for r in residencias_a_validar if saldo_por_res.get(r.id, 0) > 0]
                if con_saldo:
                    # mensaje simple (puedes hacerlo más detallado)
                    raise UserError("No se puede cambiar el cliente.\n"
                                    "La residencia tiene cobros pendientes.\n"
                                    "Liquide el saldo antes de realizar el cambio.")

        return super().write(vals)

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
    
    def action_cargar_servicios_asociacion(self):
        self.ensure_one()

        # 1) Borrar líneas actuales
        self.residencia_lines.unlink()

        # 2) Buscar productos marcados como servicio ASO
        productos = self.env['product.template'].search([
            ('aso_es_servicio_aso', '=', True),
            ('aso_automatico', '=', True),
            ('active', '=', True)
        ])

        # 3) Crear una línea por producto con su precio de lista
        lines_vals = []
        for p in productos:
            lines_vals.append((0, 0, {
                'producto_id': p.id,
                'precio': p.list_price,
            }))

        self.write({'residencia_lines': lines_vals})

        # opcional: notificación
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_print_estado_cuenta_lecturas(self):
        self.ensure_one()
        return self.env.ref("iit_asovec.action_report_estado_cuenta_residencia_lecturas").report_action(self)


class ResidenciaLines(models.Model):
    _name = 'asovec.residencia.lines'

    producto_id = fields.Many2one(string="Servicio", comodel_name='product.template', required=True, domain=[('aso_es_servicio_aso', '=', True), ('aso_automatico', '=', True)])
    company_id = fields.Many2one("res.company", string="Compañía", required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one("res.currency", string="Moneda", related="company_id.currency_id", store=True, readonly=True)
    precio = fields.Monetary(string="Precio", default=0, currency_field="currency_id", required=True)
    residencia_id = fields.Many2one(comodel_name='asovec.residencia')

    @api.onchange('producto_id')
    def _onchange_product_id(self):
        for line in self:
            line.precio = self.producto_id.list_price
