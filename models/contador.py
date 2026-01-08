# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class Contador(models.Model):
    _name = 'asovec.contador'
    _description = 'Contador por Residencia'
    _order = 'id desc'

    name = fields.Char(string="Contador", required=True)
    active = fields.Boolean(string="Activo", default=True)
    residencia_id = fields.Many2one('asovec.residencia', string="Residencia", required=True, ondelete='cascade', index=True)
    cliente_id = fields.Many2one(comodel_name='res.partner', string="Contacto", related='residencia_id.cliente_id', readonly=True, store=False)
    proyecto_aso_id = fields.Many2one(comodel_name='asovec.proyecto_aso', string="Proyecto", related='residencia_id.proyecto_aso_id', readonly=True, store=False)

    line_ids = fields.One2many('asovec.contador.lines', 'contador_id', string='Lecturas')

    ultima_lectura = fields.Float(string="Última lectura", compute="_compute_ultima", readonly=True)
    ultimo_consumo = fields.Float(string="Último consumo", compute="_compute_ultima", readonly=True)
    ultima_fecha = fields.Date(string="Última fecha", compute="_compute_ultima", readonly=True)

    @api.depends('line_ids.fecha_lectura', 'line_ids.lectura', 'line_ids.consumo')
    def _compute_ultima(self):
        for rec in self:
            last = rec.line_ids.sorted(lambda l: (l.fecha_lectura or fields.Date.today(), l.id))[-1:]
            last = last[0] if last else False
            rec.ultima_lectura = last.lectura if last else 0.0
            rec.ultimo_consumo = last.consumo if last else 0.0
            rec.ultima_fecha = last.fecha_lectura if last else False

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
        return {
            'type': 'ir.actions.act_window',
            'name': 'Nueva Lectura',
            'res_model': 'asovec.contador.lines',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_contador_id': self.id,
                'default_fecha_lectura': fields.Date.context_today(self),
            },
        }


class ContadorLine(models.Model):
    _name = 'asovec.contador.lines'
    _description = 'Histórico de Lecturas del Contador'
    _order = 'fecha_lectura desc, id desc'

    contador_id = fields.Many2one('asovec.contador', string="Contador", required=True, ondelete='cascade', index=True)
    residencia_id = fields.Many2one('asovec.residencia', related='contador_id.residencia_id', store=True, readonly=True)
    cliente_id = fields.Many2one(comodel_name='res.partner', string="Contacto", related='residencia_id.cliente_id', store=True, readonly=True)
    proyecto_aso_id = fields.Many2one(comodel_name='asovec.proyecto_aso', string="Proyecto", related='residencia_id.proyecto_aso_id', store=True, readonly=True)

    fecha_lectura = fields.Date(string="Fecha de lectura", required=True, default=fields.Date.context_today, index=True)
    lectura = fields.Float(string="Lectura actual", required=True, default=0.0)

    lectura_anterior = fields.Float(string="Lectura anterior", default=0.0, readonly=True)
    consumo = fields.Float(string="Consumo", default=0.0, readonly=True)

    base = fields.Float(string="Base", default=0.0, readonly=True)
    metros_extras = fields.Float(string="Metros extras", default=0.0, readonly=True)
    pago_extra = fields.Float(string="Pago extra", default=0.0, readonly=True)
    pago_total = fields.Float(string="Pago total", default=0.0, readonly=True)

    def _get_last_line(self, contador_id, exclude_id=None):
        domain = [('contador_id', '=', contador_id)]
        if exclude_id:
            domain.append(('id', '!=', exclude_id))
        return self.search(domain, order='fecha_lectura desc, id desc', limit=1)

    def _calcular_campos_linea(self, contador, lectura_actual, lectura_anterior):
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
    # PREVIEW EN FORM (SIN GUARDAR)
    # -------------------------

    @api.onchange('contador_id')
    def _onchange_contador_id_preview(self):
        for rec in self:
            if not rec.contador_id:
                continue

            # Si es nueva (no guardada), traer lectura anterior del último registro
            if not rec._origin or not rec._origin.id:
                last = rec._get_last_line(rec.contador_id.id)
                rec.lectura_anterior = last.lectura if last else 0.0

            # Recalcular preview en pantalla (también para edit de viejas)
            calc = rec._calcular_campos_linea(rec.contador_id, rec.lectura or 0.0, rec.lectura_anterior or 0.0)
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
            calc = rec._calcular_campos_linea(rec.contador_id, rec.lectura or 0.0, rec.lectura_anterior or 0.0)
            rec.consumo = calc['consumo']
            rec.base = calc['base']
            rec.metros_extras = calc['metros_extras']
            rec.pago_extra = calc['pago_extra']
            rec.pago_total = calc['pago_total']

    # -------------------------
    # GUARDADO (SIN RECALCULAR HISTORIA)
    # -------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            contador_id = vals.get('contador_id')
            lectura_actual = vals.get('lectura', 0.0)

            if not contador_id:
                raise ValidationError("Debe seleccionar un Contador.")

            last = self._get_last_line(contador_id)
            lectura_anterior = last.lectura if last else 0.0

            if (lectura_actual or 0.0) < (lectura_anterior or 0.0):
                raise ValidationError(
                    f"La lectura ({lectura_actual}) no puede ser menor que la lectura anterior ({lectura_anterior}). "
                    "Si necesita corregir, borre o ajuste manualmente la lectura anterior."
                )

            contador = self.env['asovec.contador'].browse(contador_id)
            vals.update(self._calcular_campos_linea(contador, lectura_actual, lectura_anterior))

        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)

        # Si no cambia nada relevante, salir
        if not any(k in vals for k in ('lectura', 'contador_id')):
            return res

        for rec in self:
            # Si cambiaron el contador, recalcular lectura_anterior desde el último del NUEVO contador
            if 'contador_id' in vals:
                if not rec.contador_id:
                    continue
                last = rec._get_last_line(rec.contador_id.id, exclude_id=rec.id)
                rec.lectura_anterior = last.lectura if last else 0.0

            # Validación SIEMPRE contra la lectura_anterior guardada en ESTA línea (historia fija)
            if (rec.lectura or 0.0) < (rec.lectura_anterior or 0.0):
                raise ValidationError(
                    f"La lectura ({rec.lectura}) no puede ser menor que la lectura anterior ({rec.lectura_anterior}). "
                    "Si necesita corregir, ajuste manualmente la lectura anterior o borre registros."
                )

            calc = rec._calcular_campos_linea(rec.contador_id, rec.lectura or 0.0, rec.lectura_anterior or 0.0)
            super(ContadorLine, rec).write({
                'consumo': calc['consumo'],
                'base': calc['base'],
                'metros_extras': calc['metros_extras'],
                'pago_extra': calc['pago_extra'],
                'pago_total': calc['pago_total'],
                # lectura_anterior solo se escribe si cambió contador_id (arriba)
            })

        return res
