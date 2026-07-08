# -*- coding: utf-8 -*-
import base64
import calendar
from datetime import date

from odoo import models, fields, api
from odoo.tools import image_process

from .contador import MONTH_SELECTION

# Miniatura del logo para el recibo: reduce drásticamente el tamaño del HTML/PDF
# generado (importante en el proceso masivo, donde el logo se repite por cada recibo).
LOGO_MAX_HEIGHT = 180

MOVE_STATE_LABELS = {"draft": "Borrador", "posted": "Publicado", "cancel": "Cancelado"}
MOVE_STATE_COLORS = {"draft": "#8a8a8a", "posted": "#009999", "cancel": "#c62828"}
PAYMENT_LABELS = {"paid": "Pagado", "unpaid": "No pagado"}
PAYMENT_COLORS = {"paid": "#2e7d32", "unpaid": "#c62828"}


class ReportReciboResidenciaMensual(models.AbstractModel):
    _name = "report.iit_asovec.report_recibo_residencia_mensual"
    _description = "Recibo Mensual por Residencia"

    @api.model
    def _get_fecha_pago_disponible(self, lectura, proyecto):
        """Fecha a partir de la cual se puede pagar el recibo:
        - Si el cobro mensual de ese proyecto/mes/año ya fue confirmado, se usa la fecha
          en la que se confirmó.
        - Si no, se usa el día tentativo de carga configurado en el proyecto, del mes
          siguiente al de la lectura.
        """
        mes_padded = str(lectura.mes or "").zfill(2)
        cobro = self.env["asovec.proyecto_cobro_mensual"].search([
            ("proyecto_aso_id", "=", proyecto.id),
            ("month", "=", mes_padded),
            ("year", "=", lectura.anio),
            ("state", "!=", "cancel"),
        ], limit=1)

        if cobro and cobro.state == "posted" and cobro.fecha_confirmacion:
            return cobro.fecha_confirmacion

        mes_siguiente = int(lectura.mes) + 1
        anio_siguiente = lectura.anio
        if mes_siguiente > 12:
            mes_siguiente = 1
            anio_siguiente += 1

        dia = proyecto.dia_tentativo_carga or 6
        dia = min(dia, calendar.monthrange(anio_siguiente, mes_siguiente)[1])

        return date(anio_siguiente, mes_siguiente, dia)

    @api.model
    def _get_recibo_data(self, lecturas):
        meses = dict(MONTH_SELECTION)
        recibos = []
        logos_cache = {}

        for lectura in lecturas:
            residencia = lectura.residencia_id
            proyecto = lectura.proyecto_aso_id
            company = lectura.company_id

            if company.id not in logos_cache:
                if company.logo:
                    resized = image_process(base64.b64decode(company.logo), size=(0, LOGO_MAX_HEIGHT))
                    logos_cache[company.id] = base64.b64encode(resized) if resized else False
                else:
                    logos_cache[company.id] = False

            direccion = residencia.direccion_real

            move = lectura.invoice_move_id
            agua = lectura.pago_total
            total = move.amount_total if move else agua
            otros = total - agua

            move_state = move.state if move else False
            payment_state = lectura.payment_status_badge if move else False
            fecha_pago_disponible = self._get_fecha_pago_disponible(lectura, proyecto) if proyecto else False

            recibos.append({
                "lectura": lectura,
                "proyecto": proyecto,
                "vecino": residencia.cliente_id.name or "",
                "cuenta": residencia.name,
                "direccion": direccion,
                "periodo": "%s %s" % (meses.get(lectura.mes, lectura.mes or ""), lectura.anio or ""),
                "lectura_anterior": lectura.lectura_anterior,
                "lectura_actual": lectura.lectura,
                "consumo": lectura.consumo,
                "agua": agua,
                "otros": otros,
                "total": total,
                "tiene_exceso": (lectura.metros_extras or 0) > 0,
                "currency": lectura.currency_id,
                "company": company,
                "logo": logos_cache[company.id],
                "leyenda": proyecto.leyenda_recibo if proyecto else False,
                "move_state_label": MOVE_STATE_LABELS.get(move_state),
                "move_state_color": MOVE_STATE_COLORS.get(move_state),
                "payment_label": PAYMENT_LABELS.get(payment_state),
                "payment_color": PAYMENT_COLORS.get(payment_state),
                "fecha_pago_disponible": fecha_pago_disponible,
            })

        return recibos

    @api.model
    def _get_report_values(self, docids, data=None):
        lecturas = self.env["asovec.contador.lines"].browse(docids)

        return {
            "doc_ids": docids,
            "doc_model": "asovec.contador.lines",
            "docs": lecturas,
            "recibos": self._get_recibo_data(lecturas),
            "fecha_generacion": fields.Date.context_today(self),
        }
