Some databases configure the currencies (MXN, USD...) with more than 2
decimals, for instance 6, to keep the exact amounts of the accounting. The
CFDI then prints the amounts with those 6 decimals (`SubTotal="41753.115000"`)
and the PAC rejects the invoices and the payment complements, because the SAT
only accepts the decimals of the currency catalog (2 for MXN and USD).

This module keeps the accounting with 6 decimals and stamps the CFDI with the
decimals the SAT accepts:

- Invoices and credit notes: `SubTotal`, `Descuento`, the document taxes and
  `Total` are rounded HALF-UP to 2 decimals, and `Total` is computed from the
  rounded amounts (local taxes included), so the arithmetic the PAC checks
  holds.
- Payment complements: `ImpSaldoAnt`, `ImpPagado`, `ImpSaldoInsoluto`,
  `BaseDR` and `ImporteDR` have 2 decimals (`ImporteDR` within the CRP20261
  limits), `BaseP`/`ImporteP` are the sum of the DR amounts divided by
  `EquivalenciaDR` rounded to 6 decimals without trailing zeros (CRP20268,
  CRP20274, CRPER654), `Monto` is built from the rounded `ImpPagado`
  (CRP20217) and the `Totales` from the P amounts of every `Pago` node.
