# -*- coding: utf-8 -*-
"""El cálculo de facturación ahora toma el 'metro base (derecho)' de la residencia
(campo `metros_especiales_cantidad`) en vez de tomarlo siempre del proyecto.

Para no cambiar la facturación de las residencias existentes, esta migración copia
el metro_base del proyecto a cada residencia que todavía no tenga su propio valor
(es decir, las que no tienen marcado 'Metro base propio').
"""

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    residencias = env["asovec.residencia"].search([("metros_especiales", "=", False)])
    for residencia in residencias:
        if residencia.proyecto_aso_id:
            residencia.metros_especiales_cantidad = residencia.proyecto_aso_id.metro_base
