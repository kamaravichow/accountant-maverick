"""Document tools: invoice data entry (50+ fields), inbox classification & filing."""

from __future__ import annotations

import json
import re

from langchain.tools import ToolRuntime, tool

from ... import spreadsheet as xl
from ...extraction.documents import DOC_TYPE_FOLDER, classify_document, extract_invoice, read_document
from ...extraction.schema import REGISTER_COLUMNS, Invoice, to_register_rows
from ...extraction.validate import validate_invoice
from ...recon.normalize import normalize_invoice_no
from ...workspace import INBOX, get_workspace
from ..context import AgentContext, active_fy, company_storage, dump
from ..llm import get_model

Rt = ToolRuntime[AgentContext]
DOC_EXT = (".pdf", ".png", ".jpg", ".jpeg", ".webp")

REGISTERS = {
    "purchase": "02_Purchases/Purchase_Register.xlsx",
    "sales": "01_Sales/Sales_Register.xlsx",
    "expense": "02_Purchases/Expenses_Reimbursements/Expense_Register.xlsx",
}


def _extract_one(ctx: AgentContext, path: str, register: str | None, hint: str | None) -> dict:
    cs = company_storage(ctx)
    ws = get_workspace()
    prof = ws.get_company(ctx.company_id)
    data = cs.read_bytes(path)
    doc = read_document(data, path)
    if doc.kind == "unsupported":
        return {"file": path, "status": "error", "errors": doc.notes}
    inv: Invoice = extract_invoice(doc, get_model(vision=doc.kind in ("scanned_pdf", "image")), hint)
    check = validate_invoice(inv, prof.gstins)
    sidecar = re.sub(r"\.[^.]+$", "", path) + ".extracted.json"
    cs.write_text(sidecar, json.dumps({"invoice": inv.model_dump(), "validation": check}, indent=1, default=str))
    out = {"file": path, "doc_kind": doc.kind, "status": check["status"], "errors": check["errors"],
           "warnings": check["warnings"], "sidecar": sidecar,
           "summary": {"invoice_no": inv.invoice_no, "date": inv.invoice_date, "supplier": inv.supplier.name,
                       "supplier_gstin": inv.supplier.gstin, "buyer_gstin": inv.buyer.gstin,
                       "taxable": inv.total_taxable_value, "igst": inv.total_igst, "cgst": inv.total_cgst,
                       "sgst": inv.total_sgst_utgst, "total": inv.grand_total, "lines": len(inv.line_items),
                       "confidence": inv.extraction_confidence}}
    if register:
        reg_path = f"{active_fy(ctx)}/{REGISTERS[register]}"
        existing = cs.read_bytes(reg_path) if cs.exists(reg_path) else None
        if existing:
            recs = xl.records_from_sheet(existing, "Register")
            dup = [r for r in recs if normalize_invoice_no(r.get("invoice_no")) == normalize_invoice_no(inv.invoice_no)
                   and str(r.get("supplier_gstin") or "").upper() == str(inv.supplier.gstin or "").upper()]
            if dup:
                out["register"] = f"NOT added - duplicate of an entry already in {reg_path} (file {dup[0].get('file')})"
                return out
        rows = to_register_rows(inv, path, check["status"], check["errors"] + check["warnings"])
        cs.write_bytes(reg_path, xl.append_rows(existing, "Register", REGISTER_COLUMNS, rows))
        out["register"] = f"Added {len(rows)} line(s) to {reg_path}"
    return out


@tool
def extract_invoice_data(runtime: Rt, path: str, register_type: str | None = "purchase", hint: str | None = None) -> str:
    """Read an invoice/bill/credit note (digital PDF, scanned PDF or photo) and extract all GST invoice fields
    (supplier/buyer GSTIN, invoice no/date, place of supply, IRN, e-way bill, every line with HSN, qty, rate,
    taxable value, CGST/SGST/IGST/cess, totals, bank details, Udyam no.). Then validates arithmetic, GSTIN
    checksums, HSN vs rate, tax head vs place of supply and Rule 46 fields, saves a .extracted.json next to the file
    and appends the lines to the FY register (skipping duplicates).

    Args:
        path: File path relative to company root.
        register_type: "purchase", "sales", "expense" or null to skip adding to a register.
        hint: Optional context, e.g. "this is a credit note" or "vendor is a GTA under RCM".
    """
    if register_type and register_type not in REGISTERS:
        return f"register_type must be one of {list(REGISTERS)} or null"
    return dump(_extract_one(runtime.context, path, register_type, hint))


