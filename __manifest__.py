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
        "account"
    ],
    'data': [
        'security/asovec_security.xml',
        'security/ir.model.access.csv',
        'views/residencia.xml',
        'views/menu_view.xml'
    ]
}