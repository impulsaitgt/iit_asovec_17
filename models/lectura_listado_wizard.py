# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .contador import MONTH_SELECTION


class LecturaListadoWizard(models.TransientModel):
    _name = "asovec.lectura_listado_wizard"
    _description = "Listado de Residencias por Proyecto (para tomar lecturas)"

    proyecto_aso_id = fields.Many2one("asovec.proyecto_aso", string="Proyecto", required=True)
    mes = fields.Selection(MONTH_SELECTION, string="Mes", required=True)
    anio = fields.Integer(string="Año", required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Igual que el CSV de lecturas: se quiere ver qué falta AHORA, del mes en curso.
        today = fields.Date.context_today(self)
        if "mes" in fields_list and not res.get("mes"):
            res["mes"] = str(today.month)
        if "anio" in fields_list and not res.get("anio"):
            res["anio"] = today.year
        return res

    def action_buscar(self):
        """Arma el listado con consultas por lote (en vez de una por residencia):
        con cientos de residencias, buscar el contador/lectura de cada una por
        separado se sentía lento (más de 2000 consultas para 500+ residencias)."""
        self.ensure_one()
        if not self.proyecto_aso_id:
            raise UserError(_("Selecciona un proyecto."))

        # Ya no se filtra por 'activo' aquí: se trae todo y el filtro "Activas" (por
        # defecto activado, pero removible) se aplica en la vista, igual que
        # "Pendientes" y que "Activos" en Contadores.
        residencias = self.env["asovec.residencia"].search([
            ("proyecto_aso_id", "=", self.proyecto_aso_id.id),
            ("no_paga_servicios", "=", False),
            ("sin_contador", "=", False),
        ])
        if not residencias:
            raise UserError(_("No hay residencias para ese proyecto."))

        # Un solo query para los contadores de todas las residencias (con
        # active_test=False para no perder el fallback a un contador inactivo).
        Contador = self.env["asovec.contador"].with_context(active_test=False)
        contadores = Contador.search([("residencia_id", "in", residencias.ids)])
        contador_por_residencia = {}
        for c in contadores.sorted(lambda c: (c.active, c.id), reverse=True):
            # El primero que se ve por residencia es el preferido: activo y, si hay
            # varios, el más reciente (mismo criterio que _get_contador_activo).
            contador_por_residencia.setdefault(c.residencia_id.id, c)

        contador_ids = list(contador_por_residencia.values())
        contador_ids = list({c.id for c in contador_ids})

        Line = self.env["asovec.contador.lines"]
        mes_plano = str(int(self.mes))

        # Un solo query para TODAS las lecturas mensuales de todos los contadores,
        # ya ordenadas para que la primera de cada contador sea la más reciente.
        mensuales = Line.search([
            ("contador_id", "in", contador_ids),
            ("es_inicial", "=", False),
        ], order="contador_id, periodo_date desc, id desc")
        mensuales_por_contador = {}
        for l in mensuales:
            mensuales_por_contador.setdefault(l.contador_id.id, []).append(l)

        # Un solo query para los registros iniciales (fallback si un contador
        # todavía no tiene ninguna lectura mensual).
        iniciales = Line.search([("contador_id", "in", contador_ids), ("es_inicial", "=", True)])
        inicial_por_contador = {i.contador_id.id: i for i in iniciales}

        vals_list = []
        for residencia in residencias:
            contador = contador_por_residencia.get(residencia.id)
            if not contador:
                continue

            lecturas_contador = mensuales_por_contador.get(contador.id, [])
            lectura_este_mes = next(
                (l for l in lecturas_contador if str(l.mes) == mes_plano and int(l.anio) == int(self.anio)),
                None,
            )

            otras = [l for l in lecturas_contador if l != lectura_este_mes]
            if otras:
                lectura_anterior = otras[0].lectura or 0.0
            else:
                ini = inicial_por_contador.get(contador.id)
                lectura_anterior = (ini.lectura or 0.0) if ini else 0.0

            company = residencia.proyecto_aso_id.company_id or self.env.company
            periodo_habilitado = Line._periodo_esta_habilitado(company, self.mes, self.anio)

            vals_list.append({
                "residencia_id": residencia.id,
                "contador_id": contador.id,
                "mes": self.mes,
                "anio": self.anio,
                "residencia_activa": residencia.activo,
                "lectura_anterior": lectura_anterior,
                "lectura_actual": lectura_este_mes.lectura if lectura_este_mes else 0.0,
                "tiene_lectura": bool(lectura_este_mes),
                "estado_lectura": "con_lectura" if lectura_este_mes else "pendiente",
                "periodo_habilitado": periodo_habilitado,
            })

        if not vals_list:
            raise UserError(_("No hay residencias con contador activo para ese proyecto."))

        lines = self.env["asovec.lectura_listado_wizard_line"].create(vals_list)

        mes_label = dict(MONTH_SELECTION).get(self.mes, self.mes)
        return {
            "type": "ir.actions.act_window",
            "name": _("Residencias - %s (%s/%s)") % (self.proyecto_aso_id.name, mes_label, self.anio),
            "res_model": "asovec.lectura_listado_wizard_line",
            "view_mode": "tree",
            "views": [(self.env.ref("iit_asovec.view_asovec_lectura_listado_wizard_line_tree").id, "tree")],
            "search_view_id": [self.env.ref("iit_asovec.view_asovec_lectura_listado_wizard_line_search").id],
            "domain": [("id", "in", lines.ids)],
            "context": {"search_default_pendientes": 1, "search_default_activas": 1},
            "target": "current",
        }


class LecturaListadoWizardLine(models.TransientModel):
    _name = "asovec.lectura_listado_wizard_line"
    _description = "Línea de Listado de Residencias (para tomar lecturas)"
    # Ordenar por "residencia_id" directamente ordenaría por el ID interno del
    # registro relacionado (su orden de creación), no por su código/nombre. Por eso
    # se usa este campo de código propio, guardado, para el orden por defecto.
    _order = "residencia_codigo"

    residencia_id = fields.Many2one("asovec.residencia", string="Residencia", readonly=True)
    residencia_codigo = fields.Char(related="residencia_id.name", string="Código", store=True, readonly=True)
    contador_id = fields.Many2one("asovec.contador", string="Contador", readonly=True)
    direccion_real = fields.Char(related="residencia_id.direccion_real", string="Dirección", store=True, readonly=True)
    cliente_id = fields.Many2one(related="residencia_id.cliente_id", string="Contacto", store=True, readonly=True)
    proyecto_aso_id = fields.Many2one(related="residencia_id.proyecto_aso_id", string="Proyecto", store=True, readonly=True)

    # Período con el que se generó este listado: se reenvía como contexto al abrir
    # "Registrar Lectura", para que ese wizard sepa a qué listado regresar al
    # Guardar/Cancelar.
    mes = fields.Selection(MONTH_SELECTION, string="Mes", readonly=True)
    anio = fields.Integer(string="Año", readonly=True)

    # Para el filtro "Activas" (activado por defecto, se puede quitar para ver
    # también las residencias inactivas).
    residencia_activa = fields.Boolean(string="Residencia activa", readonly=True)

    lectura_anterior = fields.Float(string="Lectura anterior", readonly=True)
    lectura_actual = fields.Float(string="Lectura actual", readonly=True)
    # `tiene_lectura` se usa para el filtro "Pendientes"; `estado_lectura` es la
    # versión para mostrar con badge (un widget "badge" sobre un Boolean no
    # renderiza bien, se ve el HTML del checkbox en vez del badge de color).
    tiene_lectura = fields.Boolean(string="Ya tiene lectura", readonly=True)
    estado_lectura = fields.Selection(
        [("pendiente", "Pendiente"), ("con_lectura", "Con lectura")],
        string="Estado", readonly=True,
    )

    # False cuando el mes/año buscado es anterior al umbral "Cálculos a partir de" de
    # la compañía: ese período es historial migrado (ver
    # ContadorLine._periodo_esta_habilitado) y no se debe poder registrar/corregir
    # desde aquí. Se usa para ocultar el botón "Registrar" en la vista.
    periodo_habilitado = fields.Boolean(string="Período habilitado", readonly=True, default=True)

    def action_ir_a_registrar(self):
        self.ensure_one()
        if not self.periodo_habilitado:
            raise UserError(_(
                "No se puede registrar/corregir: %s/%s es un período anterior al umbral "
                "de cálculos de la compañía (historial migrado)."
            ) % (self.mes, self.anio))
        return {
            "type": "ir.actions.act_window",
            "name": _("Registrar Lectura"),
            "res_model": "asovec.lectura_operador_wizard",
            "view_mode": "form",
            # Vista especial: como la residencia ya viene seleccionada, el foco debe
            # quedar en "Lectura actual" en vez de en el buscador de residencia.
            "views": [(self.env.ref("iit_asovec.view_asovec_lectura_operador_wizard_form_desde_listado").id, "form")],
            "target": "current",
            "context": {
                "default_residencia_id": self.residencia_id.id,
                "listado_proyecto_id": self.proyecto_aso_id.id,
                "listado_mes": self.mes,
                "listado_anio": self.anio,
                # Si esta residencia ya tiene lectura este período, entra directo en
                # modo corrección (sin tener que dar clic en "Corregir última
                # lectura"). Esto solo aplica viniendo de este listado: entrando
                # directo a "Registrar Lectura" el comportamiento no cambia.
                "listado_forzar_correccion": self.tiene_lectura,
            },
        }