@tool
def batch_extract_invoices(runtime: Rt, folder: str, register_type: str | None = "purchase", limit: int = 25,
                           skip_already_extracted: bool = True) -> str:
    """Run extract_invoice_data on every PDF/image in a folder (up to `limit` files per call). Returns a compact
    status table; files with status 'error' or 'review' need your attention. Call again to continue a big folder."""
    cs = company_storage(runtime.context)
    files = [e.path for e in cs.list(folder) if not e.is_dir and e.name.lower().endswith(DOC_EXT)]
    if skip_already_extracted:
        done = {e.path for e in cs.list(folder) if e.name.endswith(".extracted.json")}
        files = [f for f in files if re.sub(r"\.[^.]+$", "", f) + ".extracted.json" not in done]
    results = []
    for f in files[:limit]:
        try:
            r = _extract_one(runtime.context, f, register_type, None)
            results.append({"file": f, "status": r["status"], "invoice_no": r["summary"]["invoice_no"],
                            "total": r["summary"]["total"], "issues": (r["errors"] + r["warnings"])[:3],
                            "register": r.get("register")})
        except Exception as exc:  # keep going on bad files
            results.append({"file": f, "status": "failed", "issues": [str(exc)[:200]]})
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("ok", "review", "error", "failed")}
    return dump({"processed": len(results), "remaining": max(len(files) - limit, 0), "counts": counts, "results": results})


@tool
def classify_inbox(runtime: Rt, apply: bool = False, limit: int = 20) -> str:
    """Classify every unsorted document in _inbox (sales invoice, purchase bill, bank statement, GSTR-2B, 26AS,
    notice, ...) and propose a destination folder + clean file name. With apply=true the files are moved.
    Always run with apply=false first and show the plan unless the user asked you to just file everything."""
    ctx = runtime.context
    cs = company_storage(ctx)
    prof = get_workspace().get_company(ctx.company_id)
    files = [e for e in cs.list(INBOX) if not e.is_dir][:limit]
    plan = []
    for e in files:
        try:
            doc = read_document(cs.read_bytes(e.path), e.name)
            meta = classify_document(doc, get_model(vision=doc.kind in ("scanned_pdf", "image")), prof.name, prof.gstins)
        except Exception as exc:
            plan.append({"file": e.path, "error": str(exc)[:200]})
            continue
        fy = meta.get("financial_year") or active_fy(ctx)
        if fy not in prof.financial_years:
            get_workspace().add_financial_year(ctx.company_id, fy)
            prof = get_workspace().get_company(ctx.company_id)
        folder = DOC_TYPE_FOLDER.get(meta.get("doc_type"), "11_Correspondence")
        folder = folder[1:] if folder.startswith("@") else f"{fy}/{folder}"
        ext = e.name.rsplit(".", 1)[-1].lower() if "." in e.name else "bin"
        name = re.sub(r"[^A-Za-z0-9_.\-]+", "-", str(meta.get("suggested_name") or e.name.rsplit(".", 1)[0]))[:80]
        dest = f"{folder}/{name}.{ext}"
        n = 2
        while cs.exists(dest):
            dest = f"{folder}/{name}_{n}.{ext}"
            n += 1
        item = {"file": e.path, "doc_type": meta.get("doc_type"), "confidence": meta.get("confidence"),
                "party": meta.get("party"), "destination": dest}
        if apply and (meta.get("confidence") or 0) >= 0.6:
            cs.move(e.path, dest)
            item["moved"] = True
        elif apply:
            item["moved"] = False
            item["reason"] = "low confidence - left in inbox for human review"
        plan.append(item)
    return dump({"files": len(plan), "applied": apply, "plan": plan})


DOCUMENT_TOOLS = [extract_invoice_data, batch_extract_invoices, classify_inbox]
