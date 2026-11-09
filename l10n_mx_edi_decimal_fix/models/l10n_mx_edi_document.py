from odoo import api, models
from odoo.tools.float_utils import float_round

# Decimals the SAT catalog (c_Moneda) supports for MXN, USD... The currency may
# be configured with more (6 in some databases), so they can not be read from
# l10n_mx_edi_decimal_places.
SAT_CURRENCY_DIGITS = 2


def round_sat(amount):
    """Round HALF-UP to the decimals the SAT supports for the currency."""
    return float_round(
        amount, precision_digits=SAT_CURRENCY_DIGITS, rounding_method="HALF-UP"
    )


class L10nMxEdiDocument(models.Model):
    _inherit = "l10n_mx_edi.document"

    @api.model
    def _add_currency_cfdi_values(self, cfdi_values, currency):
        # EXTENDS l10n_mx_edi
        res = super()._add_currency_cfdi_values(cfdi_values, currency)
        format_float = cfdi_values["format_float"]

        def format_float_min_precision(
            amount, precision=cfdi_values["currency_precision"], min_precision=None
        ):
            """Same as format_float, optionally dropping the trailing zeros beyond
            min_precision: "28200.000000" -> "28200.00",
            "18796.718750" -> "18796.71875".
            """
            formatted = format_float(amount, precision=precision)
            if formatted is None or min_precision is None or "." not in formatted:
                return formatted
            integer, decimals = formatted.split(".")
            return f"{integer}.{decimals.rstrip('0').ljust(min_precision, '0')}"

        cfdi_values["format_float"] = format_float_min_precision
        return res

    @api.model
    def _add_base_lines_cfdi_values(
        self, cfdi_values, base_lines, global_invoice=False
    ):
        """Express the amounts of the document with the SAT decimals.

        With a currency configured with more decimals, the document amounts keep
        them (SubTotal="41753.115000"). Round each one HALF-UP and build the
        totals from the rounded amounts, so that the arithmetic the PAC checks
        (Total = SubTotal - Descuento + taxes) holds with the printed values.
        """
        # EXTENDS l10n_mx_edi
        res = super()._add_base_lines_cfdi_values(
            cfdi_values, base_lines, global_invoice=global_invoice
        )
        for key in (
            "retenciones_list",
            "traslados_list",
            "local_retenciones_list",
            "local_traslados_list",
        ):
            for tax_values in cfdi_values[key]:
                for amount_key in ("base", "importe"):
                    if tax_values.get(amount_key) is not None:
                        tax_values[amount_key] = round_sat(tax_values[amount_key])
        for total_key, key in (
            ("total_impuestos_trasladados", "traslados_list"),
            ("total_local_impuestos_trasladados", "local_traslados_list"),
            ("total_impuestos_retenidos", "retenciones_list"),
            ("total_local_impuestos_retenidos", "local_retenciones_list"),
        ):
            if cfdi_values[total_key] is not None:
                cfdi_values[total_key] = round_sat(
                    sum(
                        tax_values["importe"]
                        for tax_values in cfdi_values[key]
                        if tax_values["importe"] is not None
                    )
                )
        cfdi_values["subtotal"] = round_sat(cfdi_values["subtotal"])
        if cfdi_values["descuento"] is not None:
            cfdi_values["descuento"] = round_sat(cfdi_values["descuento"])
        cfdi_values["total"] = round_sat(
            cfdi_values["subtotal"]
            - (cfdi_values["descuento"] or 0.0)
            + (cfdi_values["total_impuestos_trasladados"] or 0.0)
            - (cfdi_values["total_impuestos_retenidos"] or 0.0)
            + cfdi_values["total_local_impuestos_trasladados"]
            - cfdi_values["total_local_impuestos_retenidos"]
        )
        return res
