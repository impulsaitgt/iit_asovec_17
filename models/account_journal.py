from odoo import api, models, fields
from odoo.exceptions import ValidationError


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    aso_cargo = fields.Selection([('No', 'No'), ('Si', 'Si')], default='No', string='Cargo Asociacion')
    convenio_principal = fields.Char(string='Convenio Principal')

    aso_cargo_otro = fields.Selection([('No', 'No'), ('Si', 'Si')], default='No', string='Cargo Asociacion Otro')
    convenio_otro = fields.Char(string='Convenio Otro')

    aso_cargo_automatico = fields.Selection(
        [('No', 'No'), ('Si', 'Si')], default='No', string='Cargo Automatico Asociacion',
        help="Diario único que usa el proceso de Cobros Mensuales para postear los cargos "
             "automáticos. Solo puede haber un diario por compañía con este flag en 'Si'. "
             "'Cargo Asociacion' es solo una sugerencia usada en otras partes del sistema "
             "(por ejemplo, el CSV de estado de cuenta) y puede repetirse en varios diarios.",
    )

    @api.constrains('aso_cargo', 'convenio_principal', 'aso_cargo_otro', 'convenio_otro')
    def _check_convenios(self):
        for rec in self:
            if rec.convenio_principal and rec.aso_cargo != 'Si':
                raise ValidationError(
                    "Solo se puede llenar 'Convenio Principal' cuando 'Cargo Asociacion' es 'Si'."
                )
            if rec.convenio_otro and rec.aso_cargo_otro != 'Si':
                raise ValidationError(
                    "Solo se puede llenar 'Convenio Otro' cuando 'Cargo Asociacion Otro' es 'Si'."
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
