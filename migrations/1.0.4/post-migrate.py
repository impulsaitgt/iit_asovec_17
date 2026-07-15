# -*- coding: utf-8 -*-
"""Renombra el flag 'Cargo Asociacion' (aso_cargo) del diario a 'Cargo Migrado'
(aso_cargo_migrado), ahora exclusivo con 'Cargo Automatico Asociacion'. Preserva el
valor solo para los diarios donde de verdad significaba "diario de deuda migrada"
(los que NO son el diario automático de Cobros Mensuales); para ese, el nuevo campo
queda en 'No' (ya lo cubre 'Cargo Automatico Asociacion')."""


def migrate(cr, version):
    cr.execute("""
        UPDATE account_journal
        SET aso_cargo_migrado = 'Si'
        WHERE aso_cargo = 'Si' AND COALESCE(aso_cargo_automatico, 'No') != 'Si'
    """)
