"""Validators for Indian tax identifiers: GSTIN (with checksum), PAN, TAN, IFSC, Udyam."""

from __future__ import annotations

import re

from ..formulas.rates import GST_STATE_CODES

_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

PAN_ENTITY = {
    "P": "Individual", "C": "Company", "H": "HUF", "F": "Firm / LLP", "A": "Association of Persons",
    "T": "Trust", "B": "Body of Individuals", "L": "Local Authority", "J": "Artificial Juridical Person",
    "G": "Government",
}

PAN_RE = re.compile(r"^[A-Z]{3}[PCHFATBLJG][A-Z][0-9]{4}[A-Z]$")
TAN_RE = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z0-9]{10}[0-9A-Z]Z[0-9A-Z]$")
GSTIN_FIND_RE = re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
UDYAM_RE = re.compile(r"^UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}$")


def gstin_checksum(first14: str) -> str:
    """Mod-36 checksum used by GSTN (Luhn-style, alternating factors 1 and 2)."""
    total = 0
    for i, ch in enumerate(first14):
        code = _CHARSET.index(ch)
        prod = code * (2 if i % 2 else 1)
        total += prod // 36 + prod % 36
    return _CHARSET[(36 - total % 36) % 36]


def validate_gstin(gstin: str) -> dict:
    g = (gstin or "").strip().upper().replace(" ", "")
    errors = []
    if len(g) != 15:
        errors.append(f"GSTIN must be 15 characters (got {len(g)})")
    elif not GSTIN_RE.match(g):
        errors.append("Format should be 2-digit state + 10-char PAN + entity no. + 'Z' + checksum")
    state = g[:2]
    if len(g) >= 2 and state not in GST_STATE_CODES:
        errors.append(f"Unknown state code {state}")
    pan = g[2:12] if len(g) >= 12 else ""
    warnings = []
    if len(pan) == 10 and not PAN_RE.match(pan):
        # TDS/TCS deductor, NRTP, OIDAR and UN-body registrations embed a TAN/other id instead of a PAN
        warnings.append(f"Embedded id {pan} is not a PAN - verify it is a TDS/TCS/NRTP/UN registration")
    if len(g) == 15 and all(c in _CHARSET for c in g):
        expected = gstin_checksum(g[:14])
        if g[14] != expected:
            errors.append(f"Checksum mismatch: last character should be {expected} (typo or fake GSTIN)")
    return {
        "gstin": g,
        "valid": not errors,
        "state_code": state,
        "state": GST_STATE_CODES.get(state),
        "pan": pan or None,
        "entity_type": PAN_ENTITY.get(pan[3]) if len(pan) == 10 else None,
        "errors": errors,
        "warnings": warnings,
        "note": "Format/checksum only. Confirm active status & filing history on the GST portal "
        "(Search Taxpayer) - cancelled suppliers' invoices don't qualify for ITC.",
    }


def validate_pan(pan: str) -> dict:
    p = (pan or "").strip().upper()
    ok = bool(PAN_RE.match(p))
    return {
        "pan": p,
        "valid": ok,
        "holder_type": PAN_ENTITY.get(p[3]) if ok else None,
        "errors": [] if ok else ["PAN must be 5 letters + 4 digits + 1 letter, 4th letter = holder type"],
        "note": "Check PAN-Aadhaar linkage for individuals: inoperative PAN attracts higher TDS/TCS (sec 206AA/206CC).",
    }


def validate_tan(tan: str) -> dict:
    t = (tan or "").strip().upper()
    return {"tan": t, "valid": bool(TAN_RE.match(t))}


def validate_ifsc(ifsc: str) -> dict:
    i = (ifsc or "").strip().upper()
    return {"ifsc": i, "valid": bool(IFSC_RE.match(i)), "bank_code": i[:4] if len(i) >= 4 else None}


def find_gstins(text: str) -> list[str]:
    return sorted(set(GSTIN_FIND_RE.findall((text or "").upper())))


def validate_identifier(value: str) -> dict:
    """Auto-detect and validate a GSTIN / PAN / TAN / IFSC / Udyam number."""
    v = (value or "").strip().upper()
    if len(v) == 15:
        return {"type": "GSTIN", **validate_gstin(v)}
    if len(v) == 10 and PAN_RE.match(v):
        return {"type": "PAN", **validate_pan(v)}
    if len(v) == 10 and TAN_RE.match(v):
        return {"type": "TAN", **validate_tan(v)}
    if len(v) == 11:
        return {"type": "IFSC", **validate_ifsc(v)}
    if v.startswith("UDYAM"):
        return {"type": "UDYAM", "value": v, "valid": bool(UDYAM_RE.match(v))}
    return {"type": "unknown", "value": v, "valid": False}
