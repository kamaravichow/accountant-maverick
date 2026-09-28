"""Calculation, validation, data-cleaning and reconciliation tools."""

from __future__ import annotations

import json
from datetime import date

from langchain.tools import ToolRuntime, tool
from pydantic import ValidationError

from ... import spreadsheet as xl
from ...formulas import FORMULAS, catalog, run_formula
from ...recon import engines
from ...recon.normalize import load_records
from ...storage import ScopedStorage
from ...validators.hsn import audit_register, validate_hsn
from ...validators.identifiers import validate_identifier
from ...workspace import get_workspace
from ..context import AgentContext, active_fy, company_storage, dump

Rt = ToolRuntime[AgentContext]


# ------------------------------------------------------------------ calculations

@tool
def list_formulas(category: str | None = None, name: str | None = None) -> str:
    """List the preset, audited tax formulas (income tax, TDS, GST, interest, capital gains, depreciation, payroll,
    compliance calendar). Pass `name` to get that formula's full input JSON schema before calling `calculate`."""
    if name:
        if name not in FORMULAS:
            return f"Unknown formula. Available: {', '.join(FORMULAS)}"
        f = FORMULAS[name]
        return dump({"name": name, "description": f.description, "input_schema": f.schema()})
    items = [c for c in catalog() if not category or c["category"].lower() == category.lower()]
    return dump(items)


@tool
def calculate(formula: str, inputs: dict) -> str:
    """Run a preset formula - ALWAYS use this for tax, interest, fee, TDS, GST, depreciation, payroll or
    capital-gain arithmetic instead of computing mentally. Returns the result with a step-by-step working
    ('steps') and legal basis that you should show the user.

    Args:
        formula: Formula name from list_formulas, e.g. "income_tax_individual", "gst_interest", "tds_calc".
        inputs: Input object matching the formula's schema (see list_formulas(name=...)).
    """
    try:
        return dump(run_formula(formula, inputs))
    except KeyError as exc:
        return str(exc)
    except ValidationError as exc:
        schema = FORMULAS[formula].schema() if formula in FORMULAS else {}
        return dump({"error": "Invalid arguments", "details": json.loads(exc.json()), "expected_schema": schema})
    except ValueError as exc:
        return f"Error: {exc}"


# ------------------------------------------------------------------ validation

@tool
def validate_ids(values: list[str]) -> str:
    """Validate GSTINs (incl. checksum), PANs, TANs, IFSCs or Udyam numbers. Auto-detects the type."""
    return dump([validate_identifier(v) for v in values])


@tool
def check_hsn(code: str, description: str | None = None, rate: float | None = None,
              invoice_date: str | None = None, aato: float | None = None, is_service: bool | None = None) -> str:
    """Validate one HSN/SAC: format, digits required for AATO, goods-vs-service, and whether the GST rate charged
    matches the reference rate (handles the 22-Sep-2025 GST 2.0 rate changes). Suggests codes from the description.
    Reference table is a starter set - for codes it doesn't know, confirm the rate with web_search on cbic-gst.gov.in."""
    return dump(validate_hsn(code, description, rate, invoice_date, aato, is_service))


def _load(cs: ScopedStorage, path: str, sheet: str | None = None) -> list[dict]:
    data = cs.read_bytes(path)
    if path.lower().endswith(".json"):
        j = json.loads(data)
        if isinstance(j, dict) and ("data" in j or "docdata" in j):
            return engines.parse_gstr2b_json(j)
        if isinstance(j, list):
            return j
        raise ValueError("Unrecognised JSON structure (expected GSTR-2B JSON or a list of records)")
    if path.lower().endswith((".xlsx", ".xlsm")) and sheet is None:
        wb = xl.load(data)
        # GSTR-2B Excel has a 'B2B' sheet; prefer it when present
        for name in wb.sheetnames:
            if name.strip().upper() in ("B2B", "REGISTER"):
                sheet = name
                break
    recs, _stats = load_records(data, path, sheet)
    return recs


