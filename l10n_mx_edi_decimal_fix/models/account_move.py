from collections import defaultdict

from odoo import models
from odoo.tools.float_utils import float_round

from .l10n_mx_edi_document import SAT_CURRENCY_DIGITS, round_sat

# pago20:Totales attributes fed by each tax of pago20:ImpuestosP, as
# (impuesto, tipo_factor, tasa_o_cuota): (base total, importe total).
TRASLADOS_TOTALS = {
    ("002", "Tasa", 0.0): (
        "total_traslados_base_iva0",
        "total_traslados_impuesto_iva0",
    ),
    ("002", "Exento", 0.0): ("total_traslados_base_iva_exento", None),
    ("002", "Tasa", 0.08): (
        "total_traslados_base_iva8",
        "total_traslados_impuesto_iva8",
    ),
    ("002", "Tasa", 0.16): (
        "total_traslados_base_iva16",
        "total_traslados_impuesto_iva16",
    ),
}
RETENCIONES_TOTALS = {
    "001": "total_retenciones_isr",
    "002": "total_retenciones_iva",
    "003": "total_retenciones_ieps",
}
TOTALS = [
    total_key
    for total_keys in TRASLADOS_TOTALS.values()
    for total_key in total_keys
    if total_key
] + list(RETENCIONES_TOTALS.values())


class AccountMove(models.Model):
    _inherit = "account.move"

    def _l10n_mx_edi_add_payment_cfdi_values(self, cfdi_values, pay_results):
        """Express the payment complement amounts with the SAT decimals.

        With a 6 decimals currency every amount keeps 6 decimals, and the PAC
        rejects the payment:

        - BaseDR/ImporteDR are rounded to 2 decimals first, ImporteDR within the
          CRP20261 limits, and the P amounts are built from them
          (CRP20268/CRP20274).
        - BaseP/ImporteP are the sum of those DR amounts divided by
          EquivalenciaDR, rounded to 6 decimals; the template drops the
          trailing zeros beyond the decimals of MonedaP (CRPER654).
        - Monto is built from the rounded ImpPagado, so that their sum never
          exceeds it (CRP20217).
        - The totals are the P amounts times TipoCambioP rounded to 2 decimals.
        """
        # EXTENDS l10n_mx_edi
        res = super()._l10n_mx_edi_add_payment_cfdi_values(cfdi_values, pay_results)
        if cfdi_values.get("errors"):
            return res

        amounts_mxn = defaultdict(float)
        monto_total_pagos = 0.0
        for payment_values in cfdi_values["payment_list"]:
            doctos = payment_values["dcto_relationado_list"]
            for docto in doctos:
                docto["imp_saldo_ant"] = round_sat(docto["imp_saldo_ant"])
                docto["imp_pagado"] = round_sat(docto["imp_pagado"])
                # ImpSaldoInsoluto = ImpSaldoAnt - ImpPagado with the printed
                # amounts; it also avoids the -0.000001 left by a full payment.
                docto["imp_saldo_insoluto"] = round_sat(
                    docto["imp_saldo_ant"] - docto["imp_pagado"]
                )
                for key in ("retenciones_list", "traslados_list"):
                    for tax_values in docto[key]:
                        self._l10n_mx_edi_decimal_fix_round_tax_values(tax_values)

            for key in ("retenciones_list", "traslados_list"):
                for tax_values in payment_values[key]:
                    self._l10n_mx_edi_decimal_fix_set_payment_tax_values(
                        tax_values, doctos, key
                    )

            payment_values["monto"] = round_sat(
                sum(
                    docto["imp_pagado"] / (docto["equivalencia"] or 1.0)
                    for docto in doctos
                )
            )
            pay_rate = payment_values["tipo_cambio"] or 1.0
            monto_total_pagos += payment_values["monto"] * pay_rate
            for tax_values in payment_values["traslados_list"]:
                tax_key = (
                    tax_values["impuesto"],
                    tax_values["tipo_factor"],
                    float_round(tax_values["tasa_o_cuota"] or 0.0, 6),
                )
                base_key, importe_key = TRASLADOS_TOTALS.get(tax_key, (None, None))
                if base_key:
                    amounts_mxn[base_key] += tax_values["base"] * pay_rate
                if importe_key:
                    amounts_mxn[importe_key] += tax_values["importe"] * pay_rate
            for tax_values in payment_values["retenciones_list"]:
                total_key = RETENCIONES_TOTALS.get(tax_values["impuesto"])
                if total_key:
                    amounts_mxn[total_key] += tax_values["importe"] * pay_rate

        cfdi_values.update(
            {
                key: round_sat(amounts_mxn[key]) if key in amounts_mxn else None
                for key in TOTALS
            }
        )
        cfdi_values.update(
            {
                "monto_total_pagos": round_sat(monto_total_pagos),
                "mxn_digits": SAT_CURRENCY_DIGITS,
            }
        )
        return res

    def _l10n_mx_edi_decimal_fix_round_tax_values(self, tax_values):
        """Round BaseDR/ImporteDR to the SAT decimals of MonedaDR."""
        base, importe = tax_values["base"], tax_values["importe"]
        tax_values["base"] = round_sat(base)
        if importe is None:
            return
        # Keep BaseDR + ImporteDR equal to the rounded sum of both amounts.
        importe = round_sat(round_sat(base + importe) - tax_values["base"])
        if tax_values["tipo_factor"] == "Tasa":
            # CRP20261: keep ImporteDR within [trunc, ceil] of BaseDR * Tasa.
            expected = float_round(tax_values["base"] * tax_values["tasa_o_cuota"], 6)
            lower = float_round(expected, SAT_CURRENCY_DIGITS, rounding_method="DOWN")
            upper = float_round(expected, SAT_CURRENCY_DIGITS, rounding_method="UP")
            importe = min(max(importe, lower), upper)
        tax_values["importe"] = importe

    def _l10n_mx_edi_decimal_fix_set_payment_tax_values(self, tax_values, doctos, key):
        """BaseP/ImporteP = sum(BaseDR/ImporteDR / EquivalenciaDR), 6 decimals."""
        dr_amounts = [
            (dr_values, docto["equivalencia"] or 1.0)
            for docto in doctos
            for dr_values in docto[key]
            if (
                dr_values["impuesto"],
                dr_values["tipo_factor"],
                dr_values["tasa_o_cuota"],
            )
            == (
                tax_values["impuesto"],
                tax_values["tipo_factor"],
                tax_values["tasa_o_cuota"],
            )
        ]
        tax_values["base"] = float_round(
            sum(dr_values["base"] / rate for dr_values, rate in dr_amounts), 6
        )
        if tax_values["importe"] is not None:
            tax_values["importe"] = float_round(
                sum(dr_values["importe"] / rate for dr_values, rate in dr_amounts), 6
            )
