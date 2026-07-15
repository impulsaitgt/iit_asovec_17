# -*- coding: utf-8 -*-
import base64

from odoo import http
from odoo.http import content_disposition, request


class EstadoCuentaController(http.Controller):

    @http.route("/asovec/estado_cuenta/<int:wizard_id>/xlsx", type="http", auth="user")
    def estado_cuenta_xlsx(self, wizard_id, **kwargs):
        """Genera y descarga el Excel del estado de cuenta directamente desde el
        reporte HTML, sin tener que volver al wizard. Reusa action_generar_excel
        (mismo builder que el HTML y el PDF) para que los tres coincidan."""
        wizard = request.env["asovec.cobro_mensual_consulta_wizard"].browse(wizard_id).exists()
        if not wizard:
            return request.not_found()

        wizard.action_generar_excel()

        return request.make_response(
            base64.b64decode(wizard.file_data),
            headers=[
                ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                ("Content-Disposition", content_disposition(wizard.file_name)),
            ],
        )

    @http.route("/asovec/residencia_config/<int:wizard_id>/xlsx", type="http", auth="user")
    def residencia_config_xlsx(self, wizard_id, **kwargs):
        """Genera y descarga el Excel de configuración de residencias directamente
        desde el reporte HTML, sin tener que volver al wizard."""
        wizard = request.env["asovec.residencia_config_wizard"].browse(wizard_id).exists()
        if not wizard:
            return request.not_found()

        wizard.action_generar_excel()

        return request.make_response(
            base64.b64decode(wizard.file_data),
            headers=[
                ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                ("Content-Disposition", content_disposition(wizard.file_name)),
            ],
        )