@tool
def audit_hsn_register(runtime: Rt, path: str, sheet: str | None = None) -> str:
    """Audit a sales/purchase register (xlsx/csv) for HSN problems: invalid codes, wrong rates for the HSN,
    too few digits for AATO, same item under different HSNs, same HSN at different rates. Needs columns like
    HSN, Description, Rate (and ideally Invoice Date)."""
    cs = company_storage(runtime.context)
    rows = _load(cs, path, sheet)
    prof = get_workspace().get_company(runtime.context.company_id)
    aato = None
    if prof.turnover_band:
        try:
            aato = float(prof.turnover_band)
        except ValueError:
            pass
    res = audit_register([{"hsn": r.get("hsn"), "description": r.get("description") or r.get("narration"),
                           "rate": r.get("rate"), "invoice_date": r.get("date"), "invoice_no": r.get("invoice_no")}
                          for r in rows], aato)
    return dump(res)


# ------------------------------------------------------------------ data cleaning

@tool
def clean_table(runtime: Rt, path: str, output_path: str | None = None, sheet: str | None = None) -> str:
    """Clean a messy export (Tally/Busy/Zoho ledger, bank statement PDF/Excel/CSV, client spreadsheet): finds
    the real header row below logos/addresses, maps column names to standard ones, parses Indian amounts
    (1,23,456.00 Dr, brackets), day-first dates and Excel serials, merges wrapped narration lines, drops
    totals/opening balance lines and duplicates. Saves a clean .xlsx (default: same folder, suffix _clean)."""
    cs = company_storage(runtime.context)
    data = cs.read_bytes(path)
    recs, stats = load_records(data, path, sheet)
    if not recs:
        return dump({"error": "No table found", "stats": stats})
    headers = list(dict.fromkeys(k for r in recs for k in r))
    out = output_path or path.rsplit(".", 1)[0] + "_clean.xlsx"
    money_cols = [h for h in headers if h in ("debit", "credit", "amount", "taxable_value", "igst", "cgst", "sgst",
                                               "cess", "invoice_value", "tds")]
    cs.write_bytes(out, xl.write_table(None, "Clean", headers, [[r.get(h) for h in headers] for r in recs],
                                       totals=money_cols))
    return dump({"saved": out, "stats": stats, "columns": headers, "sample": recs[:5]})


# ------------------------------------------------------------------ reconciliations

def _workpaper(cs: ScopedStorage, path: str, title: str, summary: dict, sections: dict[str, list[dict]]) -> str:
    data = xl.write_table(None, "Summary", ["Particulars", "Value"],
                          [[k.replace("_", " ").title(), v] for k, v in summary.items()], title=title)
    for name, rows in sections.items():
        if not rows:
            continue
        headers = list(dict.fromkeys(k for r in rows for k in r if not k.startswith("_")))
        body = [[("; ".join(v) if isinstance(v, list) else v) for v in (r.get(h) for h in headers)] for r in rows]
        num = [h for h in headers if any(isinstance(r.get(h), (int, float)) and not isinstance(r.get(h), bool) for r in rows)]
        data = xl.write_table(data, name[:31], headers, body, totals=num)
    cs.write_bytes(path, data)
    return path


def _default_out(ctx: AgentContext, name: str) -> str:
    return f"{active_fy(ctx)}/12_Workpapers/{name}_{date.today():%Y%m%d}.xlsx"


