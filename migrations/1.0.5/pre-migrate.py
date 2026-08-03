# -*- coding: utf-8 -*-
"""'colaborador_id' de Orden de Trabajo pasa de res.users a hr.employee. Antes de que
el ORM recree el constraint de la columna apuntando a hr_employee, se remapea cada
valor existente (id de res.users) al empleado relacionado a ese usuario; si un
colaborador no tiene empleado vinculado, se deja en NULL en vez de dejar un id
inválido que rompa el nuevo constraint."""


def migrate(cr, version):
    cr.execute("""
        UPDATE asovec_orden_trabajo o
        SET colaborador_id = e.id
        FROM hr_employee e
        WHERE e.user_id = o.colaborador_id
    """)
    cr.execute("""
        UPDATE asovec_orden_trabajo
        SET colaborador_id = NULL
        WHERE colaborador_id IS NOT NULL
          AND colaborador_id NOT IN (SELECT id FROM hr_employee)
    """)
