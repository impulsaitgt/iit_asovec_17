# -*- coding: utf-8 -*-
import base64
import csv
import io
from collections import defaultdict
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare

from .contador import MONTH_SELECTION, mes_anio_anterior


class ProcesoCargaPagosBancoWizard(models.TransientModel):
    _name = "asovec.proceso_carga_pagos_banco_wizard"
    _description = "Carga de Pagos del Banco (CSV manual, mientras no exista Servipagos)"

    # Igual estrategia de lotes acotados que "Cargar Deudas/Facturas Anteriores" y
    # "Completar Faltantes": evita exceder el tiempo límite de una sola petición web.
    _VALIDAR_CHUNK_SIZE = 200
    _PAGAR_CHUNK_SIZE = 80

    mes = fields.Selection(MONTH_SELECTION, string="Mes", required=True)
    anio = fields.Integer(string="Año", required=True)

    journal_ids = fields.Many2many(
        "account.journal", string="Diarios de Venta", required=True,
        domain="[('type', '=', 'sale')]",
        help="Diarios a considerar para buscar los cargos pendientes (mes y anteriores). "
             "Por defecto sugiere los diarios 'Cargo Asociacion = Si', pero se pueden "
             "agregar otros diarios de Venta aunque no sean de asociación (por ejemplo, "
             "si hay deuda migrada en un diario distinto). A propósito NO se filtran aquí "
             "los diarios que no tengan 'Diario Relacionado' configurado: esa validación "
             "se hace fila por fila, para poder señalar exactamente qué diario falta "
             "configurar en vez de ocultar el diario de la lista.",
    )

    archivo = fields.Binary(string="Archivo CSV", required=True)
    archivo_filename = fields.Char(string="Nombre de archivo")

    state = fields.Selection(
        selection=[
            ("draft", "Preparar"),
            ("con_error", "Con error"),
            ("validado", "Validado"),
            ("procesando", "Generando pagos"),
            ("completo", "Completo"),
        ],
        default="draft",
        readonly=True,
    )

    line_ids = fields.One2many(
        comodel_name="asovec.proceso_carga_pagos_banco_wizard.line",
        inverse_name="wizard_id",
        string="Filas",
    )

    total_filas = fields.Integer(readonly=True)
    total_generados = fields.Integer(string="Pagos generados", readonly=True)
    total_errores = fields.Integer(string="Filas con error", readonly=True, compute="_compute_totales")
    total_errores_pago = fields.Integer(
        string="Filas con error al generar pago", readonly=True, compute="_compute_totales",
        help="Filas que validaron correctamente pero fallaron al generar/confirmar el pago "
             "(por ejemplo, un rechazo de Hacienda al confirmar). Para reintentarlas, sube un "
             "CSV nuevo que cuadre solo con esas residencias.",
    )
    total_pendientes_validar = fields.Integer(string="Filas pendientes de validar", readonly=True, compute="_compute_totales")
    total_pendientes_pagar = fields.Integer(string="Filas pendientes de generar pago", readonly=True, compute="_compute_totales")

    log = fields.Text(readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        mes, anio = mes_anio_anterior(fields.Date.context_today(self))
        if "mes" in fields_list and not res.get("mes"):
            res["mes"] = mes
        if "anio" in fields_list and not res.get("anio"):
            res["anio"] = anio
        if "journal_ids" in fields_list and not res.get("journal_ids"):
            journal_aso = self.env["account.journal"].search([
                ("aso_cargo", "=", "Si"),
                ("type", "=", "sale"),
                ("company_id", "=", self.env.company.id),
            ])
            if journal_aso:
                res["journal_ids"] = [(6, 0, journal_aso.ids)]
        return res

    @api.depends("line_ids.error", "line_ids.etapa_error", "line_ids.validado", "line_ids.procesado")
    def _compute_totales(self):
        for rec in self:
            rec.total_errores = len(rec.line_ids.filtered("error"))
            rec.total_errores_pago = len(rec.line_ids.filtered(lambda l: l.error and l.etapa_error == "pago"))
            rec.total_pendientes_validar = len(rec.line_ids.filtered(lambda l: not l.validado))
            rec.total_pendientes_pagar = len(
                rec.line_ids.filtered(lambda l: l.validado and not l.error and not l.procesado)
            )

    # -------------------------
    # Parseo del archivo
    # -------------------------
    @api.model
    def _parse_monto(self, value):
        value = (value or "").strip()
        if not value:
            return 0.0
        value = value.replace("Q.", "").replace("Q", "").replace(",", "").strip()
        if not value:
            return 0.0
        try:
            return float(value)
        except ValueError:
            return 0.0

    @api.model
    def _parse_fecha(self, value):
        value = (value or "").strip()
        if not value:
            return False
        try:
            d, m, y = value.split("/")
            return date(int(y), int(m), int(d))
        except Exception:
            return False

    def _parsear_archivo(self):
        self.ensure_one()
        raw = base64.b64decode(self.archivo)
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")

        reader = csv.DictReader(io.StringIO(text))
        lines_vals = []
        for row in reader:
            codigo = (row.get("CODIGO") or "").strip()
            correlativo = (row.get("CORRELATIVO") or "").strip()
            if not codigo or not correlativo:
                continue
            if correlativo.lower().startswith("transacciones"):
                # Fila de totales al final del archivo del banco: no es un pago.
                continue

            lines_vals.append((0, 0, {
                "correlativo": correlativo,
                "residencia_code": codigo,
                "nombre": (row.get("NOMBRE") or "").strip(),
                "direccion": (row.get("DIRECCION") or "").strip(),
                "cuota": self._parse_monto(row.get("CUOTA")),
                "saldo": self._parse_monto(row.get("SALDO")),
                "mora": self._parse_monto(row.get("MORA")),
                "fecha": self._parse_fecha(row.get("FECHA")),
                "fecha_texto": (row.get("FECHA") or "").strip(),
                "nombre_agencia": (row.get("NOMBRE AGENCIA") or "").strip(),
                "efectivo": self._parse_monto(row.get("EFECTIVO")),
                "cheque_bi": self._parse_monto(row.get("CHEQUE BI")),
                "cheque_ob": self._parse_monto(row.get("CHEQUE OB")),
                "cheque_be": self._parse_monto(row.get("CHEQUE BE")),
                "no_chq_ob": (row.get("NO. CHQ. OB") or "").strip(),
                "no_boleta": (row.get("NO. BOLETA") or "").strip(),
                "monto_total": self._parse_monto(row.get("MONTO TOTAL")),
                "pago_con_tc": (row.get("PAGO CON TC") or "").strip(),
            }))

        if not lines_vals:
            raise UserError(_("El archivo no tiene filas válidas."))

        self.line_ids = lines_vals
        self.total_filas = len(lines_vals)

    # -------------------------
    # Búsqueda de cargos no pagados (mismo criterio que "Generar CSV de Estado de
    # Cuenta (Banco)", pero devolviendo las facturas en vez de solo el monto, para
    # poder reconciliarlas al generar el pago).
    # -------------------------
    def _get_cargos_no_pagados(self, residencia):
        self.ensure_one()
        mes_int = int(self.mes)
        mes_padded = str(mes_int).zfill(2)
        fecha_mes = date(self.anio, mes_int, 1)

        CobroLine = self.env["asovec.proyecto_cobro_mensual_line"]
        lineas = CobroLine.search([
            ("residencia_id", "=", residencia.id),
            ("move_id.journal_id", "in", self.journal_ids.ids),
            ("move_id.state", "=", "posted"),
            ("cobro_id.state", "!=", "cancel"),
        ])
        del_mes = lineas.filtered(lambda l: l.month == mes_padded and l.year == self.anio)
        anteriores = lineas.filtered(lambda l: (l.year, int(l.month)) < (self.anio, mes_int))

        moves_del_mes = del_mes.mapped("move_id").filtered(lambda m: m.amount_residual > 0)
        moves_anteriores = anteriores.mapped("move_id").filtered(lambda m: m.amount_residual > 0)

        # Deudas migradas (facturas sueltas con residencia_id, sin línea de cobro
        # mensual): ver comentario equivalente en proceso_estado_cuenta_csv_wizard.
        Move = self.env["account.move"]
        migrados = Move.search([
            ("residencia_id", "=", residencia.id),
            ("journal_id", "in", self.journal_ids.ids),
            ("state", "=", "posted"),
            ("invoice_line_ids.product_id.product_tmpl_id.tipo_servicio_aso_id.aso_migrado", "=", True),
        ])
        moves_del_mes |= migrados.filtered(lambda m: m.invoice_date == fecha_mes and m.amount_residual > 0)
        moves_anteriores |= migrados.filtered(
            lambda m: m.invoice_date and m.invoice_date < fecha_mes and m.amount_residual > 0
        )

        return moves_del_mes, moves_anteriores

    # -------------------------
    # Validación
    # -------------------------
    def _validar_linea(self, line):
        self.ensure_one()
        residencia = self.env["asovec.residencia"].search([("name", "=", line.residencia_code)], limit=1)
        if not residencia:
            line.write({
                "error": _("Residencia '%s' no encontrada.") % line.residencia_code,
                "etapa_error": "validacion",
                "validado": True,
            })
            return
        if not residencia.cliente_id:
            line.write({
                "residencia_id": residencia.id,
                "error": _("La residencia '%s' no tiene cliente asignado.") % residencia.name,
                "etapa_error": "validacion",
                "validado": True,
            })
            return

        moves_del_mes, moves_anteriores = self._get_cargos_no_pagados(residencia)
        saldo_mes = sum(moves_del_mes.mapped("amount_residual"))
        saldo_anterior = sum(moves_anteriores.mapped("amount_residual"))

        errores = []
        if float_compare(saldo_mes, line.cuota, precision_digits=2) != 0:
            errores.append(_("Cuota no cuadra (CSV: %.2f, Sistema: %.2f)") % (line.cuota, saldo_mes))
        if float_compare(saldo_anterior, line.saldo, precision_digits=2) != 0:
            errores.append(_("Saldo no cuadra (CSV: %.2f, Sistema: %.2f)") % (line.saldo, saldo_anterior))

        if not errores:
            moves_totales = moves_del_mes | moves_anteriores
            sin_diario = moves_totales.filtered(lambda m: not m.journal_id.diario_relacionado_id)
            if sin_diario:
                diarios = ", ".join(sorted(set(sin_diario.mapped("journal_id.name"))))
                errores.append(_("El/los diario(s) '%s' no tiene(n) Diario Relacionado configurado.") % diarios)

        line.write({
            "residencia_id": residencia.id,
            "saldo_mes_calculado": saldo_mes,
            "saldo_anterior_calculado": saldo_anterior,
            "error": " | ".join(errores) if errores else False,
            "etapa_error": "validacion" if errores else False,
            "validado": True,
        })

    def action_validar(self):
        self.ensure_one()

        if not self.line_ids:
            self._parsear_archivo()

        pendientes = self.line_ids.filtered(lambda l: not l.validado)
        if not pendientes:
            self._actualizar_estado_validacion()
            return self._reabrir_form_action()

        lote = pendientes[: self._VALIDAR_CHUNK_SIZE]
        for line in lote:
            self._validar_linea(line)

        self._actualizar_estado_validacion(validadas_en_lote=len(lote))
        self.env.cr.commit()

        return self._reabrir_form_action()

    def _actualizar_estado_validacion(self, validadas_en_lote=None):
        self.ensure_one()
        con_error = self.line_ids.filtered("error")
        pendientes = self.line_ids.filtered(lambda l: not l.validado)

        partes = []
        if validadas_en_lote is not None:
            partes.append(_("Se validaron %s fila(s) en este lote.") % validadas_en_lote)

        if pendientes:
            partes.append(_(
                "Faltan %s de %s filas por validar: vuelve a presionar 'Validar' para continuar."
            ) % (len(pendientes), self.total_filas))
        elif con_error:
            self.state = "con_error"
            partes.append(_(
                "%s fila(s) con error de %s en total. Corrige los datos (residencia, saldo o "
                "configuración de diarios) y vuelve a presionar 'Validar' para reintentar."
            ) % (len(con_error), self.total_filas))
        else:
            self.state = "validado"
            partes.append(_(
                "Validación completa: %s filas cuadran exactamente. Ya puedes presionar "
                "'Generar Pagos'."
            ) % self.total_filas)

        self.log = ((self.log or "") + "\n" + " ".join(partes)).strip()

    # -------------------------
    # Generación de pagos
    # -------------------------
    @api.model
    def _fmt2(self, value):
        return "%.2f" % (value or 0.0)

    def _datos_banco_vals(self, line):
        """Información complementaria del CSV del banco (columna FECHA en adelante) que
        se graba tal cual en el pago generado, para que quede visible en su ficha sin
        tener que volver a abrir este wizard (transitorio, se purga con el tiempo)."""
        return {
            "aso_pago_banco_correlativo": line.correlativo,
            "aso_pago_banco_codigo": line.residencia_code,
            "aso_pago_banco_fecha": line.fecha_texto,
            "aso_pago_banco_agencia": line.nombre_agencia,
            "aso_pago_banco_efectivo": self._fmt2(line.efectivo),
            "aso_pago_banco_cheque_bi": self._fmt2(line.cheque_bi),
            "aso_pago_banco_cheque_ob": self._fmt2(line.cheque_ob),
            "aso_pago_banco_cheque_be": self._fmt2(line.cheque_be),
            "aso_pago_banco_no_chq_ob": line.no_chq_ob,
            "aso_pago_banco_no_boleta": line.no_boleta,
            "aso_pago_banco_monto_total": self._fmt2(line.monto_total),
            "aso_pago_banco_pago_con_tc": line.pago_con_tc,
        }

    def _generar_pagos_linea(self, line):
        self.ensure_one()
        residencia = line.residencia_id
        moves_del_mes, moves_anteriores = self._get_cargos_no_pagados(residencia)
        moves = moves_del_mes | moves_anteriores
        if not moves:
            return 0

        fecha_pago = line.fecha or fields.Date.context_today(self)

        grupos = defaultdict(lambda: self.env["account.move"])
        diario_por_id = {}
        for move in moves:
            diario_pago = move.journal_id.diario_relacionado_id
            grupos[diario_pago.id] |= move
            diario_por_id[diario_pago.id] = diario_pago

        pagos_creados = self.env["account.payment"]
        for diario_id, moves_grupo in grupos.items():
            if not diario_id:
                raise UserError(_(
                    "El diario '%s' no tiene Diario Relacionado configurado."
                ) % moves_grupo[:1].journal_id.name)
            diario_pago = diario_por_id[diario_id]
            register = self.env["account.payment.register"].with_context(
                active_model="account.move",
                active_ids=moves_grupo.ids,
            ).create({
                "journal_id": diario_pago.id,
                "payment_date": fecha_pago,
                "group_payment": True,
            })
            pagos_creados |= register._create_payments()

        pagos_creados.write(self._datos_banco_vals(line))
        line.payment_ids = [(6, 0, pagos_creados.ids)]
        return len(pagos_creados)

    def action_generar_pagos(self):
        self.ensure_one()
        if self.state not in ("validado", "procesando"):
            raise UserError(_("Solo puedes generar pagos cuando la validación esté completa y sin errores."))

        pendientes = self.line_ids.filtered(lambda l: not l.procesado)
        if not pendientes:
            self.state = "completo"
            return self._reabrir_form_action()

        lote = pendientes[: self._PAGAR_CHUNK_SIZE]

        generados = 0
        fallidas_en_lote = []
        for line in lote:
            try:
                with self.env.cr.savepoint():
                    generados += self._generar_pagos_linea(line)
            except Exception as e:
                # Una residencia con error (por ejemplo, un rechazo de Hacienda al
                # confirmar el pago/recibo FEL) NUNCA debe detener el resto del lote:
                # se deja constancia clara de cuál falló y se continúa con las demás.
                # El savepoint ya revirtió cualquier cosa parcial que se hubiera
                # alcanzado a crear para esta residencia.
                line.write({"error": str(e), "etapa_error": "pago"})
                fallidas_en_lote.append(line.residencia_code)
                continue
            line.write({"procesado": True, "error": False, "etapa_error": False})

        self.total_generados += generados

        faltan = len(self.line_ids.filtered(lambda l: not l.procesado))
        con_error_pago = self.line_ids.filtered(lambda l: l.error and l.etapa_error == "pago")
        partes = [_("Se generaron %s pago(s) en este lote.") % generados]
        if fallidas_en_lote:
            partes.append(_(
                "ATENCIÓN: fallaron %s residencia(s) en este lote (%s). En total hay %s fila(s) "
                "con error de generación de pago: revísalas en la pestaña 'Filas con error'. "
                "Para reintentarlas, corrige lo que corresponda y sube un CSV nuevo que cuadre "
                "solo con esas residencias."
            ) % (len(fallidas_en_lote), ", ".join(fallidas_en_lote), len(con_error_pago)))
        if faltan:
            self.state = "procesando"
            partes.append(_(
                "Faltan %s fila(s) por procesar: vuelve a presionar 'Generar Pagos' para continuar."
            ) % faltan)
        else:
            self.state = "completo"
            partes.append(_("Completo: se generaron %s pagos en total.") % self.total_generados)

        self.log = ((self.log or "") + "\n" + " ".join(partes)).strip()
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


class ProcesoCargaPagosBancoWizardLine(models.TransientModel):
    _name = "asovec.proceso_carga_pagos_banco_wizard.line"
    _description = "Fila de Carga de Pagos del Banco"

    wizard_id = fields.Many2one(
        "asovec.proceso_carga_pagos_banco_wizard", required=True, ondelete="cascade", index=True
    )

    correlativo = fields.Char(string="Correlativo")
    residencia_code = fields.Char(string="Código", required=True)
    residencia_id = fields.Many2one("asovec.residencia", string="Residencia")
    nombre = fields.Char(string="Nombre")
    direccion = fields.Char(string="Dirección")

    cuota = fields.Float(string="Cuota (mes)")
    saldo = fields.Float(string="Saldo (meses anteriores)")
    mora = fields.Float(string="Mora")
    fecha = fields.Date(string="Fecha de pago")
    fecha_texto = fields.Char(string="Fecha (texto CSV)")
    nombre_agencia = fields.Char(string="Agencia")
    efectivo = fields.Float(string="Efectivo")
    cheque_bi = fields.Float(string="Cheque BI")
    cheque_ob = fields.Float(string="Cheque OB")
    cheque_be = fields.Float(string="Cheque BE")
    no_chq_ob = fields.Char(string="No. Cheque OB")
    no_boleta = fields.Char(string="No. Boleta")
    monto_total = fields.Float(string="Monto total")
    pago_con_tc = fields.Char(string="Pago con TC")

    saldo_mes_calculado = fields.Float(string="Cuota (Sistema)", readonly=True)
    saldo_anterior_calculado = fields.Float(string="Saldo (Sistema)", readonly=True)

    validado = fields.Boolean(default=False)
    procesado = fields.Boolean(default=False)
    error = fields.Char(string="Error")
    etapa_error = fields.Selection(
        selection=[("validacion", "Validación"), ("pago", "Generación de pago")],
        string="Etapa del error",
        readonly=True,
        help="En qué paso ocurrió el error: al validar (datos/saldo no cuadran) o al "
             "generar/confirmar el pago (por ejemplo, un rechazo de Hacienda al confirmar).",
    )

    payment_ids = fields.Many2many(
        "account.payment",
        relation="asovec_carga_pagos_banco_line_payment_rel",
        column1="wizard_line_id", column2="payment_id",
        string="Pagos generados",
    )
