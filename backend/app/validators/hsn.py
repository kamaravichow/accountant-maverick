"""HSN/SAC validation and mismatch detection.

Common real-world problems this catches:
  * malformed codes (wrong length, invalid chapter, 'NA', decimals from Excel like 8471.0)
  * too few digits for the company's AATO (4 digits up to Rs 5 cr, 6 digits above)
  * rate charged on the invoice != rate expected for that HSN (incl. GST 2.0 changes on 22-Sep-2025)
  * goods HSN used for a service or SAC used for goods
  * the same item description booked under different HSNs / rates across a register
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from ..formulas.rates import GST_RATE_CHANGE_DATE

DATA = Path(__file__).parent / "data" / "hsn_rates.json"


@lru_cache
def _table() -> list[dict]:
    return json.loads(DATA.read_text())["codes"]


def normalize_hsn(code) -> str:
    s = str(code or "").strip().upper()
    if re.fullmatch(r"\d+\.0+", s):  # Excel float artefact: 8471.0
        s = s.split(".")[0]
    s = re.sub(r"[\s.\-]", "", s)
    if s.startswith("SAC"):
        s = s[3:]
    if s.startswith("HSN"):
        s = s[3:]
    # Excel strips leading zeros from chapters 01-09 (e.g. 401 -> 0401)
    if s.isdigit() and len(s) in (3, 5, 7):
        s = "0" + s
    return s


def lookup(code: str, extra: list[dict] | None = None) -> dict | None:
    code = normalize_hsn(code)
    rows = (extra or []) + _table()
    best = None
    for row in rows:
        c = row["code"]
        if code.startswith(c) or c.startswith(code):
            if best is None or len(c) > len(best["code"]):
                best = row
    return best


def _match_score(description: str, row: dict) -> float:
    text = description.lower()
    best = fuzz.token_set_ratio(text, row["desc"].lower())
    for kw in row.get("kw", []):
        if re.search(rf"\b{re.escape(kw.lower())}\b", text):
            best = max(best, 90 + min(len(kw), 10))  # whole-word keyword hit; longer keywords win ties
        elif len(kw) >= 4:
            best = max(best, fuzz.partial_ratio(kw.lower(), text) * 0.85)
    return best


def suggest(description: str, limit: int = 3, extra: list[dict] | None = None) -> list[dict]:
    rows = (extra or []) + _table()
    scored = sorted(((_match_score(description, r), r) for r in rows), key=lambda x: -x[0])[:limit]
    return [{"code": r["code"], "desc": r["desc"], "rate_post_22sep2025": r["post"], "score": round(min(sc, 100))}
            for sc, r in scored]


def expected_rate(row: dict, invoice_date: date | None) -> float:
    if invoice_date and invoice_date.isoformat() < GST_RATE_CHANGE_DATE:
        return float(row["pre"])
    return float(row["post"])


def validate_hsn(
    code,
    description: str | None = None,
    rate: float | None = None,
    invoice_date: date | str | None = None,
    aato: float | None = None,
    is_service: bool | None = None,
    extra: list[dict] | None = None,
) -> dict:
    raw = code
    code = normalize_hsn(code)
    if isinstance(invoice_date, str) and invoice_date:
        invoice_date = date.fromisoformat(invoice_date[:10])
    issues: list[str] = []
    info: list[str] = []
    if str(raw) != code and code:
        info.append(f"Normalised '{raw}' -> '{code}'")
    if not code or not code.isdigit():
        issues.append("HSN/SAC missing or non-numeric")
        return {"code": code, "valid": False, "issues": issues, "suggestions": suggest(description) if description else []}

    sac = code.startswith("99")
    if sac:
        if len(code) not in (4, 6):
            issues.append("SAC should be 4 or 6 digits (starts with 99)")
    else:
        if len(code) not in (2, 4, 6, 8):
            issues.append("HSN should be 4, 6 or 8 digits")
        chapter = int(code[:2])
        if chapter < 1 or chapter > 98 or chapter == 77:
            issues.append(f"Invalid HSN chapter {code[:2]}")
    if is_service is True and not sac:
        issues.append("Service line uses a goods HSN - services need a SAC (99xxxx)")
    if is_service is False and sac:
        issues.append("Goods line uses a SAC code - goods need an HSN")
    if aato is not None:
        need = 6 if aato > 50_000_000 else 4
        if len(code) < need:
            issues.append(f"AATO {'>' if need == 6 else '<='} Rs 5 cr requires at least {need}-digit HSN in GSTR-1 / e-invoice")

    row = lookup(code, extra)
    out = {"code": code, "type": "SAC" if sac else "HSN"}
    if row:
        exp = expected_rate(row, invoice_date)
        out.update(matched=row["code"], matched_desc=row["desc"], expected_rate=exp)
        if row.get("note"):
            info.append(row["note"])
        if rate is not None and float(rate) != exp:
            changed = row["pre"] != row["post"]
            msg = f"Rate charged {rate}% but reference rate for {row['code']} is {exp}%"
            if changed:
                msg += (f" (changed from {row['pre']}% to {row['post']}% on {GST_RATE_CHANGE_DATE}; check invoice/supply date "
                        "and time-of-supply rules u/s 14)")
            if row.get("note"):
                msg += " - rate may depend on value/specification, see note"
            issues.append(msg)
        if description:
            score = min(_match_score(description, row), 100)
            out["description_match_score"] = round(score)
            if score < 45:
                issues.append(f"Description '{description}' looks unrelated to {row['code']} ({row['desc']})")
    else:
        info.append("Code not in local reference table - verify rate via live search (CBIC rate notifications)")
    if description and (issues or not row):
        out["suggestions"] = suggest(description, extra=extra)
    out.update(valid=not issues, issues=issues, info=info)
    return out


def audit_register(rows: list[dict], aato: float | None = None) -> dict:
    """Audit a sales/purchase register. Each row: {hsn, description, rate, invoice_date?, invoice_no?, taxable_value?}.
    Flags per-line issues plus cross-line inconsistencies."""
    line_issues = []
    by_desc: dict[str, set] = defaultdict(set)
    by_hsn_rate: dict[str, set] = defaultdict(set)
    for i, r in enumerate(rows):
        res = validate_hsn(r.get("hsn"), r.get("description"), r.get("rate"), r.get("invoice_date"), aato)
        if res["issues"]:
            line_issues.append({"row": i + 1, "invoice_no": r.get("invoice_no"), "hsn": r.get("hsn"),
                                "description": r.get("description"), "issues": res["issues"],
                                "suggestions": res.get("suggestions", [])})
        desc_key = re.sub(r"[^a-z0-9 ]", "", str(r.get("description", "")).lower()).strip()
        if desc_key:
            by_desc[desc_key].add(normalize_hsn(r.get("hsn")))
        if r.get("rate") is not None:
            period = "pre" if str(r.get("invoice_date", "9999"))[:10] < GST_RATE_CHANGE_DATE else "post"
            by_hsn_rate[f"{normalize_hsn(r.get('hsn'))}|{period}"].add(float(r["rate"]))
    inconsistent_hsn = [{"description": d, "hsn_codes": sorted(c)} for d, c in by_desc.items() if len(c) > 1]
    inconsistent_rate = [{"hsn": k.split("|")[0], "period": k.split("|")[1], "rates": sorted(v)}
                         for k, v in by_hsn_rate.items() if len(v) > 1]
    return {"rows_checked": len(rows), "rows_with_issues": len(line_issues), "line_issues": line_issues,
            "same_description_different_hsn": inconsistent_hsn, "same_hsn_different_rates": inconsistent_rate}
