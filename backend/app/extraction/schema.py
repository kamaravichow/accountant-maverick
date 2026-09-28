"""Structured schema for Indian GST invoices (Rule 46 CGST Rules + e-invoice + e-way bill fields).

This replaces typing ~50 fields per invoice by hand: the LLM fills it from the document, and
deterministic validators (``validate.py``) check the arithmetic, GSTINs, HSNs and tax heads.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Party(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    pincode: str | None = None
    state: str | None = None
    state_code: str | None = Field(None, description="2-digit GST state code")
    gstin: str | None = None
    pan: str | None = None
    phone: str | None = None
    email: str | None = None


class Supplier(Party):
    cin_llpin: str | None = None
    udyam_number: str | None = Field(None, description="Udyam/MSME registration no. if printed (matters for sec 43B(h))")
    msme_category: Literal["micro", "small", "medium"] | None = None
    bank_name: str | None = None
    bank_account_no: str | None = None
    ifsc: str | None = None


class LineItem(BaseModel):
    sl_no: int | None = None
    description: str
    hsn_sac: str | None = None
    quantity: float | None = None
    uom: str | None = Field(None, description="Unit quantity code, e.g. NOS, KGS, MTR, BOX")
    unit_price: float | None = None
    discount: float | None = None
    taxable_value: float | None = None
    gst_rate: float | None = Field(None, description="Total GST rate %, e.g. 18")
    cgst_amount: float | None = None
    sgst_utgst_amount: float | None = None
    igst_amount: float | None = None
    cess_rate: float | None = None
    cess_amount: float | None = None
    line_total: float | None = None


class Invoice(BaseModel):
    """Every field optional except what's essential; use null when not printed. Never guess numbers."""

    document_type: Literal[
        "tax_invoice", "bill_of_supply", "credit_note", "debit_note", "receipt_voucher", "refund_voucher",
        "payment_voucher", "delivery_challan", "proforma", "import_bill_of_entry", "expense_receipt", "other",
    ] = "tax_invoice"
    invoice_no: str | None = None
    invoice_date: str | None = Field(None, description="ISO date YYYY-MM-DD (Indian invoices are day-first)")
    due_date: str | None = None
    original_invoice_no: str | None = Field(None, description="For credit/debit notes: invoice being adjusted")
    original_invoice_date: str | None = None
    po_number: str | None = None
    po_date: str | None = None
    delivery_note_no: str | None = None
    reverse_charge: bool | None = None
    place_of_supply: str | None = Field(None, description="State name as printed")
    place_of_supply_code: str | None = None
    supply_type: Literal["B2B", "B2C", "SEZWP", "SEZWOP", "EXPWP", "EXPWOP", "DEXP", "IMPORT"] | None = None
    currency: str = "INR"
    # e-invoice / e-way bill
    irn: str | None = Field(None, description="64-char Invoice Reference Number")
    ack_no: str | None = None
    ack_date: str | None = None
    has_signed_qr: bool | None = None
    eway_bill_no: str | None = None
    eway_bill_date: str | None = None
    transporter_name: str | None = None
    transporter_id: str | None = None
    vehicle_no: str | None = None
    lr_no: str | None = None
    transport_mode: str | None = None
    # parties
    supplier: Supplier = Field(default_factory=Supplier)
    buyer: Party = Field(default_factory=Party, description="Bill-to / recipient")
    ship_to: Party | None = None
    # lines & totals
    line_items: list[LineItem] = Field(default_factory=list)
    total_taxable_value: float | None = None
    total_cgst: float | None = None
    total_sgst_utgst: float | None = None
    total_igst: float | None = None
    total_cess: float | None = None
    freight_other_charges: float | None = None
    tcs_amount: float | None = None
    round_off: float | None = None
    grand_total: float | None = None
    amount_in_words: str | None = None
    payment_terms: str | None = None
    notes: str | None = None
    is_signed: bool | None = Field(None, description="Signature / digital signature of supplier present")
    # extraction meta
    page_count: int | None = None
    illegible_fields: list[str] = Field(default_factory=list, description="Fields present but unreadable in the scan")
    extraction_confidence: Literal["high", "medium", "low"] = "medium"


# Flat column order for purchase/sales registers written to Excel.
REGISTER_COLUMNS = [
    "file", "document_type", "invoice_no", "invoice_date", "supplier_name", "supplier_gstin", "supplier_state_code",
    "buyer_name", "buyer_gstin", "place_of_supply_code", "reverse_charge", "hsn_sac", "description", "quantity",
    "uom", "gst_rate", "taxable_value", "igst", "cgst", "sgst", "cess", "invoice_value", "irn", "eway_bill_no",
    "udyam_number", "due_date", "validation_status", "issues",
]


def to_register_rows(inv: Invoice, file: str, status: str, issues: list[str]) -> list[dict]:
    base = {
        "file": file, "document_type": inv.document_type, "invoice_no": inv.invoice_no, "invoice_date": inv.invoice_date,
        "supplier_name": inv.supplier.name, "supplier_gstin": inv.supplier.gstin,
        "supplier_state_code": inv.supplier.state_code, "buyer_name": inv.buyer.name, "buyer_gstin": inv.buyer.gstin,
        "place_of_supply_code": inv.place_of_supply_code, "reverse_charge": "Y" if inv.reverse_charge else "N",
        "irn": inv.irn, "eway_bill_no": inv.eway_bill_no, "udyam_number": inv.supplier.udyam_number,
        "due_date": inv.due_date, "invoice_value": inv.grand_total, "validation_status": status,
        "issues": "; ".join(issues),
    }
    lines = inv.line_items or [LineItem(description="(no line items)", taxable_value=inv.total_taxable_value,
                                        cgst_amount=inv.total_cgst, sgst_utgst_amount=inv.total_sgst_utgst,
                                        igst_amount=inv.total_igst, cess_amount=inv.total_cess)]
    rows = []
    for i, li in enumerate(lines):
        rows.append({**base, "hsn_sac": li.hsn_sac, "description": li.description, "quantity": li.quantity,
                     "uom": li.uom, "gst_rate": li.gst_rate, "taxable_value": li.taxable_value,
                     "igst": li.igst_amount, "cgst": li.cgst_amount, "sgst": li.sgst_utgst_amount,
                     "cess": li.cess_amount, "invoice_value": inv.grand_total if i == 0 else None})
    return rows
