"""Reconciliation engines.

Every engine takes lists of *canonical* records (see ``normalize.HEADER_SYNONYMS``) and returns a
JSON-able result with a summary block and categorised line items, ready to be written to an
Excel workpaper.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date

from rapidfuzz import fuzz

from ..validators.identifiers import validate_gstin
from .normalize import normalize_invoice_no, parse_amount, parse_date


def _f(x) -> float:
    v = parse_amount(x)
    return float(v) if v is not None else 0.0


def _d(x) -> date | None:
    return parse_date(x)


def _iso(x) -> str | None:
    d = _d(x)
    return d.isoformat() if d else None


def _r(x: float) -> float:
    return round(x + 0.0, 2)


# =========================================================================== GSTR-2B

def parse_gstr2b_json(data: bytes | str | dict) -> list[dict]:
    """Flatten a GSTR-2B JSON (portal download) into canonical invoice-level records."""
    j = json.loads(data) if isinstance(data, (bytes, str)) else data
    doc = (j.get("data") or j).get("docdata") or {}
    out = []

    def add(section: str, sup: dict, doc_: dict, number_key: str, sign: int = 1):
        items = doc_.get("items") or [doc_]
        tot = {k: sum(_f(it.get(k)) for it in items) for k in ("txval", "igst", "cgst", "sgst", "cess")}
        rates = sorted({_f(it.get("rt")) for it in items if it.get("rt") is not None})
        out.append({
            "source_section": section,
            "gstin": (sup.get("ctin") or "").upper(),
            "party": sup.get("trdnm"),
            "invoice_no": doc_.get(number_key),
            "date": _iso(doc_.get("dt")),
            "invoice_value": sign * _f(doc_.get("val")),
            "taxable_value": sign * tot["txval"],
            "igst": sign * tot["igst"],
            "cgst": sign * tot["cgst"],
            "sgst": sign * tot["sgst"],
            "cess": sign * tot["cess"],
            "rates": rates,
            "place_of_supply": doc_.get("pos"),
            "reverse_charge": doc_.get("rev") == "Y",
            "itc_available": doc_.get("itcavl", "Y") != "N",
            "itc_unavailable_reason": doc_.get("rsn") or None,
            "supplier_filing_period": sup.get("supprd"),
            "irn": doc_.get("irn"),
            "note_type": doc_.get("typ") if section.startswith("cdn") else None,
        })

    for section in ("b2b", "b2ba"):
        for sup in doc.get(section, []) or []:
            for inv in sup.get("inv", []) or []:
                add(section, sup, inv, "inum")
    for section in ("cdnr", "cdnra"):
        for sup in doc.get(section, []) or []:
            for nt in sup.get("nt", []) or []:
                add(section, sup, nt, "ntnum", sign=-1 if nt.get("typ", "C") == "C" else 1)
    return out


def _aggregate_invoices(rows: list[dict]) -> list[dict]:
    """Registers usually have one row per item/rate; collapse to one row per (GSTIN, invoice)."""
    groups: dict[tuple, dict] = {}
    for r in rows:
        gstin = str(r.get("gstin") or "").upper().strip()
        inv = str(r.get("invoice_no") or "").strip()
        key = (gstin, normalize_invoice_no(inv) or inv)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {**r, "gstin": gstin, "invoice_no": inv, "taxable_value": 0.0, "igst": 0.0,
                               "cgst": 0.0, "sgst": 0.0, "cess": 0.0, "_lines": 0}
            g["_explicit_value"] = 0.0
        for k in ("taxable_value", "igst", "cgst", "sgst", "cess"):
            g[k] += _f(r.get(k))
        g["_explicit_value"] += _f(r.get("invoice_value"))
        g["_lines"] += 1
    out = []
    for g in groups.values():
        g["total_tax"] = _r(g["igst"] + g["cgst"] + g["sgst"] + g["cess"])
        # invoice_value on item lines is often repeated per line; trust taxable + tax
        g["invoice_value"] = _r(g["taxable_value"] + g["total_tax"]) if g["taxable_value"] else g["_explicit_value"]
        g.pop("_explicit_value", None)
        out.append(g)
    return out


def reconcile_gstr2b(books: list[dict], portal: list[dict], tolerance: float = 1.0, date_window_days: int = 7) -> dict:
    """Purchase register (books) vs GSTR-2B (portal).

    Passes: (1) exact GSTIN + normalised invoice no; (2) same GSTIN + similar invoice no or same tax
    within tolerance and dates close; (3) same PAN, different GSTIN (booked against wrong
    registration/state). Remaining lines are 'only in books' (ITC at risk) or 'only in 2B'
    (bill not recorded / not received - chase client)."""
    B = _aggregate_invoices(books)
    P = _aggregate_invoices(portal)
    for i, b in enumerate(B):
        b["_id"] = i
    for i, p in enumerate(P):
        p["_id"] = i
    used_b, used_p = set(), set()
    pairs: list[tuple[dict, dict, str]] = []

    p_index: dict[tuple, list[dict]] = defaultdict(list)
    for p in P:
        p_index[(p["gstin"], normalize_invoice_no(p["invoice_no"]))].append(p)
    for b in B:
        cands = [p for p in p_index.get((b["gstin"], normalize_invoice_no(b["invoice_no"])), []) if p["_id"] not in used_p]
        if cands:
            p = cands[0]
            pairs.append((b, p, "exact"))
            used_b.add(b["_id"])
            used_p.add(p["_id"])

    by_gstin: dict[str, list[dict]] = defaultdict(list)
    for p in P:
        by_gstin[p["gstin"]].append(p)
    for b in B:
        if b["_id"] in used_b:
            continue
        best, best_score = None, 0.0
        for p in by_gstin.get(b["gstin"], []):
            if p["_id"] in used_p:
                continue
            inv_sim = fuzz.ratio(normalize_invoice_no(b["invoice_no"]), normalize_invoice_no(p["invoice_no"]))
            tax_close = abs(b["total_tax"] - p["total_tax"]) <= tolerance
            bd, pd = _d(b.get("date")), _d(p.get("date"))
            date_close = bool(bd and pd and abs((bd - pd).days) <= date_window_days)
            score = inv_sim + (40 if tax_close else 0) + (20 if date_close else 0)
            if (inv_sim >= 80 or (tax_close and date_close)) and score > best_score:
                best, best_score = p, score
        if best:
            pairs.append((b, best, "fuzzy"))
            used_b.add(b["_id"])
            used_p.add(best["_id"])

    for b in B:
        if b["_id"] in used_b or len(b["gstin"]) != 15:
            continue
        for p in P:
            if p["_id"] in used_p or p["gstin"][2:12] != b["gstin"][2:12]:
                continue
            if normalize_invoice_no(p["invoice_no"]) == normalize_invoice_no(b["invoice_no"]) or \
                    abs(p["total_tax"] - b["total_tax"]) <= tolerance:
                pairs.append((b, p, "same_pan_different_gstin"))
                used_b.add(b["_id"])
                used_p.add(p["_id"])
                break

    matched, mismatched = [], []
    for b, p, how in pairs:
        diffs = {k: _r(b[k] - p[k]) for k in ("taxable_value", "igst", "cgst", "sgst", "cess", "total_tax")}
        issues = [f"{k} differs by {v:+,.2f}" for k, v in diffs.items() if abs(v) > tolerance and k != "total_tax"]
        if how == "same_pan_different_gstin":
            issues.append(f"Booked under GSTIN {b['gstin']} but supplier reported against {p['gstin']} - ITC only "
                          "for the GSTIN on the invoice/2B; correct the books or ask supplier to amend")
        if how == "fuzzy" and normalize_invoice_no(b["invoice_no"]) != normalize_invoice_no(p["invoice_no"]):
            issues.append(f"Invoice no. differs: books '{b['invoice_no']}' vs 2B '{p['invoice_no']}'")
        bd, pd = _d(b.get("date")), _d(p.get("date"))
        if bd and pd and bd != pd:
            issues.append(f"Date differs: books {bd} vs 2B {pd}")
        if (b["igst"] > tolerance) != (p["igst"] > tolerance):
            issues.append("IGST vs CGST+SGST head mismatch (place-of-supply error) - ITC of wrong head not allowed")
        if not p.get("itc_available", True):
            issues.append(f"2B marks ITC unavailable ({p.get('itc_unavailable_reason') or 'reason not given'})")
        if p.get("reverse_charge"):
            issues.append("Reverse charge supply - pay tax in cash under RCM before claiming ITC")
        row = {
            "match_type": how, "gstin": p["gstin"], "party": p.get("party") or b.get("party"),
            "invoice_no_books": b["invoice_no"], "invoice_no_2b": p["invoice_no"],
            "date_books": b.get("date"), "date_2b": p.get("date"),
            "taxable_books": _r(b["taxable_value"]), "taxable_2b": _r(p["taxable_value"]),
            "tax_books": b["total_tax"], "tax_2b": p["total_tax"], "tax_difference": diffs["total_tax"],
            "eligible_itc": _r(min(b["total_tax"], p["total_tax"])) if p.get("itc_available", True) else 0.0,
            "issues": issues,
        }
        (mismatched if issues else matched).append(row)

    only_books = []
    for b in B:
        if b["_id"] in used_b:
            continue
        v = validate_gstin(b["gstin"]) if b["gstin"] else {"valid": False, "errors": ["GSTIN missing"]}
        only_books.append({
            "gstin": b["gstin"], "party": b.get("party"), "invoice_no": b["invoice_no"], "date": b.get("date"),
            "taxable_value": _r(b["taxable_value"]), "total_tax": b["total_tax"],
            "action": "ITC not reflected in 2B - defer claim; ask supplier to file/correct GSTR-1 (sec 16(2)(aa))"
            if v["valid"] else f"Invalid GSTIN in books: {'; '.join(v['errors'])}",
        })
    only_2b = [{
        "gstin": p["gstin"], "party": p.get("party"), "invoice_no": p["invoice_no"], "date": p.get("date"),
        "taxable_value": _r(p["taxable_value"]), "total_tax": p["total_tax"],
        "itc_available": p.get("itc_available", True), "section": p.get("source_section"),
        "action": "Bill not in books - obtain the invoice from client/supplier and book it (or confirm it is not ours)",
    } for p in P if p["_id"] not in used_p]

    tax = lambda rows, k: _r(sum(r[k] for r in rows))  # noqa: E731
    summary = {
        "books_invoices": len(B), "portal_invoices": len(P),
        "matched": len(matched), "matched_with_differences": len(mismatched),
        "only_in_books": len(only_books), "only_in_2b": len(only_2b),
        "itc_as_per_books": _r(sum(b["total_tax"] for b in B)),
        "itc_as_per_2b": _r(sum(p["total_tax"] for p in P if p.get("itc_available", True))),
        "eligible_itc_matched": tax(matched + mismatched, "eligible_itc"),
        "itc_at_risk_only_in_books": tax(only_books, "total_tax"),
        "itc_unclaimed_only_in_2b": tax(only_2b, "total_tax"),
    }
    return {"summary": summary, "matched": matched, "mismatched": mismatched,
            "only_in_books": only_books, "only_in_2b": only_2b}


# =========================================================================== Bank

def _signed_bank_amount(r: dict, perspective: str) -> float:
    """+ = money into the bank account. perspective 'bank' (statement) or 'ledger' (books)."""
    if r.get("debit") is not None or r.get("credit") is not None:
        dr, cr = _f(r.get("debit")), _f(r.get("credit"))
        return _r(cr - dr) if perspective == "bank" else _r(dr - cr)
    return _f(r.get("amount"))


def _refs(text: str) -> set[str]:
    return {t for t in re.findall(r"[A-Z0-9]{6,}", str(text or "").upper()) if re.search(r"\d{4,}", t)}


def reconcile_bank(statement: list[dict], ledger: list[dict], date_before_days: int = 5,
                   date_after_days: int = 20, book_balance: float | None = None,
                   bank_balance: float | None = None) -> dict:
    """Bank statement vs bank ledger in books -> matched items and Bank Reconciliation Statement."""
    S = [{**r, "_amt": _signed_bank_amount(r, "bank"), "_date": _d(r.get("date")), "_id": i} for i, r in enumerate(statement)]
    L = [{**r, "_amt": _signed_bank_amount(r, "ledger"), "_date": _d(r.get("date")), "_id": i} for i, r in enumerate(ledger)]
    by_amt: dict[float, list[dict]] = defaultdict(list)
    for s in S:
        by_amt[s["_amt"]].append(s)
    used_s, matched = set(), []
    for l in sorted(L, key=lambda x: x["_date"] or date.min):
        best, best_score = None, -1.0
        for s in by_amt.get(l["_amt"], []):
            if s["_id"] in used_s or l["_amt"] == 0:
                continue
            if l["_date"] and s["_date"]:
                lag = (s["_date"] - l["_date"]).days
                if lag < -date_before_days or lag > date_after_days:
                    continue
            else:
                lag = 0
            score = 100 - abs(lag) * 2
            if _refs(l.get("narration")) & _refs(str(s.get("narration")) + " " + str(s.get("reference") or "")):
                score += 100
            score += fuzz.token_set_ratio(str(l.get("narration") or ""), str(s.get("narration") or "")) / 5
            if score > best_score:
                best, best_score = s, score
        if best:
            used_s.add(best["_id"])
            l["_matched"] = True
            matched.append({"date_books": l.get("date"), "date_bank": best.get("date"), "amount": l["_amt"],
                            "narration_books": l.get("narration") or l.get("party"), "narration_bank": best.get("narration")})
    books_only = [l for l in L if not l.get("_matched") and l["_amt"] != 0]
    bank_only = [s for s in S if s["_id"] not in used_s and s["_amt"] != 0]

    def pick(rows, sign):
        return [{"date": r.get("date"), "amount": abs(r["_amt"]),
                 "narration": r.get("narration") or r.get("party"), "reference": r.get("reference")}
                for r in rows if (r["_amt"] > 0) == (sign > 0)]

    unpresented = pick(books_only, -1)   # cheques issued / payments in books, not yet debited by bank
    uncleared = pick(books_only, +1)     # deposits in books, not yet credited by bank
    bank_debits = pick(bank_only, -1)    # charges, ECS, TDS, auto-debits not in books
    bank_credits = pick(bank_only, +1)   # interest, direct credits, NEFT receipts not in books

    s_ = lambda rows: _r(sum(r["amount"] for r in rows))  # noqa: E731
    brs = {"unpresented_payments": s_(unpresented), "deposits_not_credited": s_(uncleared),
           "bank_debits_not_in_books": s_(bank_debits), "bank_credits_not_in_books": s_(bank_credits)}
    if book_balance is not None:
        # balance as per books (Dr = money in bank) -> expected balance as per bank
        expected = book_balance + brs["unpresented_payments"] - brs["deposits_not_credited"] \
            - brs["bank_debits_not_in_books"] + brs["bank_credits_not_in_books"]
        brs["balance_as_per_books"] = book_balance
        brs["computed_balance_as_per_bank"] = _r(expected)
        if bank_balance is not None:
            brs["balance_as_per_bank_statement"] = bank_balance
            brs["unexplained_difference"] = _r(bank_balance - expected)
    return {
        "summary": {"statement_lines": len(S), "ledger_lines": len(L), "matched": len(matched),
                    "books_only": len(books_only), "bank_only": len(bank_only)},
        "brs": brs, "matched": matched,
        "unpresented_payments": unpresented, "deposits_not_credited": uncleared,
        "bank_debits_not_in_books": bank_debits, "bank_credits_not_in_books": bank_credits,
        "suggested_entries": [
            {"entry": "Bank charges / interest / auto-debits to be booked", "items": len(bank_debits) + len(bank_credits)},
        ],
    }


# =========================================================================== TDS: 26AS / AIS vs books

def reconcile_26as(books: list[dict], form26as: list[dict], tolerance: float = 1.0) -> dict:
    """Books (TDS receivable by customer/deductor) vs 26AS Part-I / AIS TDS entries, per TAN (or party name)."""
    def key(r):
        tan = str(r.get("tan") or "").upper().strip()
        return tan or re.sub(r"[^a-z]", "", str(r.get("party") or "").lower())[:25]

    def agg(rows):
        g: dict[str, dict] = {}
        for r in rows:
            k = key(r)
            x = g.setdefault(k, {"key": k, "tan": r.get("tan"), "party": r.get("party"), "amount": 0.0, "tds": 0.0})
            x["amount"] += _f(r.get("amount") or r.get("invoice_value") or r.get("taxable_value"))
            x["tds"] += _f(r.get("tds"))
        return g

    gb, ga = agg(books), agg(form26as)
    # fuzzy-link party-name keys that differ in spelling
    for kb in list(gb):
        if kb in ga:
            continue
        cand = max(ga, key=lambda ka: fuzz.token_set_ratio(str(gb[kb]["party"]), str(ga[ka]["party"])), default=None)
        if cand and cand not in gb and fuzz.token_set_ratio(str(gb[kb]["party"]), str(ga[cand]["party"])) >= 88:
            gb[cand] = gb.pop(kb)
    rows = []
    for k in sorted(set(gb) | set(ga)):
        b, a = gb.get(k), ga.get(k)
        tb, ta = _r(b["tds"]) if b else 0.0, _r(a["tds"]) if a else 0.0
        status = "matched" if b and a and abs(tb - ta) <= tolerance else (
            "only_in_books" if not a else "only_in_26as" if not b else "difference")
        action = {
            "matched": "",
            "only_in_books": "Deductor has not filed/quoted PAN correctly - ask customer to file/revise TDS return",
            "only_in_26as": "TDS credit available but income/TDS not booked - verify income is accounted (AIS mismatch risk)",
            "difference": "Amount mismatch - check section, period, or short deduction; request revised return",
        }[status]
        rows.append({"tan": (a or b).get("tan"), "party": (b or a).get("party"), "tds_books": tb, "tds_26as": ta,
                     "difference": _r(tb - ta), "receipts_books": _r(b["amount"]) if b else 0.0,
                     "receipts_26as": _r(a["amount"]) if a else 0.0, "status": status, "action": action})
    summary = {"tds_as_per_books": _r(sum(r["tds_books"] for r in rows)),
               "tds_as_per_26as": _r(sum(r["tds_26as"] for r in rows)),
               "deductors": len(rows), "with_issues": sum(1 for r in rows if r["status"] != "matched")}
    summary["claimable_credit"] = summary["tds_as_per_26as"]
    return {"summary": summary, "rows": rows,
            "note": "Claim TDS only as reflected in 26AS (rule 37BA), in the year the income is offered."}


# =========================================================================== Missing documents

def find_missing_bills(bank_rows: list[dict], purchase_rows: list[dict], min_amount: float = 1000.0,
                       window_days: int = 60, tolerance_pct: float = 1.0) -> dict:
    """Bank payments with no purchase bill of a similar amount near that date -> documents to chase."""
    payments = [r for r in bank_rows if _signed_bank_amount(r, "bank") < -min_amount]
    bills = [{**b, "_amt": _f(b.get("invoice_value")) or (_f(b.get("taxable_value")) + _f(b.get("igst")) +
                                                         _f(b.get("cgst")) + _f(b.get("sgst"))),
              "_date": _d(b.get("date"))} for b in purchase_rows]
    ignore = re.compile(r"\b(salary|sal|gst|tds|tax|challan|emi|loan|transfer to own|self|atm|cash withdrawal|interest|"
                        r"charges|epf|esic|pf|advance tax|refund|sweep|fd)\b", re.I)
    missing, matched = [], 0
    for p in payments:
        amt = abs(_signed_bank_amount(p, "bank"))
        pd = _d(p.get("date"))
        narr = str(p.get("narration") or "")
        if ignore.search(narr):
            continue
        hit = None
        for b in bills:
            if abs(b["_amt"] - amt) <= amt * tolerance_pct / 100 and (
                    not pd or not b["_date"] or -window_days <= (pd - b["_date"]).days <= window_days):
                hit = b
                break
        if hit:
            matched += 1
            continue
        missing.append({"date": p.get("date"), "amount": _r(amt), "narration": narr,
                        "likely_party": _guess_party(narr)})
    return {"summary": {"payments_checked": len(payments), "with_bill": matched, "missing_bills": len(missing),
                        "missing_amount": _r(sum(m["amount"] for m in missing))},
            "missing": missing}


def _guess_party(narration: str) -> str:
    s = re.sub(r"(NEFT|RTGS|IMPS|UPI|ACH|NACH|CHQ|TRF|TO|BY|INB|MB|IB)[/\-: ]*", " ", narration.upper())
    s = re.sub(r"[A-Z]{4}0[A-Z0-9]{6}", " ", s)  # IFSC
    s = re.sub(r"\b[A-Z0-9]*\d{5,}[A-Z0-9]*\b", " ", s)  # refs, account numbers
    s = re.sub(r"[^A-Z &.]", " ", s)
    words = [w for w in s.split() if len(w) > 2]
    return " ".join(words[:4]).title()

