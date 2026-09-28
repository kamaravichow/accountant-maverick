"""Deterministic checks on an extracted invoice - the LLM reads, code verifies."""

from __future__ import annotations

from ..recon.normalize import parse_date
from ..validators.hsn import validate_hsn
from ..validators.identifiers import validate_gstin
from .schema import Invoice

TOL = 1.0  # rupee tolerance for rounding


def _s(*xs) -> float:
    return round(sum(x or 0 for x in xs), 2)


def validate_invoice(inv: Invoice, company_gstins: list[str] | None = None, aato: float | None = None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    # --- Rule 46 mandatory particulars ------------------------------------------------
    required = {"invoice_no": inv.invoice_no, "invoice_date": inv.invoice_date, "supplier.name": inv.supplier.name}
    if inv.document_type in ("tax_invoice", "credit_note", "debit_note"):
        required["supplier.gstin"] = inv.supplier.gstin
        if inv.buyer.gstin is None and inv.supply_type in (None, "B2B"):
            warnings.append("Recipient GSTIN missing - ITC cannot be claimed on a B2C invoice")
        if not inv.place_of_supply and not inv.place_of_supply_code:
            warnings.append("Place of supply not stated (mandatory for inter-state supplies, Rule 46(n))")
    for k, v in required.items():
        if not v:
            errors.append(f"Missing mandatory field: {k}")
    if inv.invoice_no and len(inv.invoice_no) > 16:
        warnings.append("Invoice number longer than 16 characters (Rule 46(b))")

    d = parse_date(inv.invoice_date) if inv.invoice_date else None
    if inv.invoice_date and not d:
        errors.append(f"Unreadable invoice date '{inv.invoice_date}'")

    # --- GSTINs ---------------------------------------------------------------------
    for label, g in (("supplier", inv.supplier.gstin), ("buyer", inv.buyer.gstin)):
        if g:
            v = validate_gstin(g)
            if not v["valid"]:
                errors.append(f"{label} GSTIN {g}: {'; '.join(v['errors'])}")
    if company_gstins and inv.buyer.gstin and inv.buyer.gstin.upper() not in [x.upper() for x in company_gstins]:
        warnings.append(f"Buyer GSTIN {inv.buyer.gstin} is not one of this company's GSTINs - ITC not available "
                        "to us (or this is a sales invoice)")

    # --- Tax head vs place of supply --------------------------------------------------
    sup_state = (inv.supplier.gstin or "")[:2] or inv.supplier.state_code
    pos = inv.place_of_supply_code or (inv.buyer.gstin or "")[:2] or None
    has_igst = (inv.total_igst or 0) > TOL or any((li.igst_amount or 0) > 0 for li in inv.line_items)
    has_cgst = (inv.total_cgst or 0) > TOL or any((li.cgst_amount or 0) > 0 for li in inv.line_items)
    if sup_state and pos and sup_state.isdigit() and pos.isdigit():
        inter = sup_state != pos or inv.supply_type in ("SEZWP", "SEZWOP", "EXPWP", "EXPWOP")
        if inter and has_cgst:
            errors.append(f"Inter-state supply ({sup_state} -> {pos}) charged CGST/SGST - should be IGST; ITC of "
                          "wrongly charged tax head is at risk (supplier must issue credit note & re-invoice)")
        if not inter and has_igst:
            errors.append(f"Intra-state supply (state {pos}) charged IGST - should be CGST+SGST")

    # --- Arithmetic -----------------------------------------------------------------
    line_issues = 0
    for i, li in enumerate(inv.line_items, 1):
        if li.quantity and li.unit_price and li.taxable_value is not None:
            gross = li.quantity * li.unit_price - (li.discount or 0)
            if abs(gross - li.taxable_value) > max(TOL, 0.005 * li.taxable_value):
                warnings.append(f"Line {i}: qty x rate - discount = {gross:,.2f} but taxable value is {li.taxable_value:,.2f}")
                line_issues += 1
        if li.gst_rate is not None and li.taxable_value:
            expected = li.taxable_value * li.gst_rate / 100
            charged = _s(li.cgst_amount, li.sgst_utgst_amount, li.igst_amount)
            if charged and abs(expected - charged) > max(TOL, 0.005 * expected):
                errors.append(f"Line {i}: tax {charged:,.2f} != {li.gst_rate}% of {li.taxable_value:,.2f} = {expected:,.2f}")
                line_issues += 1
            if li.cgst_amount and li.sgst_utgst_amount and abs(li.cgst_amount - li.sgst_utgst_amount) > TOL:
                errors.append(f"Line {i}: CGST and SGST should be equal")
        if li.hsn_sac or li.description:
            h = validate_hsn(li.hsn_sac, li.description, li.gst_rate, d, aato)
            for issue in h["issues"]:
                warnings.append(f"Line {i} HSN: {issue}")
    if inv.line_items:
        sums = {
            "total_taxable_value": _s(*[li.taxable_value for li in inv.line_items]),
            "total_cgst": _s(*[li.cgst_amount for li in inv.line_items]),
            "total_sgst_utgst": _s(*[li.sgst_utgst_amount for li in inv.line_items]),
            "total_igst": _s(*[li.igst_amount for li in inv.line_items]),
        }
        for k, v in sums.items():
            printed = getattr(inv, k)
            if printed is not None and abs(printed - v) > TOL:
                errors.append(f"Sum of lines {k} = {v:,.2f} but invoice shows {printed:,.2f}")
    if inv.grand_total is not None:
        computed = _s(inv.total_taxable_value, inv.total_cgst, inv.total_sgst_utgst, inv.total_igst, inv.total_cess,
                      inv.freight_other_charges, inv.tcs_amount, inv.round_off)
        if computed and abs(computed - inv.grand_total) > TOL:
            errors.append(f"Taxable + taxes + charges + round-off = {computed:,.2f} but grand total is {inv.grand_total:,.2f}")
        if inv.round_off and abs(inv.round_off) > 1:
            warnings.append(f"Round-off {inv.round_off} exceeds Rs 1")

    # --- Compliance flags -----------------------------------------------------------
    if inv.grand_total and inv.grand_total > 50000 and inv.document_type == "tax_invoice" and not inv.eway_bill_no \
            and inv.line_items and not all((li.hsn_sac or "").startswith("99") for li in inv.line_items):
        warnings.append("Goods consignment > Rs 50,000 without e-way bill number (may be exempt/intra-city - verify)")
    if inv.irn is None and inv.document_type in ("tax_invoice", "credit_note", "debit_note") and inv.buyer.gstin:
        warnings.append("No IRN: if supplier's AATO > Rs 5 cr, a B2B invoice without IRN is not a valid invoice "
                        "(ITC at risk)")
    if inv.supplier.udyam_number or inv.supplier.msme_category in ("micro", "small"):
        warnings.append("Supplier is MSME: pay within 15 days (45 with agreement) to avoid sec 43B(h) disallowance")
    if inv.illegible_fields:
        warnings.append(f"Illegible in scan: {', '.join(inv.illegible_fields)} - verify manually")

    status = "error" if errors else ("review" if warnings or inv.extraction_confidence == "low" else "ok")
    return {"status": status, "errors": errors, "warnings": warnings}
