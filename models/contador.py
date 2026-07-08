# -*- coding: utf-8 -*-
from datetime import date
from odoo import models, fields, api
from odoo.exceptions import ValidationError


MONTH_SELECTION = [
    ('1', 'Enero'), ('2', 'Febrero'), ('3', 'Marzo'), ('4', 'Abril'),
    ('5', 'Mayo'), ('6', 'Junio'), ('7', 'Julio'), ('8', 'Agosto'),
    ('9', 'Septiembre'), ('10', 'Octubre'), ('11', 'Noviembre'), ('12', 'Diciembre'),
]


def mes_anio_anterior(today):
    """Devuelve (mes, anio) del mes anterior a `today`, como (str, int)."""
    mes = today.month - 1
    anio = today.year
    if mes < 1:
        mes = 12
        anio -= 1
    return str(mes), anio


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

    def init(self):
        # Defensa adicional a nivel de base de datos: nunca debe existir más de un
        # contador activo por residencia, incluso si algo escribe sin pasar por el ORM.
        self._cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS asovec_contador_one_active_per_residencia
            ON asovec_contador (residencia_id)
            WHERE active IS TRUE
        """)

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

    def _check_no_other_active(self, residencia_id, exclude_id=None):
        domain = [
            ('residencia_id', '=', residencia_id),
            ('active', '=', True),
        ]
        if exclude_id:
            domain.append(('id', '!=', exclude_id))
        otro = self.search(domain, limit=1)
        if otro:
            residencia = self.env['asovec.residencia'].browse(residencia_id)
            raise ValidationError(
                f"La residencia {residencia.name} ya tiene un contador activo ({otro.name}). "
                f"Desactívelo antes de activar/crear otro."
            )

    def _sync_residencia_active(self, residencia_ids):
        residencia_ids = {rid for rid in residencia_ids if rid}
        for residencia in self.env['asovec.residencia'].browse(residencia_ids):
            tiene_activo = bool(self.search_count([
                ('residencia_id', '=', residencia.id),
                ('active', '=', True),
            ]))
            if tiene_activo and not residencia.activo:
                residencia.activo = True
            elif not tiene_activo and residencia.activo:
                residencia.activo = False

    @api.model_create_multi
    def create(self, vals_list):
        residencias_activas_en_lote = set()
        for vals in vals_list:
            residencia_id = vals.get('residencia_id')
            if vals.get('active', True) and residencia_id:
                if residencia_id in residencias_activas_en_lote:
                    residencia = self.env['asovec.residencia'].browse(residencia_id)
                    raise ValidationError(
                        f"No se pueden crear varios contadores activos a la vez para la "
                        f"residencia {residencia.name}."
                    )
                self._check_no_other_active(residencia_id)
                residencias_activas_en_lote.add(residencia_id)

        records = super().create(vals_list)

        self._sync_residencia_active(records.mapped('residencia_id').ids)
        return records

    def write(self, vals):
        residencia_ids_to_sync = set(self.mapped('residencia_id').ids)
        if 'residencia_id' in vals:
            residencia_ids_to_sync.add(vals['residencia_id'])

        if vals.get('active') is True:
            objetivos = {}
            for rec in self:
                target_id = vals.get('residencia_id', rec.residencia_id.id)
                objetivos.setdefault(target_id, []).append(rec.id)
            for target_id, rec_ids in objetivos.items():
                if len(rec_ids) > 1:
                    residencia = self.env['asovec.residencia'].browse(target_id)
                    raise ValidationError(
                        f"No se pueden activar varios contadores a la vez para la "
                        f"residencia {residencia.name}."
                    )
                self._check_no_other_active(target_id, exclude_id=rec_ids[0])

        res = super().write(vals)

        if residencia_ids_to_sync:
            self._sync_residencia_active(residencia_ids_to_sync)

        return res

    def unlink(self):
        for rec in self:
            if rec.line_ids:
                raise ValidationError(
                    f"No se puede eliminar el contador {rec.name}: tiene lecturas asociadas. "
                    f"Inactívelo en su lugar para conservar el historial."
                )
        residencia_ids_to_sync = set(self.mapped('residencia_id').ids)
        res = super().unlink()
        self._sync_residencia_active(residencia_ids_to_sync)
        return res

    def action_activar(self):
        for rec in self:
            rec.active = True

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

    foto = fields.Binary(string="Foto", attachment=True)
    foto_filename = fields.Char(string="Nombre foto")  # opcional pero recomendado

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

    force_invoiced = fields.Boolean(
        string="Migrado (Facturación)",
        default=False,
        help="Marca esta lectura como migrada: no tiene una factura real asociada en el "
             "sistema (viene de historial), pero no debe salir como pendiente. Se "
             "mostrará como 'Migrado' en vez de 'Facturado', hasta que se opere "
             "correctamente con una factura real.",
    )

    force_paid = fields.Boolean(
        string="Migrado (Pago)",
        default=False,
        help="Marca el pago de esta lectura como migrado: no tiene un pago real "
             "registrado en el sistema (viene de historial), pero no debe salir como "
             "pendiente. Se mostrará como 'Migrado' en vez de 'Pagado', hasta que se "
             "opere correctamente con un pago real.",
    )

    invoice_status_badge = fields.Selection(
        selection=[
            ("not_invoiced", "No facturado"),
            ("borrador", "Borrador"),
            ("invoiced", "Facturado"),
            ("migrado", "Migrado"),
        ],
        string="Facturación",
        compute="_compute_invoice_info",
        readonly=True,
    )

    payment_status_badge = fields.Selection(
        selection=[("unpaid", "No pagado"), ("paid", "Pagado"), ("migrado", "Migrado")],
        string="Pago",
        compute="_compute_invoice_info",
        readonly=True,
    )

    @api.depends("invoice_line_ids.move_id.state", "invoice_line_ids.move_id.payment_state", "force_invoiced", "force_paid")
    def _compute_invoice_info(self):
        for rec in self:
            if rec.force_invoiced:
                rec.invoice_line_count = len(rec.invoice_line_ids)
                rec.invoice_move_id = False
                rec.invoice_status_badge = "migrado"
                rec.payment_status_badge = "migrado" if rec.force_paid else "unpaid"
                continue

            lines = rec.invoice_line_ids
            rec.invoice_line_count = len(lines)

            if lines:
                line = lines.sorted(lambda l: (l.move_id.id or 0, l.id))[0]
                move = line.move_id
                rec.invoice_move_id = move

                if move.state == "posted":
                    rec.invoice_status_badge = "invoiced"
                elif move.state == "draft":
                    rec.invoice_status_badge = "borrador"
                else:
                    rec.invoice_status_badge = "not_invoiced"

                rec.payment_status_badge = "paid" if move.payment_state == "paid" else "unpaid"
            else:
                rec.invoice_move_id = False
                rec.invoice_status_badge = "not_invoiced"
                rec.payment_status_badge = "migrado" if rec.force_paid else "unpaid"

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

    def action_imprimir_recibo(self):
        self.ensure_one()
        if self.es_inicial:
            raise ValidationError("No se puede imprimir el recibo de un registro inicial.")
        return self.env.ref("iit_asovec.action_report_recibo_residencia_mensual").report_action(self)

    def action_save(self):
        return True

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
    def _siguiente_periodo(self, mes, anio):
        y = int(anio)
        m = int(mes)
        if m == 12:
            return "1", y + 1
        return str(m + 1), y

    @api.model
    def _next_period_for_contador(self, contador_id):
        last = self._last_mensual(contador_id)
        today = fields.Date.context_today(self)
        if not last:
            return str(today.month), int(today.year)
        return self._siguiente_periodo(last.mes, last.anio)

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
            self._check_cargo_anterior_confirmado(last)
            exp_m, exp_y = self._next_period_for_contador(contador_id)
            if str(mes) != str(exp_m) or int(anio) != int(exp_y):
                raise ValidationError(
                    f"El siguiente período debe ser {exp_m}/{exp_y}. No se permiten saltos de meses."
                )

    @api.model
    def _validate_periodo_vals_en_lote(self, vals, estado):
        """Igual que `_validate_periodo_vals`, pero considerando además las filas del
        mismo contador ya procesadas dentro de este mismo lote de `create()` (necesario
        para que una importación masiva con varios meses de un mismo contador en un solo
        archivo valide/calcule la secuencia correctamente, ya que esas filas todavía no
        existen en la base de datos mientras se procesa el lote)."""
        contador_id = vals.get('contador_id')
        if not contador_id:
            raise ValidationError("Debe seleccionar un Contador.")

        es_inicial = bool(vals.get('es_inicial', False))

        if es_inicial:
            if estado['inicial'] is not None:
                raise ValidationError("Ya existe un registro inicial para este contador.")
            domain_ini = [('contador_id', '=', contador_id), ('es_inicial', '=', True)]
            if self.search(domain_ini, limit=1):
                raise ValidationError("Ya existe un registro inicial para este contador.")
            return

        mes = vals.get('mes')
        anio = vals.get('anio')
        if not mes or not anio:
            raise ValidationError("Debe seleccionar Mes y Año para una lectura mensual.")

        for m in estado['mensuales']:
            if str(m['mes']) == str(mes) and int(m['anio']) == int(anio):
                raise ValidationError("Ya existe una lectura para ese Mes/Año en este contador.")

        domain_dup = [
            ('contador_id', '=', contador_id),
            ('es_inicial', '=', False),
            ('mes', '=', mes),
            ('anio', '=', anio),
        ]
        if self.search(domain_dup, limit=1):
            raise ValidationError("Ya existe una lectura para ese Mes/Año en este contador.")

        if estado['mensuales']:
            ultimo = estado['mensuales'][-1]
            exp_m, exp_y = self._siguiente_periodo(ultimo['mes'], ultimo['anio'])
        else:
            last = self._last_mensual(contador_id)
            if not last:
                return
            self._check_cargo_anterior_confirmado(last)
            exp_m, exp_y = self._next_period_for_contador(contador_id)

        if str(mes) != str(exp_m) or int(anio) != int(exp_y):
            raise ValidationError(
                f"El siguiente período debe ser {exp_m}/{exp_y}. No se permiten saltos de meses."
            )

    @api.model
    def _check_cargo_anterior_confirmado(self, lectura_anterior):
        """Evita ingresar una nueva lectura mensual si el cargo de la lectura del mes
        anterior (mismo contador) todavía está en borrador (no confirmado/posteado)."""
        if lectura_anterior.invoice_status_badge == 'borrador':
            raise ValidationError(
                f"No se puede ingresar la lectura: el cargo de "
                f"{lectura_anterior.mes}/{lectura_anterior.anio} de este contador "
                f"todavía está en borrador. Confírmalo (postéalo) antes de ingresar "
                f"la siguiente lectura."
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

        # El "canon de agua" (cobro base) sigue en vivo el valor del proyecto, salvo que la
        # residencia tenga marcado su propio "Canon de agua propio": en ese caso se usa el
        # valor guardado en la residencia, independiente de lo que tenga el proyecto.
        if residencia and residencia.cobro_base_especial:
            cobro_base = float(residencia.cobro_base_especial_valor or 0.0)
        else:
            cobro_base = float(getattr(proyecto, 'cobro_base', 0.0) or 0.0) if proyecto else 0.0
        precio_maestro = float(getattr(proyecto, 'precio_metro', 0.0) or 0.0) if proyecto else 0.0
        # El "metro base (derecho)" sigue en vivo el valor del proyecto, salvo que la
        # residencia tenga marcado su propio metro base ("Metro base propio"): en ese caso
        # se usa el valor guardado en la residencia, independiente de lo que tenga el proyecto.
        if residencia and residencia.metros_especiales:
            metro_base = float(residencia.metros_especiales_cantidad or 0.0)
        else:
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

    def _refrescar_calculo_con_precio_actual(self):
        """Vuelve a calcular y guardar base/metros_extras/pago_extra/pago_total de esta
        lectura usando el precio VIGENTE del proyecto en este momento. Se usa justo antes
        de generar un cargo que todavía no existe (por ejemplo desde "Completar
        Faltantes"), para no usar una foto vieja del precio si el proyecto cambió de
        precio después de que la lectura ya se había guardado."""
        self.ensure_one()
        if self.es_inicial:
            return
        calc = self._calcular_campos_linea(
            self.contador_id, self.lectura, self.lectura_anterior, es_inicial=False
        )
        self.write({
            'base': calc['base'],
            'metros_extras': calc['metros_extras'],
            'pago_extra': calc['pago_extra'],
            'pago_total': calc['pago_total'],
        })

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
        # Estado en memoria por contador: permite que, dentro de un mismo lote (por
        # ejemplo una importación masiva de Excel con varios meses de un mismo
        # contador en un solo archivo), cada fila considere las filas anteriores del
        # mismo lote y no solo lo que ya existía en la base de datos antes de crear.
        estado_por_contador = {}

        for vals in vals_list:
            contador_id = vals.get('contador_id')
            lectura_actual = vals.get('lectura', 0.0)
            es_inicial = bool(vals.get('es_inicial', False))

            if not contador_id:
                raise ValidationError("Debe seleccionar un Contador.")

            estado = estado_por_contador.setdefault(contador_id, {'inicial': None, 'mensuales': []})

            self._validate_periodo_vals_en_lote(vals, estado)

            if es_inicial:
                lectura_anterior = 0.0
            elif estado['mensuales']:
                lectura_anterior = estado['mensuales'][-1]['lectura']
            else:
                last_m = self._last_mensual(contador_id)
                if last_m:
                    lectura_anterior = last_m.lectura or 0.0
                elif estado['inicial'] is not None:
                    lectura_anterior = estado['inicial']
                else:
                    ini = self._get_inicial(contador_id)
                    lectura_anterior = (ini.lectura or 0.0) if ini else 0.0

            if (lectura_actual or 0.0) < (lectura_anterior or 0.0):
                raise ValidationError(
                    f"La lectura ({lectura_actual}) no puede ser menor que la lectura anterior ({lectura_anterior})."
                )

            contador = self.env['asovec.contador'].browse(contador_id)
            vals.update(self._calcular_campos_linea(contador, lectura_actual, lectura_anterior, es_inicial=es_inicial))

            if es_inicial:
                estado['inicial'] = lectura_actual
            else:
                estado['mensuales'].append({'mes': vals.get('mes'), 'anio': vals.get('anio'), 'lectura': lectura_actual})

        records = super().create(vals_list)

        for rec in records:
            # La generación del cargo/factura es un efecto de sistema automático de
            # registrar una lectura, no una acción contable que el usuario esté
            # ejecutando a propósito: se corre con sudo para que un operador de
            # lecturas (sin permisos de facturación) pueda registrar su lectura sin
            # que la generación del cargo le falle por falta de acceso a los modelos
            # contables internos.
            rec.sudo()._generar_cargo_mensual()

        return records

    def _check_no_cargo_posteado(self):
        """No permite modificar el valor de la lectura si ya existe un cargo
        POSTEADO (factura confirmada) para esa residencia/período.

        Ojo: esto es independiente del umbral de cálculo de la compañía
        ('Cálculos a partir de'). Ese umbral solo evita generar/regenerar cargos
        automáticamente para historial migrado, pero un cargo real ya posteado
        antes de que el umbral avanzara sigue existiendo y debe protegerse igual
        (si no, `_generar_cargo_mensual` se salta por completo para períodos viejos
        y la lectura se modificaría sin ningún control)."""
        self.ensure_one()
        if self.es_inicial:
            return
        mes_padded = str(self.mes or "").zfill(2)
        line = self.env["asovec.proyecto_cobro_mensual_line"].search([
            ("residencia_id", "=", self.residencia_id.id),
            ("month", "=", mes_padded),
            ("year", "=", self.anio),
            ("move_state", "=", "posted"),
        ], limit=1)
        if line:
            raise ValidationError(
                f"No se puede modificar esta lectura: ya existe un cargo posteado "
                f"({line.move_id.name}) para {self.residencia_id.display_name} en "
                f"{self.mes}/{self.anio}."
            )

    def write(self, vals):
        periodo_puede_cambiar = any(k in vals for k in ('mes', 'anio'))
        periodos_anteriores = {}
        if periodo_puede_cambiar:
            for rec in self:
                periodos_anteriores[rec.id] = (rec.mes, rec.anio, rec.es_inicial)

        if 'lectura' in vals:
            for rec in self:
                rec._check_no_cargo_posteado()

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
            # Solo hay que re-validar el período (secuencia/duplicados) si realmente está
            # cambiando de período; si solo se corrigió el valor de `lectura`, el período
            # (y por tanto la validación de secuencia) sigue siendo el mismo.
            if any(k in vals for k in ('contador_id', 'es_inicial', 'mes', 'anio')):
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

            # Si el período (mes/año) cambió, hay que limpiar el cargo que había quedado
            # asociado al período anterior antes de generar el del período nuevo.
            if rec.id in periodos_anteriores:
                old_mes, old_anio, old_es_inicial = periodos_anteriores[rec.id]
                if not old_es_inicial and (old_mes != rec.mes or old_anio != rec.anio):
                    rec.sudo()._eliminar_cargo_periodo(rec.residencia_id, old_mes, old_anio)

            super(ContadorLine, rec).write({
                'lectura_anterior': calc['lectura_anterior'],
                'consumo': calc['consumo'],
                'base': calc['base'],
                'metros_extras': calc['metros_extras'],
                'pago_extra': calc['pago_extra'],
                'pago_total': calc['pago_total'],
            })

            # Ver comentario equivalente en create(): efecto de sistema, se corre con
            # sudo para no exigirle permisos contables al operador de lecturas.
            rec.sudo()._generar_cargo_mensual()

        return res

    def unlink(self):
        for rec in self:
            if not rec.es_inicial:
                rec._eliminar_cargo_periodo(rec.residencia_id, rec.mes, rec.anio)
        return super().unlink()

    # -------------------------
    # Generación de cargos (cobro mensual)
    # -------------------------
    def _cobro_line_for_period(self, residencia, mes, anio):
        mes_padded = str(mes or "").zfill(2)
        return self.env["asovec.proyecto_cobro_mensual_line"].search([
            ("residencia_id", "=", residencia.id),
            ("cobro_id.month", "=", mes_padded),
            ("cobro_id.year", "=", anio),
            ("cobro_id.state", "!=", "cancel"),
        ], limit=1)

    def _eliminar_cargo_periodo(self, residencia, mes, anio):
        """Borra el cargo (y su línea de cobro mensual) de esa residencia/período si está en
        borrador o cancelado. Si ya está posteado, no permite continuar."""
        line = self._cobro_line_for_period(residencia, mes, anio)
        if not line:
            return
        move = line.move_id
        if move and move.state == "posted":
            raise ValidationError(
                f"No se puede modificar/eliminar esta lectura: ya existe un cargo posteado "
                f"({move.name}) para {residencia.name} en {str(mes).zfill(2)}/{anio}."
            )
        line.unlink()
        if move:
            move.unlink()

    def _periodo_habilitado_para_calculo(self):
        """Compara el período (mes/año) de esta lectura contra el umbral configurado en
        la compañía ('Cálculos a partir de'). Si el período es anterior al umbral, no se
        debe generar cargo (se está cargando historial de meses anteriores)."""
        self.ensure_one()
        company = self.company_id or self.env.company
        mes_umbral = company.aso_calculos_mes
        anio_umbral = company.aso_calculos_anio
        if not mes_umbral or not anio_umbral:
            return True
        if not self.periodo_date:
            return True
        umbral = date(int(anio_umbral), int(mes_umbral), 1)
        return self.periodo_date >= umbral

    def _generar_cargo_mensual(self):
        """Crea (o recrea, si estaba en borrador) el cargo correspondiente a esta lectura."""
        self.ensure_one()
        if self.es_inicial:
            return
        if not self._periodo_habilitado_para_calculo():
            return
        if self.residencia_id.no_paga_servicios:
            return
        proyecto = self.residencia_id.proyecto_aso_id
        if not proyecto:
            return
        cobro = self.env["asovec.proyecto_cobro_mensual"]._get_or_create_cobro(proyecto, self.mes, self.anio)
        cobro._generar_cargo_residencia(self.residencia_id, lectura=self)
