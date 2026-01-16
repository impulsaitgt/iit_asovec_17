# -*- coding: utf-8 -*-
{
    'name' : 'Asociacion de Vecinos',
    'summary':"""
        Implementacion Asociacion de Vecinos, Odoo 17
    """,
    'author':'Alexander Paiz',
    'category': 'General',
    'version' : '1.0.0',
    'depends': [
        'base', 'product', 'account'
    ],
    'data': [
        'security/asovec_security.xml',
        'security/ir.model.access.csv',
        'views/proyecto_aso_view.xml',
        'views/residencia_view.xml',
        'views/tipo_servicio_aso_view.xml',
        'views/contador_view.xml',
        'views/proyecto_cobro_mensual_view.xml',
        'views/product_template_view.xml',
        'views/account_journal.xml',
        'views/proyecto_cobro_mensual_line_view.xml',
        'views/cobro_consulta_wizard_view.xml',
        'views/menu_view.xml',
        'reports/estado_cuenta_report.xml'
    ]
}