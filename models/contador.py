# -*- coding: utf-8 -*-
from datetime import date
from odoo import models, fields, api
from odoo.exceptions import ValidationError


MONTH_SELECTION = [
    ('1', 'Enero'), ('2', 'Febrero'), ('3', 'Marzo'), ('4', 'Abril'),
    ('5', 'Mayo'), ('6', 'Junio'), ('7', 'Julio'), ('8', 'Agosto'),
    ('9', 'Septiembre'), ('10', 'Octubre'), ('11', 'Noviembre'), ('12', 'Diciembre'),
]


class Contador(models.Model):
    _name = 'asovec.contador'
    _description = 'Contador por Residencia'
    _order = 'id desc'

    name = fields.Char(string="Contador", required=True)
    active = fields.Boolean(string="Activo", default=True)
    residencia_id = fields.Many2one(
        'asovec.residencia', string="Residencia", required=True,
        ondelete='cascade', index=True
    )
    cliente_id = fields.Many2one(
        comodel_name='res.partner', string="Contacto",
        related='residencia_id.cliente_id', readonly=True, store=False
    )
    proyecto_aso_id = fields.Many2one(
        comodel_name='asovec.proyecto_aso', string="Proyecto",
        related='residencia_id.proyecto_aso_id', readonly=True, store=False
    )

    line_ids = fields.One2many('asovec.contador.lines', 'contador_id', string='Lecturas')

    ultima_lectura = fields.Float(string="Última lectura", compute="_compute_ultima", readonly=True)
    ultimo_consumo = fields.Float(string="Último consumo", compute="_compute_ultima", readonly=True)
    ultima_fecha = fields.Date(string="Último período", compute="_compute_ultima", readonly=True)

    tiene_inicial = fields.Boolean(string="Tiene inicial", compute="_compute_tiene_inicial", store=True, readonly=True)

    @api.depends('line_ids.es_inicial')
    def _compute_tiene_inicial(self):
        for rec in self:
            rec.tiene_inicial = any(rec.line_ids.filtered('es_inicial'))

    @api.depends('line_ids.periodo_date', 'line_ids.lectura', 'line_ids.consumo', 'line_ids.es_inicial')
    def _compute_ultima(self):
        for rec in self:
            mensuales = rec.line_ids.filtered(lambda l: not l.es_inicial and l.periodo_date)
            if mensuales:
                last = mensuales.sorted(lambda l: (l.periodo_date, l.id))[-1]
            else:
                last = rec.line_ids.sorted(lambda l: (l.id,))[-1] if rec.line_ids else False

            rec.ultima_lectura = last.lectura if last else 0.0
            rec.ultimo_consumo = last.consumo if last else 0.0
            rec.ultima_fecha = last.periodo_date if (last and last.periodo_date) else False

    def _desactivar_otros_activos(self):
        for rec in self:
            if rec.active and rec.residencia_id:
                self.search([
                    ('id', '!=', rec.id),
                    ('residencia_id', '=', rec.residencia_id.id),
                    ('active', '=', True),
                ]).write({'active': False})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('active', True) and vals.get('residencia_id'):
                self.search([
                    ('residencia_id', '=', vals['residencia_id']),
                    ('active', '=', True),
                ]).write({'active': False})
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if vals.get('active') is True:
            self._desactivar_otros_activos()
        return res

    def action_activar(self):
        for rec in self:
            rec.active = True
            rec._desactivar_otros_activos()

    def action_desactivar(self):
        self.write({'active': False})

    def action_nueva_lectura(self):
        self.ensure_one()
        Line = self.env['asovec.contador.lines']
        next_mes, next_anio = Line._next_period_for_contador(self.id)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Nueva Lectura',
            'res_model': 'asovec.contador.lines',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_contador_id': self.id,
                'default_mes': next_mes,
                'default_anio': next_anio,
                'default_es_inicial': False,
            },
        }

    def action_registro_inicial(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Registro Inicial',
            'res_model': 'asovec.contador.lines',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_contador_id': self.id,
                'default_es_inicial': True,
            },
        }


