from odoo import api, models, fields


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    aso_cargo = fields.Selection([('No', 'No'), ('Si', 'Si')], default='No', string='Cargo Asociacion')
