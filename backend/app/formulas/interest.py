"""Interest u/s 234A, 234B, 234C and the advance-tax schedule."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from . import rates as R
from .common import D, Trail, floor100, inr, money, months_or_part, pct


class Interest234AInput(BaseModel):
    tax_on_assessed_income: float = Field(..., description="Tax on total income (after rebate, incl. cess)")
    prepaid_before_due_date: float = Field(..., description="TDS + TCS + advance tax + SA tax paid on or before due date")
    due_date: date
    filing_date: date


def interest_234a(inp: Interest234AInput) -> dict:
    t = Trail()
    base = floor100(D(inp.tax_on_assessed_income) - D(inp.prepaid_before_due_date))
    months = months_or_part(inp.due_date, inp.filing_date) if inp.filing_date > inp.due_date else 0
    interest = base * pct(1) * months
    t(f"Unpaid tax {inr(base)} (rounded down to Rs 100) x 1% x {months} month(s) = {inr(interest)}")
    return {"section": "234A", "amount_basis": money(base), "months": months, "interest": money(interest), "steps": t.steps}


class Interest234BInput(BaseModel):
    fy: str = "2025-26"
    assessed_tax: float = Field(..., description="Tax on total income less TDS/TCS and reliefs")
    advance_tax_paid: float = 0
    payment_date: date = Field(..., description="Date of self-assessment tax payment / determination")
    self_assessment_payments: list[tuple[date, float]] = Field(
        default_factory=list, description="[(date, amount)] payments made after 31 March; interest stops on paid portion"
    )


def interest_234b(inp: Interest234BInput) -> dict:
    t = Trail()
    fy = R.fy_key(inp.fy)
    start = int(fy[:4]) + 1  # AY starts 1 April after FY end
    ay_start_exclusive = date(start, 3, 31)
    assessed = D(inp.assessed_tax)
    if assessed <= 0 or D(inp.advance_tax_paid) >= assessed * D("0.9"):
        t("Advance tax paid >= 90% of assessed tax (or no liability) - no interest u/s 234B")
        return {"section": "234B", "interest": 0.0, "steps": t.steps}
    shortfall = assessed - D(inp.advance_tax_paid)
    interest = Decimal(0)
    balance = shortfall
    period_start = ay_start_exclusive
    # Sec 234B(2): interest runs on the full shortfall up to each self-assessment payment,
    # then on the reduced balance up to the next payment / determination date.
    for pay_date, amt in sorted(inp.self_assessment_payments):
        if balance <= 0:
            break
        m = months_or_part(period_start, pay_date)
        part = floor100(balance) * pct(1) * m
        t(f"{inr(floor100(balance))} x 1% x {m} month(s) to {pay_date} = {inr(part)}")
        interest += part
        balance = max(balance - D(amt), Decimal(0))
        period_start = pay_date
    if balance > 0 and inp.payment_date > period_start:
        m = months_or_part(period_start, inp.payment_date)
        part = floor100(balance) * pct(1) * m
        t(f"{inr(floor100(balance))} x 1% x {m} month(s) to {inp.payment_date} = {inr(part)}")
        interest += part
    return {"section": "234B", "shortfall": money(shortfall), "interest": money(interest), "steps": t.steps}


class Interest234CInput(BaseModel):
    fy: str = "2025-26"
    tax_on_returned_income: float = Field(..., description="Tax on returned income less TDS/TCS")
    paid_by_jun15: float = 0
    paid_by_sep15: float = Field(0, description="Cumulative advance tax paid up to 15 Sep")
    paid_by_dec15: float = Field(0, description="Cumulative up to 15 Dec")
    paid_by_mar15: float = Field(0, description="Cumulative up to 15 Mar")
    presumptive_44ad_44ada: bool = False


def interest_234c(inp: Interest234CInput) -> dict:
    t = Trail()
    T = D(inp.tax_on_returned_income)
    if T < R.ADVANCE_TAX["threshold"]:
        t("Tax liability below Rs 10,000 - advance tax not required (sec 208)")
        return {"section": "234C", "interest": 0.0, "steps": t.steps}
    rows = []
    total = Decimal(0)
    if inp.presumptive_44ad_44ada:
        sched = [("15-Mar", 100, None, inp.paid_by_mar15, 1)]
    else:
        sched = [
            ("15-Jun", 15, 12, inp.paid_by_jun15, 3),
            ("15-Sep", 45, 36, inp.paid_by_sep15, 3),
            ("15-Dec", 75, None, inp.paid_by_dec15, 3),
            ("15-Mar", 100, None, inp.paid_by_mar15, 1),
        ]
    for label, req_pct, safe_pct, paid, months in sched:
        required = T * pct(req_pct)
        paid = D(paid)
        if safe_pct is not None and paid >= T * pct(safe_pct):
            t(f"{label}: paid {inr(paid)} >= {safe_pct}% safe harbour - no interest")
            rows.append({"installment": label, "required": money(required), "paid": money(paid), "interest": 0.0})
            continue
        short = floor100(required - paid)
        i = short * pct(1) * months
        total += i
        t(f"{label}: required {req_pct}% = {inr(required)}, paid {inr(paid)}, shortfall {inr(short)} x 1% x {months} = {inr(i)}")
        rows.append({"installment": label, "required": money(required), "paid": money(paid), "shortfall": money(short), "interest": money(i)})
    return {"section": "234C", "installments": rows, "interest": money(total), "steps": t.steps}


class AdvanceTaxScheduleInput(BaseModel):
    fy: str = "2025-26"
    estimated_tax: float = Field(..., description="Estimated tax for the year less expected TDS/TCS")
    presumptive_44ad_44ada: bool = False
    already_paid: float = 0


def advance_tax_schedule(inp: AdvanceTaxScheduleInput) -> dict:
    fy = R.fy_key(inp.fy)
    y = int(fy[:4])
    T = D(inp.estimated_tax)
    if T < R.ADVANCE_TAX["threshold"]:
        return {"required": False, "note": "Estimated liability below Rs 10,000 - no advance tax (sec 208)."}
    sched = R.ADVANCE_TAX["presumptive_installments" if inp.presumptive_44ad_44ada else "installments"]
    out, cum_prev = [], Decimal(0)
    for md, cum_pct, _safe, in sched:
        mm, dd = map(int, md.split("-"))
        due = date(y + (1 if mm <= 3 else 0), mm, dd)
        cum = T * pct(cum_pct)
        out.append({"due_date": due.isoformat(), "cumulative_pct": cum_pct, "cumulative_amount": money(cum),
                    "installment_amount": money(cum - cum_prev)})
        cum_prev = cum
    return {"required": True, "fy": fy, "schedule": out,
            "balance_after_paid": money(max(T - D(inp.already_paid), Decimal(0)))}

