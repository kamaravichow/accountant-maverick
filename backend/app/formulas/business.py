"""Business formulas: sec 43B(h) MSME payments, MSMED interest, presumptive taxation."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from . import rates as R
from .common import D, Trail, inr, money, pct


class MSMEPayable(BaseModel):
    vendor: str
    invoice_date: date
    amount: float
    acceptance_date: date | None = Field(None, description="Date of acceptance/deemed acceptance; defaults to invoice date")
    written_agreement_days: int | None = Field(None, description="Agreed credit period (max 45 counts)")
    payment_date: date | None = None
    enterprise_category: Literal["micro", "small", "medium", "trader"] = "micro"


class MSME43BhInput(BaseModel):
    fy: str = "2025-26"
    payables: list[MSMEPayable]
    bank_rate_pct: float | None = Field(None, description="RBI bank rate for MSMED sec 16 interest (fetch live)")
    as_on: date | None = Field(None, description="Date for interest computation on unpaid dues; default FY end")


def msme_43bh(inp: MSME43BhInput) -> dict:
    fy = R.fy_key(inp.fy)
    fy_end = date(int(fy[:4]) + 1, 3, 31)
    as_on = inp.as_on or fy_end
    rows, total_disallow, total_interest = [], Decimal(0), Decimal(0)
    for p in inp.payables:
        if p.enterprise_category in ("medium", "trader"):
            rows.append({"vendor": p.vendor, "amount": p.amount, "status": "not covered (medium enterprise / trader)"})
            continue
        start = p.acceptance_date or p.invoice_date
        limit_days = min(p.written_agreement_days, 45) if p.written_agreement_days else 15
        due = start + timedelta(days=limit_days)
        paid_in_time = p.payment_date is not None and p.payment_date <= due
        # 43B(h): disallowed in this FY if not paid within the MSMED time limit
        disallow = (not paid_in_time) and (p.payment_date is None or p.payment_date > due) and p.invoice_date <= fy_end
        row = {"vendor": p.vendor, "amount": p.amount, "due_date": due.isoformat(),
               "paid_on": p.payment_date.isoformat() if p.payment_date else None,
               "disallowed_43Bh": bool(disallow)}
        if disallow:
            total_disallow += D(p.amount)
            row["allowed_in"] = "year of actual payment"
        if inp.bank_rate_pct is not None and (p.payment_date is None or p.payment_date > due):
            end = p.payment_date or as_on
            months = max((end - due).days, 0) / Decimal("30.4375")
            monthly = D(inp.bank_rate_pct) * R.MSME["msmed_interest_multiple_of_bank_rate"] / 100 / 12
            interest = D(p.amount) * ((1 + monthly) ** int(months) - 1)
            row["msmed_interest_sec16"] = money(interest)
            row["interest_note"] = "Compound interest at 3x RBI bank rate, monthly rests; NOT deductible (sec 23 MSMED Act)"
            total_interest += interest
        rows.append(row)
    return {"fy": fy, "rows": rows, "total_disallowance_43Bh": money(total_disallow),
            "total_msmed_interest": money(total_interest),
            "notes": ["Applies from AY 2024-25 to buyers (not traders' purchases from traders) for supplies from Udyam-registered "
                      "micro & small enterprises.", "Report in Form 3CD clause 22 and MSME Form-1 (half-yearly) where applicable."]}


class PresumptiveInput(BaseModel):
    section: Literal["44AD", "44ADA"] = "44AD"
    turnover_digital: float = Field(0, description="Receipts via banking channels / digital modes")
    turnover_cash: float = 0
    declared_profit: float | None = None


def presumptive_income(inp: PresumptiveInput) -> dict:
    t = Trail()
    cfg = R.PRESUMPTIVE[inp.section]
    total = D(inp.turnover_digital) + D(inp.turnover_cash)
    cash_share = D(inp.turnover_cash) / total * 100 if total else Decimal(0)
    if inp.section == "44AD":
        limit = D(cfg["turnover_limit_if_cash_le_5pct"] if cash_share <= 5 else cfg["turnover_limit"])
        minimum = D(inp.turnover_digital) * pct(cfg["rate_digital"]) + D(inp.turnover_cash) * pct(cfg["rate_cash"])
        t(f"6% of digital {inr(inp.turnover_digital)} + 8% of cash {inr(inp.turnover_cash)} = {inr(minimum)}")
    else:
        limit = D(cfg["receipts_limit_if_cash_le_5pct"] if cash_share <= 5 else cfg["receipts_limit"])
        minimum = total * pct(cfg["rate"])
        t(f"50% of gross receipts {inr(total)} = {inr(minimum)}")
    eligible = total <= limit
    t(f"Cash receipts {cash_share:.2f}% of total; limit {inr(limit)} -> {'eligible' if eligible else 'NOT eligible'}")
    out = {"section": inp.section, "eligible": eligible, "turnover": money(total), "minimum_presumptive_income": money(minimum),
           "steps": t.steps}
    if inp.declared_profit is not None and D(inp.declared_profit) < minimum:
        out["warning"] = ("Declaring lower profit requires books u/s 44AA and tax audit u/s 44AB(e) if income exceeds the "
                          "basic exemption limit; opting out of 44AD bars it for the next 5 years (sec 44AD(4)).")
    return out
