# -*- coding: utf-8 -*-
{
    'name' : 'Asociacion de Vecinos',
    'summary':"""
        Implementacion Asociacion de Vecinos, Odoo 17
    """,
    'author':'Alexander Paiz',
    'category': 'General',
    'version' : '1.0.2',
    'depends': [
        'base', 'product', 'account'
    ],
    'data': [
        'security/asovec_security.xml',
        'security/ir.model.access.csv',
        'views/proyecto_aso_view.xml',
        'views/res_company_view.xml',
        'views/residencia_view.xml',
        'views/tipo_servicio_aso_view.xml',
        'views/contador_view.xml',
        'views/lectura_operador_wizard_view.xml',
        'views/proyecto_cobro_mensual_view.xml',
        'views/product_template_view.xml',
        'views/account_journal.xml',
        'views/proyecto_cobro_mensual_line_view.xml',
        'views/cobro_consulta_wizard_view.xml',
        'views/residencia_recibo_wizard_view.xml',
        'views/proceso_recibo_masivo_wizard_view.xml',
        'views/proceso_estado_cuenta_csv_wizard_view.xml',
        'views/proceso_estado_lecturas_excel_wizard_view.xml',
        'views/proceso_carga_deudas_wizard_view.xml',
        'views/proceso_analisis_mensual_wizard_view.xml',
        'views/menu_view.xml',
        'reports/estado_cuenta_report.xml',
        'reports/estado_cuenta_residencia_lecturas_report.xml',
        'reports/recibo_residencia_mensual_report.xml',
        'reports/recibo_residencia_mensual_masivo_report.xml',
        'reports/analisis_mensual_report.xml'
    ],
    'assets': {
        'web.assets_backend': [
            'iit_asovec/static/src/css/lectura_operador.css',
        ],
    },
}