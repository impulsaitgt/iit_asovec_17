# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError


class Residencia(models.Model):
    _name = 'asovec.residencia'

    name = fields.Char(string="Nombre/Codigo", required=True)
    direccion = fields.Char(string="Direccion")
    direccion_real = fields.Char(string="Dirección Real", compute="_compute_direccion_real", store=True)
    sector = fields.Integer(string="Sector")
    calle = fields.Char(string="Calle")
    no_casa = fields.Char(string="No. Casa")
    detalle = fields.Text(string="Informacion Detallada")
    proyecto_aso_id = fields.Many2one(string="Proyecto", comodel_name='asovec.proyecto_aso', required=True)
    cliente_id = fields.Many2one(comodel_name='res.partner', string="Contacto", required=False)
    residencia_lines = fields.One2many(comodel_name="asovec.residencia.lines", inverse_name="residencia_id")
    contadores_ids = fields.One2many(comodel_name='asovec.contador', inverse_name='residencia_id', string='Contadores')
    contador_count = fields.Integer(string="Contadores", compute="_compute_contador_count")
    lectura_count = fields.Integer(string="Lecturas", compute="_compute_lectura_count")
    activo = fields.Boolean(string='Activo', default=True)
    no_paga_servicios = fields.Boolean(
        string='No paga servicios',
        default=False,
        help="Si se marca, esta residencia se excluye por completo del cálculo de "
             "facturas (no genera cargo ni siquiera como Inactivo). Es distinto de "
             "'Activo': una residencia Inactiva sigue pagando su cuota de inactivo; "
             "una residencia 'No paga servicios' no genera ningún cargo. Tiene "
             "prioridad sobre 'Sin contador': al marcarla, apaga 'Sin contador' y "
             "vuelve a activar la residencia.",
    )
    sin_contador = fields.Boolean(
        string='Sin contador',
        default=False,
        help="Residencia sin contador de agua: solo genera la cuota de contador "
             "inactivo, ignorando los servicios automáticos (basura, mantenimiento, "
             "etc.). Al marcarla, la residencia pasa a Inactivo y ese campo queda "
             "bloqueado mientras 'Sin contador' esté activo.",
    )
    metros_especiales = fields.Boolean(
        string='Metro base propio',
        default=False,
        help="Si se marca, esta residencia usa su propio 'Metros base (derecho)' en vez del "
             "configurado en el proyecto.",
    )
    metros_especiales_cantidad = fields.Integer(
        string='Metros base (derecho)',
        default=0,
        help="Metros base (derecho) que se usan al calcular el consumo en exceso de esta "
             "residencia. Por defecto sigue al del proyecto; si se marca 'Metro base propio' "
             "se puede definir uno distinto para esta residencia.",
    )
    currency_id = fields.Many2one(
        "res.currency", string="Moneda",
        related="proyecto_aso_id.currency_id", readonly=True,
    )
    cobro_base_especial = fields.Boolean(
        string='Canon de agua propio',
        default=False,
        help="Si se marca, esta residencia usa su propio 'Canon de agua (valor propio)' en "
             "vez del 'Cobro Base' configurado en el proyecto.",
    )
    cobro_base_especial_valor = fields.Monetary(
        string='Canon de agua (valor propio)',
        currency_field="currency_id",
        default=0,
        help="Valor de canon de agua (cobro base) propio de esta residencia. Por defecto "
             "sigue al del proyecto; si se marca 'Canon de agua propio' se puede definir uno "
             "distinto para esta residencia, y se usará al calcular la factura mensual.",
    )
    exonera_exceso_agua = fields.Boolean(
        string='Exonera Exceso Agua',
        default=False,
        help="Si se marca, esta residencia nunca paga por consumo en exceso: aunque la "
             "lectura registre metros por encima del derecho base, el exceso y su cobro se "
             "asignan en cero y no se genera la línea de exceso en el cargo.",
    )

    @api.depends('direccion', 'calle', 'no_casa', 'proyecto_aso_id.name')
    def _compute_direccion_real(self):
        for rec in self:
            if rec.direccion:
                rec.direccion_real = rec.direccion
            else:
                rec.direccion_real = " ".join(filter(None, [
                    rec.calle,
                    rec.no_casa,
                    rec.proyecto_aso_id.name,
                ]))

    @api.onchange('no_paga_servicios')
    def _onchange_no_paga_servicios(self):
        for rec in self:
            if rec.no_paga_servicios:
                rec.sin_contador = False
                rec.activo = True

    @api.onchange('sin_contador')
    def _onchange_sin_contador(self):
        for rec in self:
            if rec.sin_contador and not rec.no_paga_servicios:
                rec.activo = False

    @api.onchange('metros_especiales')
    def _onchange_metros_especiales(self):
        if not self.metros_especiales:
            self.metros_especiales_cantidad = self.proyecto_aso_id.metro_base if self.proyecto_aso_id else 0

    @api.onchange('cobro_base_especial')
    def _onchange_cobro_base_especial(self):
        if not self.cobro_base_especial:
            self.cobro_base_especial_valor = self.proyecto_aso_id.cobro_base if self.proyecto_aso_id else 0

    @api.onchange('proyecto_aso_id')
    def _onchange_proyecto_aso_id_metro_base(self):
        for rec in self:
            if not rec.metros_especiales:
                rec.metros_especiales_cantidad = rec.proyecto_aso_id.metro_base if rec.proyecto_aso_id else 0
            if not rec.cobro_base_especial:
                rec.cobro_base_especial_valor = rec.proyecto_aso_id.cobro_base if rec.proyecto_aso_id else 0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('proyecto_aso_id') and (
                (not vals.get('metros_especiales') and 'metros_especiales_cantidad' not in vals)
                or (not vals.get('cobro_base_especial') and 'cobro_base_especial_valor' not in vals)
            ):
                proyecto = self.env['asovec.proyecto_aso'].browse(vals['proyecto_aso_id'])
                if not vals.get('metros_especiales') and 'metros_especiales_cantidad' not in vals:
                    vals['metros_especiales_cantidad'] = proyecto.metro_base
                if not vals.get('cobro_base_especial') and 'cobro_base_especial_valor' not in vals:
                    vals['cobro_base_especial_valor'] = proyecto.cobro_base

            if vals.get('no_paga_servicios'):
                vals['sin_contador'] = False
                vals['activo'] = True
            elif vals.get('sin_contador'):
                vals['activo'] = False
        return super().create(vals_list)

    def _aplicar_jerarquia_flags(self):
        """Garantiza la jerarquía No paga servicios > Sin contador > Activo sin importar
        si el campo se estableció desde el formulario (onchange), una importación o la
        API: No paga servicios siempre apaga Sin contador y activa la residencia; Sin
        contador (sin No paga servicios) siempre inactiva la residencia."""
        for rec in self:
            correccion = {}
            if rec.no_paga_servicios:
                if rec.sin_contador:
                    correccion['sin_contador'] = False
                if not rec.activo:
                    correccion['activo'] = True
            elif rec.sin_contador and rec.activo:
                correccion['activo'] = False
            if correccion:
                rec.write(correccion)

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

        contadores_a_desactivar = self.env['asovec.contador']
        if vals.get('activo') is False:
            residencias_previamente_activas = self.filtered(lambda r: r.activo)
            if residencias_previamente_activas:
                contadores_a_desactivar = self.env['asovec.contador'].search([
                    ('residencia_id', 'in', residencias_previamente_activas.ids),
                    ('active', '=', True),
                ])

        res = super().write(vals)

        if contadores_a_desactivar:
            contadores_a_desactivar.write({'active': False})

        if 'no_paga_servicios' in vals or 'sin_contador' in vals:
            self._aplicar_jerarquia_flags()

        return res

    def _compute_contador_count(self):
        Contador = self.env['asovec.contador'].sudo()
        for rec in self:
            rec.contador_count = Contador.search_count([('residencia_id', '=', rec.id)])

    def _compute_lectura_count(self):
        Line = self.env['asovec.contador.lines'].sudo()
        for rec in self:
            rec.lectura_count = Line.search_count([
                ('residencia_id', '=', rec.id), ('contador_id.active', '=', True),
            ])

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
            'domain': [('residencia_id', '=', self.id), ('contador_id.active', '=', True)],
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

        vista_operador = self.env.ref('iit_asovec.asovec_contador_lines_form_view_operador')

        return {
            'type': 'ir.actions.act_window',
            'name': 'Nueva Lectura',
            'res_model': 'asovec.contador.lines',
            'view_mode': 'form',
            'views': [(vista_operador.id, 'form')],
            'target': 'current',  # cambia a 'new' si lo querés en popup
            'context': {
                'default_contador_id': contador.id,
                'default_fecha_lectura': fields.Date.context_today(self),
            },
        }
    
    def action_print_estado_cuenta_lecturas(self):
        self.ensure_one()
        return self.env.ref("iit_asovec.action_report_estado_cuenta_residencia_lecturas").report_action(self)

    def action_abrir_recibo_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Imprimir Recibo Mensual',
            'res_model': 'asovec.residencia_recibo_wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_residencia_id': self.id},
        }

    def action_abrir_recibo_detallado_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Imprimir Recibo Mensual Detallado',
            'res_model': 'asovec.residencia_recibo_wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_residencia_id': self.id, 'default_detallado': True},
        }

    def action_abrir_estado_cuenta_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Estado de Cuenta',
            'res_model': 'asovec.cobro_mensual_consulta_wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_residencia_ids': [(6, 0, [self.id])],
                'default_proyecto_aso_id': self.proyecto_aso_id.id,
            },
        }


class ResidenciaLines(models.Model):
    _name = 'asovec.residencia.lines'

    producto_id = fields.Many2one(string="Servicio", comodel_name='product.template', required=True, domain=[('aso_es_servicio_aso', '=', True), ('aso_automatico', '=', True), ('aso_activo', '=', True)])
    company_id = fields.Many2one("res.company", string="Compañía", required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one("res.currency", string="Moneda", related="company_id.currency_id", store=True, readonly=True)
    precio = fields.Monetary(string="Precio", default=0, currency_field="currency_id", required=True)
    residencia_id = fields.Many2one(comodel_name='asovec.residencia')

    @api.onchange('producto_id')
    def _onchange_product_id(self):
        for line in self:
            line.precio = self.producto_id.list_price
