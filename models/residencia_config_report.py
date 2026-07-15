# -*- coding: utf-8 -*-
import base64

from odoo import api, fields, models
from odoo.tools import image_process

LOGO_MAX_HEIGHT = 90


class ReportResidenciaConfig(models.AbstractModel):
    _name = "report.iit_asovec.report_residencia_config_document"
    _description = "Configuración de Residencias (documento)"

    def _servicios_automaticos(self):
        return self.env["product.template"].search([
            ("aso_es_servicio_aso", "=", True),
            ("aso_automatico", "=", True),
            ("aso_activo", "=", True),
        ], order="name")

    def _precio_servicio(self, residencia, servicio):
        """Replica exactamente la precedencia de precio usada al generar el cargo real
        (_build_invoice_lines_residencia en proyecto_cobro_mensual.py): override por
        residencia (asovec.residencia.lines) si existe, si no el precio configurado
        para el proyecto (tipo_servicio_aso.proyecto_ids); si ninguno aplica o el
        precio efectivo es cero, el servicio no se cobra."""
        if not residencia.activo and not servicio.tipo_servicio_aso_id.aso_cobra_inactivas:
            return {"estado": "no_aplica", "precio": 0.0}

        override = self.env["asovec.residencia.lines"].search([
            ("residencia_id", "=", residencia.id), ("producto_id", "=", servicio.id),
        ], limit=1)
        if override:
            precio = override.precio
        else:
            detalle = servicio.tipo_servicio_aso_id.proyecto_ids.filtered(
                lambda d: d.proyecto_aso_id.id == residencia.proyecto_aso_id.id
            )
            if not detalle:
                return {"estado": "no_configurado", "precio": 0.0}
            precio = detalle[0].precio

        if precio <= 0:
            return {"estado": "no_paga", "precio": 0.0}
        return {"estado": "paga", "precio": precio}

    def _residencia_row(self, residencia, servicios):
        proyecto = residencia.proyecto_aso_id

        if residencia.cobro_base_especial:
            canon_valor = residencia.cobro_base_especial_valor
        else:
            canon_valor = proyecto.cobro_base

        servicios_vals = {s.name: self._precio_servicio(residencia, s) for s in servicios}
        contador = residencia._get_contador_activo()

        return {
            "proyecto": proyecto,
            "residencia": residencia,
            "direccion": residencia.direccion_real,
            "residente": residencia.cliente_id,
            "no_paga_servicios": residencia.no_paga_servicios,
            "canon_propio": residencia.cobro_base_especial,
            "canon_valor": canon_valor,
            "canon_paga": canon_valor > 0,
            "exonera_exceso": residencia.exonera_exceso_agua,
            "cobra_inactivo": not residencia.activo,
            "valor_inactivo": proyecto.cobro_inactivas,
            "contador": contador,
            "servicios": servicios_vals,
            "currency": residencia.currency_id or self.env.company.currency_id,
        }

    @api.model
    def _build_residencia_config_data(self, wizard):
        wizard.ensure_one()
        proyectos = wizard.proyecto_aso_ids
        residencias = self.env["asovec.residencia"].search(
            [("proyecto_aso_id", "in", proyectos.ids)], order="proyecto_aso_id, name",
        )
        servicios = self._servicios_automaticos()
        servicios_nombres = servicios.mapped("name")

        filas = [self._residencia_row(r, servicios) for r in residencias]

        resumen = {
            "cantidad_residencias": len(filas),
            "cantidad_sin_canon": len([f for f in filas if not f["canon_paga"]]),
            "cantidad_exoneradas": len([f for f in filas if f["exonera_exceso"]]),
            "cantidad_inactivas": len([f for f in filas if f["cobra_inactivo"]]),
            "cantidad_no_paga_servicios": len([f for f in filas if f["no_paga_servicios"]]),
        }

        currency = (filas[0]["currency"] if filas else False) or self.env.company.currency_id
        generated_at_dt = fields.Datetime.context_timestamp(wizard, fields.Datetime.now())

        return {
            "proyectos": proyectos,
            "servicios_nombres": servicios_nombres,
            "filas": filas,
            "resumen": resumen,
            "generated_at": generated_at_dt.strftime("%d/%m/%Y %H:%M"),
            "currency": currency,
        }

    @api.model
    def _get_report_values(self, docids, data=None):
        wizard = self.env["asovec.residencia_config_wizard"].browse(docids)
        wizard.ensure_one()
        datos = self._build_residencia_config_data(wizard)

        company = self.env.company
        logo_b64 = False
        if company.logo:
            resized = image_process(base64.b64decode(company.logo), size=(0, LOGO_MAX_HEIGHT))
            if resized:
                logo_b64 = base64.b64encode(resized).decode()

        return {
            "doc_ids": docids,
            "doc_model": "asovec.residencia_config_wizard",
            "docs": wizard,
            "company": company,
            "logo_b64": logo_b64,
            **datos,
        }
