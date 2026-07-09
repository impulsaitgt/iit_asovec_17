# -*- coding: utf-8 -*-
import base64
import csv
import io
from datetime import date

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .contador import MONTH_SELECTION


class ProcesoCargaDeudasWizard(models.TransientModel):
    _name = "asovec.proceso_carga_deudas_wizard"
    _description = "Cargar Deudas/Facturas Anteriores (Migración)"

    # Carga en lotes acotados para no exceder el tiempo límite de una sola
    # petición web (igual estrategia que "Completar Faltantes" en Cobros Mensuales).
    _CHUNK_SIZE = 200
    _CONFIRM_CHUNK_SIZE = 150

    archivo = fields.Binary(string="Archivo CSV", required=True)
    archivo_filename = fields.Char(string="Nombre de archivo")

    diario_1_id = fields.Many2one(
        "account.journal", string="Diario (columna 4)", required=True,
        help="Diario contable con el que se crearán los cargos de la columna 4 del CSV.",
    )
    mes_1 = fields.Selection(MONTH_SELECTION, string="Mes (columna 4)", required=True)
    anio_1 = fields.Integer(string="Año (columna 4)", required=True, default=lambda self: fields.Date.today().year)

    diario_2_id = fields.Many2one(
        "account.journal", string="Diario (columna 5)", required=True,
        help="Diario contable con el que se crearán los cargos de la columna 5 del CSV.",
    )
    mes_2 = fields.Selection(MONTH_SELECTION, string="Mes (columna 5)", required=True)
    anio_2 = fields.Integer(string="Año (columna 5)", required=True, default=lambda self: fields.Date.today().year)

    state = fields.Selection(
        selection=[
            ("draft", "Preparar"),
            ("en_proceso", "En proceso"),
            ("completo", "Completo"),
            ("con_error", "Con error"),
            ("confirmado", "Confirmado"),
        ],
        default="draft",
        readonly=True,
    )

    line_ids = fields.One2many(
        comodel_name="asovec.proceso_carga_deudas_wizard.line",
        inverse_name="wizard_id",
        string="Filas",
    )

    total_filas = fields.Integer(readonly=True)
    total_generados = fields.Integer(string="Cargos generados", readonly=True)
    total_errores = fields.Integer(string="Filas con error", readonly=True, compute="_compute_totales")
    total_pendientes = fields.Integer(string="Filas pendientes de procesar", readonly=True, compute="_compute_totales")
    total_pendientes_confirmar = fields.Integer(
        string="Cargos pendientes de confirmar", readonly=True, compute="_compute_totales"
    )

    log = fields.Text(readonly=True)

    @api.depends(
        "line_ids.error", "line_ids.procesado",
        "line_ids.move_1_id.state", "line_ids.move_2_id.state",
    )
    def _compute_totales(self):
        for rec in self:
            rec.total_errores = len(rec.line_ids.filtered("error"))
            rec.total_pendientes = len(rec.line_ids.filtered(lambda l: not l.procesado))
            moves = rec.line_ids.mapped("move_1_id") | rec.line_ids.mapped("move_2_id")
            rec.total_pendientes_confirmar = len(moves.filtered(lambda m: m.state == "draft"))

    # -------------------------
    # Parseo del archivo
    # -------------------------
    @api.model
    def _parse_monto(self, value):
        value = (value or "").strip()
        if not value:
            return 0.0
        try:
            return float(value)
        except ValueError:
            return 0.0

    def _parsear_archivo(self):
        self.ensure_one()
        raw = base64.b64decode(self.archivo)
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")

        reader = csv.reader(io.StringIO(text))
        lines_vals = []
        for row in reader:
            if not row or not (row[0] or "").strip():
                continue
            code = row[0].strip()
            monto_1 = self._parse_monto(row[3]) if len(row) > 3 else 0.0
            monto_2 = self._parse_monto(row[4]) if len(row) > 4 else 0.0
            lines_vals.append((0, 0, {
                "residencia_code": code,
                "monto_1": monto_1,
                "monto_2": monto_2,
            }))

        if not lines_vals:
            raise UserError(_("El archivo no tiene filas válidas."))

        self.line_ids = lines_vals
        self.total_filas = len(lines_vals)

    # -------------------------
    # Generación de cargos
    # -------------------------
    def _get_producto_migrado(self):
        producto = self.env["product.template"].search(
            [("tipo_servicio_aso_id.aso_migrado", "=", True)], limit=1
        )
        if not producto or not producto.product_variant_id:
            raise UserError(_(
                "No existe un producto con Tipo de Servicio marcado como 'Migrado'. "
                "Configure uno antes de continuar."
            ))
        return producto

    def _crear_cargo(self, residencia, producto, diario, anio, mes, monto):
        fecha = date(int(anio), int(mes), 1)
        return self.env["account.move"].create({
            "move_type": "out_invoice",
            "company_id": self.env.company.id,
            "journal_id": diario.id,
            "partner_id": residencia.cliente_id.id,
            "residencia_id": residencia.id,
            "invoice_date": fecha,
            "ref": _("Migración %s - %s/%s") % (residencia.display_name, mes, anio),
            "invoice_line_ids": [(0, 0, {
                "product_id": producto.product_variant_id.id,
                "name": producto.name,
                "quantity": 1.0,
                "price_unit": monto,
                "tax_ids": [(6, 0, [])],
            })],
        })

    def action_procesar(self):
        self.ensure_one()

        if not self.line_ids:
            self._parsear_archivo()

        pendientes = self.line_ids.filtered(lambda l: not l.procesado)
        if not pendientes:
            self._actualizar_estado_final()
            return self._reabrir_form_action()

        lote = pendientes[: self._CHUNK_SIZE]

        producto = self._get_producto_migrado()
        Residencia = self.env["asovec.residencia"]

        generados = 0
        for line in lote:
            residencia = Residencia.search([("name", "=", line.residencia_code)], limit=1)
            if not residencia:
                line.error = _("Residencia '%s' no encontrada.") % line.residencia_code
                continue
            if not residencia.cliente_id:
                line.error = _("La residencia '%s' no tiene cliente asignado.") % line.residencia_code
                continue

            creados_en_linea = 0
            try:
                with self.env.cr.savepoint():
                    if line.monto_1 > 0 and not line.move_1_id:
                        move = self._crear_cargo(
                            residencia, producto, self.diario_1_id, self.anio_1, self.mes_1, line.monto_1
                        )
                        line.move_1_id = move.id
                        creados_en_linea += 1
                    if line.monto_2 > 0 and not line.move_2_id:
                        move = self._crear_cargo(
                            residencia, producto, self.diario_2_id, self.anio_2, self.mes_2, line.monto_2
                        )
                        line.move_2_id = move.id
                        creados_en_linea += 1
            except Exception as e:
                line.error = str(e)
            else:
                line.error = False
                line.procesado = True
                generados += creados_en_linea

        self.total_generados += generados
        self._actualizar_estado_final(generados_en_lote=generados)
        self.env.cr.commit()

        return self._reabrir_form_action()

    def _actualizar_estado_final(self, generados_en_lote=None):
        self.ensure_one()
        con_error = self.line_ids.filtered("error")
        pendientes = self.line_ids.filtered(lambda l: not l.procesado)

        partes = []
        if generados_en_lote is not None:
            partes.append(_("Se generaron %s cargos en este lote.") % generados_en_lote)

        if con_error:
            self.state = "con_error"
            partes.append(_(
                "%s fila(s) con error de %s en total. Corrige los datos (residencia o "
                "cliente) y vuelve a presionar 'Procesar' para reintentar."
            ) % (len(con_error), self.total_filas))
        elif pendientes:
            self.state = "en_proceso"
            partes.append(_(
                "Faltan %s de %s filas: vuelve a presionar 'Procesar' para continuar."
            ) % (len(pendientes), self.total_filas))
        else:
            self.state = "completo"
            partes.append(_(
                "Completo: %s cargos generados en borrador para %s filas. Ya puedes "
                "presionar 'Confirmar Todos'."
            ) % (self.total_generados, self.total_filas))

        self.log = ((self.log or "") + "\n" + " ".join(partes)).strip()

    # -------------------------
    # Confirmación de cargos
    # -------------------------
    def action_confirmar_todos(self):
        self.ensure_one()
        if self.state not in ("completo", "confirmado"):
            raise UserError(_("Solo puedes confirmar cuando la carga esté completa y sin errores."))

        moves = (self.line_ids.mapped("move_1_id") | self.line_ids.mapped("move_2_id"))
        moves = moves.filtered(lambda m: m.state == "draft")

        if not moves:
            self.log = ((self.log or "") + "\n" + _("No hay cargos pendientes de confirmar.")).strip()
            self.state = "confirmado"
            return self._reabrir_form_action()

        lote = moves[: self._CONFIRM_CHUNK_SIZE]
        try:
            lote.action_post()
        except Exception as e:
            self.env.cr.commit()
            raise UserError(_("Se detuvo al confirmar: %s") % str(e))

        faltan = len(moves) - len(lote)
        if faltan:
            self.log = ((self.log or "") + "\n" + _(
                "Se confirmaron %s cargos. Faltan %s: vuelve a presionar 'Confirmar Todos' para continuar."
            ) % (len(lote), faltan)).strip()
        else:
            self.log = ((self.log or "") + "\n" + _("Se confirmaron todos los cargos.")).strip()
            self.state = "confirmado"

        self.env.cr.commit()

        return self._reabrir_form_action()

    def _reabrir_form_action(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "views": [(False, "form")],
            "res_id": self.id,
            "target": "new",
        }


class ProcesoCargaDeudasWizardLine(models.TransientModel):
    _name = "asovec.proceso_carga_deudas_wizard.line"
    _description = "Fila de Carga de Deudas/Facturas Anteriores"

    wizard_id = fields.Many2one(
        "asovec.proceso_carga_deudas_wizard", required=True, ondelete="cascade", index=True
    )
    residencia_code = fields.Char(string="Residencia", required=True)
    monto_1 = fields.Float(string="Monto col. 4")
    monto_2 = fields.Float(string="Monto col. 5")
    procesado = fields.Boolean(default=False)
    error = fields.Char(string="Error")
    move_1_id = fields.Many2one("account.move", string="Cargo col. 4")
    move_2_id = fields.Many2one("account.move", string="Cargo col. 5")