@tool
def reconcile_gstr2b(runtime: Rt, books_path: str, gstr2b_path: str, output_path: str | None = None,
                     tolerance: float = 1.0, books_sheet: str | None = None) -> str:
    """Reconcile the purchase register (books) with GSTR-2B (portal JSON or Excel). Matches on GSTIN + normalised
    invoice number, then fuzzy (typo'd invoice numbers, same tax & close dates), then same-PAN-different-GSTIN.
    Reports matched, mismatched (value/head/date differences, ITC unavailable, RCM), only-in-books (ITC at risk)
    and only-in-2B (bills missing from books - chase the client). Writes an Excel workpaper."""
    ctx = runtime.context
    cs = company_storage(ctx)
    books = _load(cs, books_path, books_sheet)
    books = [{**r, "gstin": r.get("gstin") or r.get("supplier_gstin"), "party": r.get("party") or r.get("supplier_name"),
              "date": r.get("date") or r.get("invoice_date")} for r in books]
    portal = _load(cs, gstr2b_path)
    res = engines.reconcile_gstr2b(books, portal, tolerance=tolerance)
    out = _workpaper(cs, output_path or _default_out(ctx, "GSTR2B_Reconciliation"), "GSTR-2B vs Books", res["summary"],
                     {"Mismatched": res["mismatched"], "Only in Books": res["only_in_books"],
                      "Only in 2B": res["only_in_2b"], "Matched": res["matched"]})
    return dump({"workpaper": out, "summary": res["summary"], "mismatched_top": res["mismatched"][:15],
                 "only_in_books_top": res["only_in_books"][:15], "only_in_2b_top": res["only_in_2b"][:15]})


@tool
def reconcile_bank(runtime: Rt, statement_path: str, ledger_path: str, book_balance: float | None = None,
                   bank_balance: float | None = None, output_path: str | None = None) -> str:
    """Bank reconciliation: bank statement (PDF/Excel/CSV) vs bank ledger exported from books. Matches by amount,
    date window, cheque/UTR references and narration; produces the BRS (unpresented cheques, deposits not credited,
    bank charges/interest/auto-debits not booked). Pass closing balances to get the unexplained difference."""
    ctx = runtime.context
    cs = company_storage(ctx)
    res = engines.reconcile_bank(_load(cs, statement_path), _load(cs, ledger_path), book_balance=book_balance,
                                 bank_balance=bank_balance)
    out = _workpaper(cs, output_path or _default_out(ctx, "Bank_Reconciliation"), "Bank Reconciliation Statement",
                     {**res["summary"], **res["brs"]},
                     {"Unpresented": res["unpresented_payments"], "Not Credited": res["deposits_not_credited"],
                      "Bank Dr not in books": res["bank_debits_not_in_books"],
                      "Bank Cr not in books": res["bank_credits_not_in_books"], "Matched": res["matched"]})
    return dump({"workpaper": out, "summary": res["summary"], "brs": res["brs"],
                 "bank_debits_not_in_books": res["bank_debits_not_in_books"][:20],
                 "bank_credits_not_in_books": res["bank_credits_not_in_books"][:20]})


@tool
def reconcile_tds_26as(runtime: Rt, books_path: str, form26as_path: str, output_path: str | None = None) -> str:
    """Reconcile TDS receivable in books (by customer/deductor) with Form 26AS / AIS TDS entries (by TAN).
    Flags deductors whose TDS is missing/short in 26AS (ask them to revise returns) and 26AS credits whose income
    isn't booked (AIS mismatch risk)."""
    ctx = runtime.context
    cs = company_storage(ctx)
    res = engines.reconcile_26as(_load(cs, books_path), _load(cs, form26as_path))
    out = _workpaper(cs, output_path or _default_out(ctx, "TDS_26AS_Reconciliation"), "TDS: Books vs 26AS",
                     res["summary"], {"Deductor-wise": res["rows"]})
    return dump({"workpaper": out, **res, "rows": res["rows"][:40]})


@tool
def find_missing_bills(runtime: Rt, bank_statement_path: str, purchase_register_path: str,
                       min_amount: float = 1000) -> str:
    """Find bank payments that have no matching purchase bill (similar amount within +/-60 days) - the list of
    bills to chase from the client. Ignores salary, taxes, EMI, own transfers, charges."""
    cs = company_storage(runtime.context)
    purchases = _load(cs, purchase_register_path)
    purchases = [{**r, "date": r.get("date") or r.get("invoice_date")} for r in purchases]
    res = engines.find_missing_bills(_load(cs, bank_statement_path), purchases, min_amount=min_amount)
    return dump(res)


COMPLIANCE_TOOLS = [list_formulas, calculate, validate_ids, check_hsn, audit_hsn_register, clean_table,
                    reconcile_gstr2b, reconcile_bank, reconcile_tds_26as, find_missing_bills]
