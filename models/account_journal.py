from odoo import api, models, fields
from odoo.exceptions import ValidationError


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    aso_cargo = fields.Selection([('No', 'No'), ('Si', 'Si')], default='No', string='Cargo Asociacion')
    convenio_principal = fields.Char(string='Convenio Principal')

    aso_cargo_otro = fields.Selection([('No', 'No'), ('Si', 'Si')], default='No', string='Cargo Asociacion Otro')
    convenio_otro = fields.Char(string='Convenio Otro')

    diario_relacionado_id = fields.Many2one(
        'account.journal',
        string='Diario Relacionado',
        domain="[('type', 'in', ('cash', 'bank'))]",
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
