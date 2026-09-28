"""TDS: rate/threshold determination, interest u/s 201(1A), fee u/s 234E, 40(a)(ia)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from . import rates as R
from .common import D, Trail, calendar_months, days_between, inr, money, pct, r0


class TDSInput(BaseModel):
    section: str = Field(..., description="1961-Act section key, e.g. 194C, 194J_professional, 194I_building, 194Q")
    amount: float = Field(..., description="Amount of this payment/credit (excluding GST if shown separately)")
    aggregate_in_fy_before: float = Field(0, description="Payments to the same payee earlier in the FY")
    payee_type: Literal["individual_huf", "company", "firm_llp", "others"] = "company"
    pan_available: bool = True
    months_of_rent: int = Field(1, description="For 194I/194IB: number of months this rent covers")
    payee_category: str = Field("others", description="194A: bank_coop_post_office | bank_senior_citizen | others")
    lower_deduction_cert_rate: float | None = Field(None, description="Rate per sec 197 certificate, if any")


def tds_calc(inp: TDSInput) -> dict:
    t = Trail()
    lookup = {k.upper(): k for k in R.TDS}
    key = lookup.get(inp.section.replace(" ", "").replace("SEC", "").upper())
    if key is None:
        raise ValueError(f"Unknown section {inp.section}. Known: {', '.join(R.TDS)}")
    cfg = R.TDS[key]
    amt = D(inp.amount)
    agg_after = D(inp.aggregate_in_fy_before) + amt
    t(f"Sec {key} ({cfg['nature']}); ITA 2025: sec 393 table entry (392 for salary)")

    if "rate" in cfg:
        rate = D(cfg["rate"])
    else:
        rate = D(cfg["rate_individual_huf"] if inp.payee_type == "individual_huf" else cfg["rate_others"])

    applicable = True
    base = amt
    if "threshold_per_month" in cfg:
        applicable = amt > D(cfg["threshold_per_month"]) * max(inp.months_of_rent, 1)
        t(f"Threshold Rs {cfg['threshold_per_month']:,} per month x {inp.months_of_rent} month(s)")
    elif key == "194C":
        applicable = amt > D(cfg["threshold_single"]) or agg_after > D(cfg["threshold_aggregate"])
        t("Threshold: single payment > Rs 30,000 or aggregate in FY > Rs 1,00,000")
    elif key == "194A":
        limit = D(cfg["threshold_aggregate"].get(inp.payee_category, 10000))
        applicable = agg_after > limit
        t(f"Threshold: aggregate interest in FY > {inr(limit)}")
    elif key == "194Q":
        excess = D(cfg["threshold_excess_over"])
        before = D(inp.aggregate_in_fy_before)
        base = max(agg_after - max(before, excess), Decimal(0)) if agg_after > excess else Decimal(0)
        applicable = base > 0
        t("TDS only on purchase value exceeding Rs 50 lakh in the FY (buyer turnover > Rs 10 cr)")
    elif key == "194IA":
        applicable = amt >= D(cfg["threshold_single"])
    elif "threshold_aggregate" in cfg:
        limit = D(cfg["threshold_aggregate"])
        applicable = agg_after > limit
        if applicable and D(inp.aggregate_in_fy_before) <= limit:
            base = agg_after  # threshold crossed now: deduct on the aggregate (incl. earlier payments)
            t(f"Aggregate {inr(agg_after)} crosses threshold {inr(limit)} - TDS on the full aggregate")

    if not applicable:
        t("Below threshold - no TDS")
        return {"section": key, "tds_applicable": False, "rate_pct": float(rate), "tds": 0.0, "steps": t.steps}

    if inp.lower_deduction_cert_rate is not None:
        rate = D(inp.lower_deduction_cert_rate)
        t(f"Sec 197 lower deduction certificate rate {rate}% applied")
    if not inp.pan_available:
        floor = R.TDS_NO_PAN_RATE_LOW if key in ("194O", "194Q") else R.TDS_NO_PAN_RATE
        rate = max(rate * 2, D(floor), rate)
        t(f"No PAN - sec 206AA higher rate {rate}%")

    tds = r0(base * pct(rate))
    t(f"TDS = {inr(base)} x {rate}% = {inr(tds)} (rounded to rupee, sec 288B)")
    return {"section": key, "tds_applicable": True, "base": money(base), "rate_pct": float(rate),
            "tds": money(tds), "net_payable_to_payee": money(amt - tds), "steps": t.steps}


class TDSInterestInput(BaseModel):
    tds_amount: float
    # Months are counted as calendar months or part thereof, as TRACES computes demands.
    deductible_date: date = Field(..., description="Date on which tax was deductible (credit or payment, earlier)")
    deducted_date: date | None = Field(None, description="Actual deduction date (None if deducted on time)")
    deposit_due_date: date | None = Field(None, description="Defaults to 7th of next month (30 Apr for March)")
    deposited_date: date


def _default_due(d: date) -> date:
    if d.month == 3:
        return date(d.year, 4, 30)
    nm = date(d.year + (d.month == 12), d.month % 12 + 1, 7)
    return nm


def tds_interest_201(inp: TDSInterestInput) -> dict:
    t = Trail()
    amt = D(inp.tds_amount)
    interest = Decimal(0)
    deducted = inp.deducted_date or inp.deductible_date
    if inp.deducted_date and inp.deducted_date > inp.deductible_date:
        m = calendar_months(inp.deductible_date, inp.deducted_date)
        i = amt * pct(1) * m
        interest += i
        t(f"Late deduction: {inr(amt)} x 1% x {m} month(s) ({inp.deductible_date} to {inp.deducted_date}) = {inr(i)}")
    due = inp.deposit_due_date or _default_due(deducted)
    if inp.deposited_date > due:
        m = calendar_months(deducted, inp.deposited_date)
        i = amt * D("1.5") / 100 * m
        interest += i
        t(f"Late deposit: {inr(amt)} x 1.5% x {m} month(s) (from deduction {deducted} to deposit {inp.deposited_date}) = {inr(i)}")
    else:
        t(f"Deposited on/before due date {due} - no 1.5% interest")
    return {"section": "201(1A)", "interest": money(r0(interest)), "deposit_due_date": due.isoformat(), "steps": t.steps}


class LateFee234EInput(BaseModel):
    tds_in_return: float
    due_date: date
    filing_date: date


def late_fee_234e(inp: LateFee234EInput) -> dict:
    days = days_between(inp.due_date, inp.filing_date)
    fee = min(D(days) * D(R.TDS_DUE["late_fee_234E_per_day"]), D(inp.tds_in_return))
    return {"section": "234E", "days_late": days, "fee": money(fee),
            "steps": [f"Rs 200 x {days} day(s), capped at TDS {inr(inp.tds_in_return)} = {inr(fee)}",
                      "Penalty u/s 271H (Rs 10,000-1,00,000) may also apply if filed > 1 year late."]}


class Disallowance40aiaInput(BaseModel):
    expense_amount: float
    tds_deducted_and_paid_by_itr_due_date: bool = False


def disallowance_40a_ia(inp: Disallowance40aiaInput) -> dict:
    if inp.tds_deducted_and_paid_by_itr_due_date:
        return {"disallowance": 0.0, "note": "TDS deducted and paid by the ITR due date u/s 139(1) - no disallowance."}
    d = D(inp.expense_amount) * pct(R.TDS_DUE["disallowance_40a_ia_pct"])
    return {"disallowance": money(d), "note": "30% of expense disallowed (resident payee); allowed in the year TDS is paid."}
