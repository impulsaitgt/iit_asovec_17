from odoo import api, models, fields
from odoo.exceptions import ValidationError


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    aso_cargo_migrado = fields.Selection(
        [('No', 'No'), ('Si', 'Si')], default='No', string='Cargo Migrado',
        help="Diario reservado para el proceso de Migración de Deuda: solo se puede "
             "cargar desde ahí, nunca operando una factura manualmente desde "
             "Facturación. Excluyente con 'Cargo Automatico Asociacion' (son procesos "
             "distintos, un diario no puede ser de los dos a la vez).",
    )
    aso_cargo_automatico = fields.Selection(
        [('No', 'No'), ('Si', 'Si')], default='No', string='Cargo Automatico Asociacion',
        help="Diario único que usa el proceso de Cobros Mensuales para postear los cargos "
             "automáticos. Solo puede haber un diario por compañía con este flag en 'Si'. "
             "Excluyente con 'Cargo Migrado' (son procesos distintos, un diario no puede "
             "ser de los dos a la vez).",
    )

    aso_valida_residencia = fields.Boolean(
        string='Valida/Sugiere Residencia', default=True,
        help="Si está activo, las facturas/notas de crédito de este diario sugieren "
             "automáticamente la Residencia del residente y no se pueden grabar sin una "
             "Residencia válida. Desactívelo para diarios usados para otros controles "
             "donde no aplica el concepto de Residencia, aunque el cliente sea un residente.",
    )
    aso_convenio = fields.Selection(
        [('No', 'No'), ('Si', 'Si')], default='No', string='Convenio (Cargo Residencial)',
        help="Diario reservado para los cargos de Convenio (menú Movimientos > "
             "Convenio). Solo se puede activar en diarios de tipo Venta, y solo puede "
             "haber un diario por compañía con este flag en 'Si'. No confundir con el "
             "campo 'Convenio' de iit_soap_bi (soap_bi.convenio, agenda de pasarela de "
             "pago): son conceptos distintos que solo comparten nombre.",
    )

    @api.constrains('aso_convenio', 'type')
    def _check_convenio_solo_venta(self):
        for rec in self:
            if rec.aso_convenio == 'Si' and rec.type != 'sale':
                raise ValidationError(
                    "El flag 'Convenio' solo se puede activar en diarios de tipo Venta."
                )

    @api.constrains('aso_convenio', 'company_id')
    def _check_convenio_unico(self):
        for rec in self:
            if rec.aso_convenio != 'Si':
                continue
            otros = self.search([
                ('aso_convenio', '=', 'Si'),
                ('company_id', '=', rec.company_id.id),
                ('id', '!=', rec.id),
            ])
            if otros:
                raise ValidationError(
                    "Ya existe el Diario '%s' marcado como 'Convenio' para esta compañía. "
                    "Solo puede haber uno." % otros[0].name
                )

    @api.constrains('aso_cargo_automatico', 'company_id')
    def _check_cargo_automatico_unico(self):
        for rec in self:
            if rec.aso_cargo_automatico != 'Si':
                continue
            otros = self.search([
                ('aso_cargo_automatico', '=', 'Si'),
                ('company_id', '=', rec.company_id.id),
                ('id', '!=', rec.id),
            ])
            if otros:
                raise ValidationError(
                    "Ya existe el Diario '%s' marcado como 'Cargo Automatico Asociacion' "
                    "para esta compañía. Solo puede haber uno." % otros[0].name
                )

    @api.constrains('aso_cargo_automatico', 'aso_cargo_migrado')
    def _check_automatico_migrado_excluyentes(self):
        for rec in self:
            if rec.aso_cargo_automatico == 'Si' and rec.aso_cargo_migrado == 'Si':
                raise ValidationError(
                    "Un diario no puede tener 'Cargo Automatico Asociacion' y 'Cargo "
                    "Migrado' en 'Si' al mismo tiempo: son procesos distintos y excluyentes."
                )
