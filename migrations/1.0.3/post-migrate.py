# -*- coding: utf-8 -*-
"""Rellena 'residencia_id' en account.move para los cargos que ya existían antes
de que ese campo existiera (tanto de cobro mensual normal como de deuda migrada),
para que el reporte de Estado de Cuenta (Banco) deje de mezclar residencias que
comparten cliente, y para que la columna 'Residencia' se vea también en cargos
históricos dentro del módulo de Facturación."""
import re

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # 1) Cargos de cobro mensual normal: la residencia ya se conoce con exactitud
    #    a través de la línea del cobro mensual asociada a ese cargo.
    lines = env["asovec.proyecto_cobro_mensual_line"].search([
        ("move_id", "!=", False),
        ("move_id.residencia_id", "=", False),
    ])
    for line in lines:
        line.move_id.residencia_id = line.residencia_id.id

    # 2) Cargos de deuda migrada: no tienen ningún vínculo estructurado a la
    #    residencia, pero el texto de 'ref' sí la menciona
    #    ("Migración <residencia> - <mes>/<anio>"), así que se parsea desde ahí.
    Residencia = env["asovec.residencia"]
    residencias_por_nombre = {r.name: r for r in Residencia.search([])}

    moves = env["account.move"].search([
        ("residencia_id", "=", False),
        ("invoice_line_ids.product_id.product_tmpl_id.tipo_servicio_aso_id.aso_migrado", "=", True),
    ])
    patron = re.compile(r"^Migraci[oó]n\s+(.+?)\s+-\s+\d+/\d+$")
    for move in moves:
        m = patron.match(move.ref or "")
        if not m:
            continue
        residencia = residencias_por_nombre.get(m.group(1).strip())
        if residencia:
            move.residencia_id = residencia.id
