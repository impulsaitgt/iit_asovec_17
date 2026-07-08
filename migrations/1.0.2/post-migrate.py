# -*- coding: utf-8 -*-
"""Los tipos de servicio ASO ahora requieren un precio configurado por proyecto
(`asovec.tipo_servicio_aso.proyecto`); si un proyecto no tiene una línea de detalle, el
servicio ya no se genera para las residencias de ese proyecto.

Para no cambiar la facturación de los servicios automáticos existentes (por ejemplo
BASURA), esta migración crea, para cada tipo de servicio marcado como 'Automático
Mensual', una línea de detalle por cada proyecto existente usando el 'Precio de venta'
del producto vinculado a ese tipo.

Además, el cálculo del canon de agua (cobro base) ahora puede tomarse de la propia
residencia (campo `cobro_base_especial_valor`) en vez de siempre del proyecto. Se
copia el `cobro_base` vigente del proyecto a cada residencia que todavía no tenga
marcado 'Canon de agua propio', para que el valor quede prellenado si luego se activa.
"""

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Tipo = env["asovec.tipo_servicio_aso"]
    Detalle = env["asovec.tipo_servicio_aso.proyecto"]
    Proyecto = env["asovec.proyecto_aso"]

    proyectos = Proyecto.search([])
    if proyectos:
        tipos_automaticos = Tipo.search([("aso_automatico", "=", True)])
        for tipo in tipos_automaticos:
            producto = env["product.template"].search(
                [("tipo_servicio_aso_id", "=", tipo.id)], limit=1
            )
            precio = producto.list_price if producto else 0.0
            for proyecto in proyectos:
                existe = Detalle.search([
                    ("tipo_servicio_aso_id", "=", tipo.id),
                    ("proyecto_aso_id", "=", proyecto.id),
                ], limit=1)
                if not existe:
                    Detalle.create({
                        "tipo_servicio_aso_id": tipo.id,
                        "proyecto_aso_id": proyecto.id,
                        "precio": precio,
                    })

    residencias = env["asovec.residencia"].search([("cobro_base_especial", "=", False)])
    for residencia in residencias:
        if residencia.proyecto_aso_id:
            residencia.cobro_base_especial_valor = residencia.proyecto_aso_id.cobro_base
