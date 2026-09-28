"""GST formulas: tax split by place of supply, back-calculation, interest, late fees, ITC timing."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from . import rates as R
from .common import D, Trail, days_between, inr, money, pct, r2


def state_from_gstin(gstin: str | None) -> str | None:
    if gstin and len(gstin) >= 2 and gstin[:2].isdigit():
        return gstin[:2]
    return None


class GSTSplitInput(BaseModel):
    taxable_value: float | None = Field(None, description="Value before GST")
    inclusive_value: float | None = Field(None, description="Value including GST (back-calculated)")
    rate: float = Field(..., description="GST rate %, e.g. 5, 18, 40")
    supplier_state: str = Field(..., description="2-digit state code or supplier GSTIN")
    place_of_supply: str = Field(..., description="2-digit state code or recipient GSTIN")
    cess_rate: float = 0
    sez_or_export: bool = Field(False, description="Supplies to SEZ / exports are inter-state (IGST) always")


def gst_split(inp: GSTSplitInput) -> dict:
    t = Trail()
    sup = state_from_gstin(inp.supplier_state) or inp.supplier_state
    pos = state_from_gstin(inp.place_of_supply) or inp.place_of_supply
    rate = D(inp.rate)
    if inp.taxable_value is not None:
        taxable = D(inp.taxable_value)
    elif inp.inclusive_value is not None:
        taxable = D(inp.inclusive_value) * 100 / (100 + rate + D(inp.cess_rate))
        t(f"Back-calculated taxable value = {inr(inp.inclusive_value)} x 100 / (100 + {rate + D(inp.cess_rate)})")
    else:
        raise ValueError("Provide taxable_value or inclusive_value")
    inter = inp.sez_or_export or sup != pos
    tax = taxable * pct(rate)
    cess = taxable * pct(inp.cess_rate)
    out = {"taxable_value": money(taxable), "rate": float(rate), "supply_type": "inter-state" if inter else "intra-state",
           "supplier_state": R.GST_STATE_CODES.get(sup, sup), "place_of_supply": R.GST_STATE_CODES.get(pos, pos)}
    if inter:
        out.update(igst=money(tax), cgst=0.0, sgst_utgst=0.0)
        t(f"Supplier state {sup} != place of supply {pos} -> IGST {rate}% = {inr(tax)} (sec 7 IGST Act)")
    else:
        half = r2(tax / 2)
        out.update(igst=0.0, cgst=money(half), sgst_utgst=money(r2(tax) - half))
        t(f"Intra-state -> CGST {rate / 2}% + SGST/UTGST {rate / 2}% = {inr(half)} each (sec 8 IGST Act)")
    out["cess"] = money(cess)
    out["total_tax"] = money(tax + cess)
    out["invoice_value"] = money(taxable + tax + cess)
    if rate not in [D(x) for x in R.GST_VALID_RATES_POST_22SEP2025] + [D(x) for x in R.GST_VALID_RATES_PRE_22SEP2025]:
        t(f"WARNING: {rate}% is not a standard GST rate - check HSN/SAC and notification")
    out["steps"] = t.steps
    return out


class GSTInterestInput(BaseModel):
    tax_amount: float = Field(..., description="Net cash liability paid late (sec 50(1) proviso) or ITC wrongly utilised")
    due_date: date
    payment_date: date
    kind: Literal["50(1)", "50(3)"] = "50(1)"


def gst_interest(inp: GSTInterestInput) -> dict:
    rate = D(R.GST_INTEREST[inp.kind])
    days = days_between(inp.due_date, inp.payment_date)
    interest = D(inp.tax_amount) * rate / 100 * days / 365
    return {"section": f"CGST {inp.kind}", "rate_pa": float(rate), "days": days, "interest": money(interest),
            "steps": [f"{inr(inp.tax_amount)} x {rate}% x {days}/365 = {inr(interest)}",
                      "Split interest head-wise (IGST/CGST/SGST) in proportion to the late tax; pay via DRC-03 "
                      "or with the next GSTR-3B."],
            "legal_basis": R.SOURCES["gst_interest"]}


class GSTLateFeeInput(BaseModel):
    return_type: Literal["GSTR-3B", "GSTR-1", "GSTR-9", "GSTR-4"] = "GSTR-3B"
    due_date: date
    filing_date: date
    nil_return: bool = False
    aggregate_turnover_prev_fy: float = Field(0, description="AATO of preceding FY (GSTR-9: turnover in the state)")


def gst_late_fee(inp: GSTLateFeeInput) -> dict:
    cfg = R.GST_LATE_FEE[inp.return_type]
    days = days_between(inp.due_date, inp.filing_date)
    t = Trail()
    turnover = D(inp.aggregate_turnover_prev_fy)
    if inp.return_type == "GSTR-9":
        for bound, per_day, cap_pct in cfg["slabs"]:
            if bound is None or turnover <= D(bound):
                break
        fee = min(D(per_day) * days, turnover * D(cap_pct) / 100) if turnover else D(per_day) * days
        t(f"GSTR-9: Rs {per_day}/day x {days} days, capped at {cap_pct}% of turnover")
    elif inp.return_type == "GSTR-4":
        per_day = cfg["per_day_nil" if inp.nil_return else "per_day"]
        fee = min(D(per_day) * days, D(cfg["cap_nil" if inp.nil_return else "cap"]))
        t(f"GSTR-4: Rs {per_day}/day x {days}")
    else:
        per_day = cfg["per_day_nil" if inp.nil_return else "per_day"]
        cap = None
        for bound, label, amount in cfg["caps"]:
            if inp.nil_return and label == "nil":
                cap = amount
                break
            if label != "nil" and (bound is None or turnover <= D(bound)):
                cap = amount
                break
        fee = min(D(per_day) * days, D(cap))
        t(f"{inp.return_type}: Rs {per_day}/day (CGST+SGST) x {days} days = {inr(D(per_day) * days)}, capped at {inr(cap)}")
    return {"return_type": inp.return_type, "days_late": days, "late_fee_total": money(fee),
            "cgst": money(fee / 2), "sgst": money(fee / 2), "steps": t.steps,
            "legal_basis": R.SOURCES["gst_late_fee"]}


class ITCTimeLimitInput(BaseModel):
    invoice_date: date
    annual_return_filing_date: date | None = None


def itc_time_limit(inp: ITCTimeLimitInput) -> dict:
    """Sec 16(4): ITC must be availed by 30 Nov following the end of the FY, or the date of
    filing the annual return, whichever is earlier."""
    fy_end_year = inp.invoice_date.year + (1 if inp.invoice_date.month >= 4 else 0)
    limit = date(fy_end_year, 11, 30)
    if inp.annual_return_filing_date and inp.annual_return_filing_date < limit:
        limit = inp.annual_return_filing_date
    return {"last_date_to_avail_itc": limit.isoformat(),
            "note": "Sec 16(4) CGST Act. Sec 16(5)/(6) give relief for FY 2017-18 to 2020-21 and revoked registrations."}


class Rule37Input(BaseModel):
    invoice_date: date
    itc_amount: float
    payment_date: date | None = Field(None, description="Date the supplier was paid (value + tax)")
    as_on: date = Field(default_factory=date.today)


def rule37_reversal(inp: Rule37Input) -> dict:
    deadline = inp.invoice_date + timedelta(days=R.GST_THRESHOLDS["itc_rule37_days"])
    paid_ok = inp.payment_date is not None and inp.payment_date <= deadline
    must_reverse = not paid_ok and inp.as_on > deadline
    out = {"payment_deadline": deadline.isoformat(), "must_reverse": must_reverse}
    if must_reverse:
        out["reverse_in_return_for_period"] = f"{deadline:%B %Y} (GSTR-3B Table 4(B)(2))"
        out["itc_to_reverse"] = money(inp.itc_amount)
        out["note"] = ("Reverse ITC with interest u/s 50; ITC can be re-availed once payment is made. "
                       "Does not apply to RCM supplies or deemed supplies without consideration.")
    return out


class HSNDigitsInput(BaseModel):
    aato: float = Field(..., description="Aggregate annual turnover of preceding FY")


def hsn_digits_required(inp: HSNDigitsInput) -> dict:
    for bound, digits in R.GST_THRESHOLDS["hsn_digits"]:
        if bound is None or D(inp.aato) <= D(bound):
            return {"min_hsn_digits": digits,
                    "e_invoice_mandatory": D(inp.aato) > D(R.GST_THRESHOLDS["e_invoice_aato"]),
                    "e_invoice_30_day_limit": D(inp.aato) >= D(R.GST_THRESHOLDS["e_invoice_30_day_reporting_aato"]),
                    "note": "Notification 78/2020-CT; B2C supplies by AATO <= 5 cr may use 4 digits."}
    return {}


def reverse_calculate(inclusive_value: float, rate: float) -> Decimal:
    return D(inclusive_value) * 100 / (100 + D(rate))