class ContadorLine(models.Model):
    _name = 'asovec.contador.lines'
    _description = 'Histórico de Lecturas del Contador'
    _order = 'periodo_date desc, id desc'

    contador_id = fields.Many2one('asovec.contador', string="Contador", required=True, ondelete='cascade', index=True)
    residencia_id = fields.Many2one('asovec.residencia', related='contador_id.residencia_id', store=True, readonly=True)
    cliente_id = fields.Many2one(comodel_name='res.partner', string="Contacto", related='residencia_id.cliente_id', store=True, readonly=True)
    proyecto_aso_id = fields.Many2one(comodel_name='asovec.proyecto_aso', string="Proyecto", related='residencia_id.proyecto_aso_id', store=True, readonly=True)

    es_inicial = fields.Boolean(string="Registro inicial", default=False)

    mes = fields.Selection(MONTH_SELECTION, string="Mes")
    anio = fields.Integer(string="Año")
    periodo_date = fields.Date(string="Período", compute="_compute_periodo_date", store=True, index=True)

    lectura = fields.Float(string="Lectura actual", required=True, default=0.0)
    lectura_anterior = fields.Float(string="Lectura anterior", default=0.0, readonly=True)
    consumo = fields.Float(string="Consumo", default=0.0, readonly=True)

    company_id = fields.Many2one("res.company", string="Compañía", required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one("res.currency", string="Moneda", related="company_id.currency_id", store=True, readonly=True)

    base = fields.Monetary(string="Base", default=0.0, currency_field="currency_id", readonly=True)
    metros_extras = fields.Float(string="Metros extras", default=0.0, readonly=True)
    pago_extra = fields.Monetary(string="Pago extra", default=0.0, currency_field="currency_id", readonly=True)
    pago_total = fields.Monetary(string="Pago total", default=0.0, currency_field="currency_id", readonly=True)

    # -------------------------
    # Facturación / pago (badges estilo Odoo)
    # -------------------------
    invoice_line_ids = fields.One2many(
        comodel_name="account.move.line",
        inverse_name="contador_line_id",
        string="Líneas de factura",
        readonly=True,
    )
    invoice_line_count = fields.Integer(string="Líneas", compute="_compute_invoice_info", readonly=True)

    invoice_move_id = fields.Many2one(
        comodel_name="account.move",
        string="Factura",
        compute="_compute_invoice_info",
        readonly=True,
    )

    invoice_status_badge = fields.Selection(
        selection=[("not_invoiced", "No facturado"), ("invoiced", "Facturado")],
        string="Facturación",
        compute="_compute_invoice_info",
        readonly=True,
    )

    payment_status_badge = fields.Selection(
        selection=[("unpaid", "No pagado"), ("paid", "Pagado")],
        string="Pago",
        compute="_compute_invoice_info",
        readonly=True,
    )

    @api.depends("invoice_line_ids.move_id.payment_state")
    def _compute_invoice_info(self):
        for rec in self:
            lines = rec.invoice_line_ids
            rec.invoice_line_count = len(lines)

            if lines:
                line = lines.sorted(lambda l: (l.move_id.id or 0, l.id))[0]
                rec.invoice_move_id = line.move_id

                rec.invoice_status_badge = "invoiced"
                rec.payment_status_badge = "paid" if rec.invoice_move_id.payment_state == "paid" else "unpaid"
            else:
                rec.invoice_move_id = False
                rec.invoice_status_badge = "not_invoiced"
                rec.payment_status_badge = "unpaid"

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_move_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": "Factura",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.invoice_move_id.id,
        }

    def action_view_invoice_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Líneas de factura",
            "res_model": "account.move.line",
            "view_mode": "tree,form",
            "domain": [("contador_line_id", "=", self.id)],
            "context": {"search_default_group_by_move_id": 1},
        }

    # -------------------------
    # Período
    # -------------------------
    @api.depends('mes', 'anio', 'es_inicial')
    def _compute_periodo_date(self):
        for rec in self:
            if rec.es_inicial:
                rec.periodo_date = False
                continue
            if rec.mes and rec.anio:
                rec.periodo_date = date(int(rec.anio), int(rec.mes), 1)
            else:
                rec.periodo_date = False

    # -------------------------
    # Helpers período
    # -------------------------
    @api.model
    def _last_mensual(self, contador_id, exclude_id=None):
        domain = [('contador_id', '=', contador_id), ('es_inicial', '=', False), ('periodo_date', '!=', False)]
        if exclude_id:
            domain.append(('id', '!=', exclude_id))
        return self.search(domain, order='periodo_date desc, id desc', limit=1)

    @api.model
    def _get_inicial(self, contador_id, exclude_id=None):
        domain = [('contador_id', '=', contador_id), ('es_inicial', '=', True)]
        if exclude_id:
            domain.append(('id', '!=', exclude_id))
        return self.search(domain, order='id desc', limit=1)

    @api.model
    def _next_period_for_contador(self, contador_id):
        last = self._last_mensual(contador_id)
        today = fields.Date.context_today(self)
        if not last:
            return str(today.month), int(today.year)
        y = int(last.anio)
        m = int(last.mes)
        if m == 12:
            return "1", y + 1
        return str(m + 1), y

    # -------------------------
    # Validaciones
    # -------------------------
    @api.model
    def _validate_periodo_vals(self, vals, exclude_id=None):
        contador_id = vals.get('contador_id')
        if not contador_id:
            raise ValidationError("Debe seleccionar un Contador.")

        es_inicial = bool(vals.get('es_inicial', False))

        if es_inicial:
            domain_ini = [('contador_id', '=', contador_id), ('es_inicial', '=', True)]
            if exclude_id:
                domain_ini.append(('id', '!=', exclude_id))
            other_ini = self.search(domain_ini, limit=1)
            if other_ini:
                raise ValidationError("Ya existe un registro inicial para este contador.")
            return

        mes = vals.get('mes')
        anio = vals.get('anio')
        if not mes or not anio:
            raise ValidationError("Debe seleccionar Mes y Año para una lectura mensual.")

        domain_dup = [
            ('contador_id', '=', contador_id),
            ('es_inicial', '=', False),
            ('mes', '=', mes),
            ('anio', '=', anio),
        ]
        if exclude_id:
            domain_dup.append(('id', '!=', exclude_id))
        dup = self.search(domain_dup, limit=1)
        if dup:
            raise ValidationError("Ya existe una lectura para ese Mes/Año en este contador.")

        last = self._last_mensual(contador_id, exclude_id=exclude_id)
        if last:
            exp_m, exp_y = self._next_period_for_contador(contador_id)
            if str(mes) != str(exp_m) or int(anio) != int(exp_y):
                raise ValidationError(
                    f"El siguiente período debe ser {exp_m}/{exp_y}. No se permiten saltos de meses."
                )

    # -------------------------
    # Cálculos
    # -------------------------
    def _calcular_campos_linea(self, contador, lectura_actual, lectura_anterior, es_inicial=False):
        if es_inicial:
            return {
                'lectura_anterior': 0.0,
                'consumo': 0.0,
                'base': 0.0,
                'metros_extras': 0.0,
                'pago_extra': 0.0,
                'pago_total': 0.0,
            }

        residencia = contador.residencia_id
        proyecto = residencia.proyecto_aso_id if residencia else False

        cobro_base = float(getattr(proyecto, 'cobro_base', 0.0) or 0.0) if proyecto else 0.0
        precio_maestro = float(getattr(proyecto, 'precio_metro', 0.0) or 0.0) if proyecto else 0.0
        metro_base = float(getattr(proyecto, 'metro_base', 0.0) or 0.0) if proyecto else 0.0

        consumo = (lectura_actual or 0.0) - (lectura_anterior or 0.0)

        base = cobro_base
        metros_extras = consumo - metro_base
        if metros_extras < 0:
            metros_extras = 0.0

        pago_extra = metros_extras * precio_maestro
        pago_total = base + pago_extra

        return {
            'lectura_anterior': lectura_anterior or 0.0,
            'consumo': consumo,
            'base': base,
            'metros_extras': metros_extras,
            'pago_extra': pago_extra,
            'pago_total': pago_total,
        }

    # -------------------------
    # PREVIEW
    # -------------------------
    @api.onchange('contador_id', 'es_inicial', 'mes', 'anio')
    def _onchange_periodo_preview(self):
        for rec in self:
            if not rec.contador_id:
                continue

            if rec.es_inicial:
                rec.mes = False
                rec.anio = False
                rec.lectura_anterior = 0.0
                calc = rec._calcular_campos_linea(
                    rec.contador_id,
                    rec.lectura or 0.0,
                    0.0,
                    es_inicial=True
                )
                rec.consumo = calc['consumo']
                rec.base = calc['base']
                rec.metros_extras = calc['metros_extras']
                rec.pago_extra = calc['pago_extra']
                rec.pago_total = calc['pago_total']
                continue

            if (not rec._origin or not rec._origin.id) and (not rec.mes or not rec.anio):
                nm, ny = self._next_period_for_contador(rec.contador_id.id)
                rec.mes = rec.mes or nm
                rec.anio = rec.anio or ny

            last_m = self._last_mensual(rec.contador_id.id)
            if last_m:
                rec.lectura_anterior = last_m.lectura or 0.0
            else:
                ini = self._get_inicial(rec.contador_id.id)
                rec.lectura_anterior = (ini.lectura or 0.0) if ini else 0.0

            calc = rec._calcular_campos_linea(
                rec.contador_id,
                rec.lectura or 0.0,
                rec.lectura_anterior or 0.0,
                es_inicial=False
            )
            rec.consumo = calc['consumo']
            rec.base = calc['base']
            rec.metros_extras = calc['metros_extras']
            rec.pago_extra = calc['pago_extra']
            rec.pago_total = calc['pago_total']

    @api.onchange('lectura')
    def _onchange_lectura_preview(self):
        for rec in self:
            if not rec.contador_id:
                continue
            calc = rec._calcular_campos_linea(
                rec.contador_id,
                rec.lectura or 0.0,
                rec.lectura_anterior or 0.0,
                es_inicial=rec.es_inicial
            )
            rec.consumo = calc['consumo']
            rec.base = calc['base']
            rec.metros_extras = calc['metros_extras']
            rec.pago_extra = calc['pago_extra']
            rec.pago_total = calc['pago_total']

    # -------------------------
    # CREATE / WRITE
    # -------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            contador_id = vals.get('contador_id')
            lectura_actual = vals.get('lectura', 0.0)
            es_inicial = bool(vals.get('es_inicial', False))

            if not contador_id:
                raise ValidationError("Debe seleccionar un Contador.")

            self._validate_periodo_vals(vals, exclude_id=None)

            if es_inicial:
                lectura_anterior = 0.0
            else:
                last_m = self._last_mensual(contador_id)
                if last_m:
                    lectura_anterior = last_m.lectura or 0.0
                else:
                    ini = self._get_inicial(contador_id)
                    lectura_anterior = (ini.lectura or 0.0) if ini else 0.0

            if (lectura_actual or 0.0) < (lectura_anterior or 0.0):
                raise ValidationError(
                    f"La lectura ({lectura_actual}) no puede ser menor que la lectura anterior ({lectura_anterior})."
                )

            contador = self.env['asovec.contador'].browse(contador_id)
            vals.update(self._calcular_campos_linea(contador, lectura_actual, lectura_anterior, es_inicial=es_inicial))

        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)

        if not any(k in vals for k in ('lectura', 'contador_id', 'es_inicial', 'mes', 'anio')):
            return res

        for rec in self:
            final_vals = {
                'contador_id': vals.get('contador_id', rec.contador_id.id),
                'es_inicial': vals.get('es_inicial', rec.es_inicial),
                'mes': vals.get('mes', rec.mes),
                'anio': vals.get('anio', rec.anio),
            }
            rec._validate_periodo_vals(final_vals, exclude_id=rec.id)

            is_ini = bool(final_vals.get('es_inicial'))
            lectura_anterior = 0.0 if is_ini else (rec.lectura_anterior or 0.0)

            if (rec.lectura or 0.0) < (lectura_anterior or 0.0):
                raise ValidationError(
                    f"La lectura ({rec.lectura}) no puede ser menor que la lectura anterior ({lectura_anterior})."
                )

            calc = rec._calcular_campos_linea(
                rec.contador_id,
                rec.lectura or 0.0,
                lectura_anterior,
                es_inicial=is_ini
            )

            super(ContadorLine, rec).write({
                'lectura_anterior': calc['lectura_anterior'],
                'consumo': calc['consumo'],
                'base': calc['base'],
                'metros_extras': calc['metros_extras'],
                'pago_extra': calc['pago_extra'],
                'pago_total': calc['pago_total'],
            })

        return res
