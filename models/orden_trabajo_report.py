# -*- coding: utf-8 -*-
import base64

from odoo import models, api
from odoo.tools import image_process

LOGO_MAX_HEIGHT = 90


class ReportOrdenTrabajo(models.AbstractModel):
    _name = "report.iit_asovec.report_orden_trabajo"
    _description = "Orden de Trabajo"

    @api.model
    def _get_report_values(self, docids, data=None):
        ordenes = self.env["asovec.orden_trabajo"].browse(docids)
        logos_cache = {}

        for orden in ordenes:
            company = orden.company_id
            if company.id not in logos_cache:
                if company.logo:
                    resized = image_process(base64.b64decode(company.logo), size=(0, LOGO_MAX_HEIGHT))
                    logos_cache[company.id] = base64.b64encode(resized) if resized else False
                else:
                    logos_cache[company.id] = False

        return {
            "doc_ids": docids,
            "doc_model": "asovec.orden_trabajo",
            "docs": ordenes,
            "logos": logos_cache,
        }
