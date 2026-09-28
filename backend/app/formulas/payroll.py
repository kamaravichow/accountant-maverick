"""Payroll statutory formulas: EPF/EPS/EDLI, ESI, gratuity, HRA exemption, labour-code wages."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from . import rates as R
from .common import D, Trail, inr, money, pct, r0

P = R.PAYROLL


class EPFInput(BaseModel):
    basic_plus_da: float = Field(..., description="Monthly PF wages (basic + DA [+ retaining allowance])")
    restrict_to_ceiling: bool = Field(True, description="Compute contributions on Rs 15,000 ceiling if wages exceed it")
    eps_member: bool = Field(True, description="False for members joining after Sep-2014 with wages > Rs 15,000")


def epf_contributions(inp: EPFInput) -> dict:
    wages = D(inp.basic_plus_da)
    pf_wages = min(wages, D(P["eps_wage_ceiling"])) if inp.restrict_to_ceiling else wages
    ee = r0(pf_wages * pct(P["epf_employee_pct"]))
    eps_wages = min(wages, D(P["eps_wage_ceiling"]))
    eps = r0(eps_wages * pct(P["eps_pct"])) if inp.eps_member else Decimal(0)
    er_total = r0(pf_wages * pct(P["epf_employer_pct"]))
    er_epf = er_total - eps
    edli = r0(min(wages, D(P["edli_wage_ceiling"])) * pct(P["edli_pct"]))
    admin = r0(pf_wages * pct(P["epf_admin_pct"]))
    return {"pf_wages": money(pf_wages), "employee_epf_12pct": money(ee), "employer_eps_8_33pct": money(eps),
            "employer_epf_3_67pct": money(er_epf), "edli_0_5pct": money(edli), "admin_charges_0_5pct": money(admin),
            "total_employer_cost": money(er_total + edli + admin),
            "steps": [f"EPS capped at 8.33% of Rs {P['eps_wage_ceiling']:,} = max Rs 1,250; "
                      "balance of employer 12% goes to EPF. Deposit by 15th of next month (ECR)."]}


class ESIInput(BaseModel):
    gross_monthly_wages: float


def esi_contributions(inp: ESIInput) -> dict:
    w = D(inp.gross_monthly_wages)
    if w > D(P["esi_wage_ceiling"]):
        return {"applicable": False, "note": "Wages above Rs 21,000 (Rs 25,000 for disabled) - ESI not applicable "
                "(continues till end of the contribution period if crossed mid-period)."}
    ee = (w * pct(P["esi_employee_pct"])).quantize(Decimal("1"), rounding="ROUND_CEILING")
    er = (w * pct(P["esi_employer_pct"])).quantize(Decimal("1"), rounding="ROUND_CEILING")
    return {"applicable": True, "employee_0_75pct": money(ee), "employer_3_25pct": money(er),
            "note": "Rounded up to next rupee; employees earning up to Rs 176/day are exempt from employee share."}


class GratuityInput(BaseModel):
    last_drawn_basic_da_monthly: float
    years_of_service: int
    extra_months: int = Field(0, description="Months beyond completed years; > 6 months rounds up")
    covered_by_gratuity_act: bool = True
    gratuity_received: float | None = None
    govt_employee: bool = False


def gratuity(inp: GratuityInput) -> dict:
    t = Trail()
    years = inp.years_of_service + (1 if inp.covered_by_gratuity_act and inp.extra_months > 6 else 0)
    salary = D(inp.last_drawn_basic_da_monthly)
    if inp.covered_by_gratuity_act:
        amount = salary * 15 / 26 * years
        t(f"15/26 x {inr(salary)} x {years} years = {inr(amount)} (Payment of Gratuity Act / Code on Social Security)")
    else:
        amount = salary * D("0.5") * inp.years_of_service
        t(f"Not covered: 1/2 x average salary x {inp.years_of_service} completed years = {inr(amount)}")
    out = {"formula_gratuity": money(amount)}
    if inp.gratuity_received is not None:
        if inp.govt_employee:
            exempt = D(inp.gratuity_received)
        else:
            exempt = min(D(inp.gratuity_received), amount, D(P["gratuity_exempt_limit"]))
        out.update(exempt_10_10=money(exempt), taxable=money(D(inp.gratuity_received) - exempt))
        t(f"Exempt u/s 10(10) = least of received, formula amount, Rs 20 lakh = {inr(exempt)}")
    out["steps"] = t.steps
    return out


class HRAInput(BaseModel):
    basic_plus_da_annual: float
    hra_received_annual: float
    rent_paid_annual: float
    metro: bool = Field(False, description="Delhi, Mumbai, Kolkata, Chennai = 50%; others 40%")


def hra_exemption(inp: HRAInput) -> dict:
    sal = D(inp.basic_plus_da_annual)
    a = D(inp.hra_received_annual)
    b = max(D(inp.rent_paid_annual) - sal * pct(10), Decimal(0))
    c = sal * pct(50 if inp.metro else 40)
    ex = min(a, b, c)
    return {"exempt_hra": money(ex), "taxable_hra": money(a - ex),
            "steps": [f"Least of: HRA received {inr(a)}; rent - 10% salary {inr(b)}; {50 if inp.metro else 40}% of salary {inr(c)}",
                      "Old regime only (sec 10(13A)); not available under the new regime. Landlord PAN needed if rent > Rs 1 lakh p.a."]}


class LabourCodeWagesInput(BaseModel):
    basic: float
    da: float = 0
    retaining_allowance: float = 0
    excluded_allowances: float = Field(..., description="HRA, conveyance, special allowance, OT, commission etc.")


def labour_code_wages(inp: LabourCodeWagesInput) -> dict:
    core = D(inp.basic) + D(inp.da) + D(inp.retaining_allowance)
    excl = D(inp.excluded_allowances)
    total = core + excl
    cap = total * pct(P["labour_code_wage_exclusion_cap_pct"])
    add_back = max(excl - cap, Decimal(0))
    wages = core + add_back
    return {"total_remuneration": money(total), "wages_for_pf_gratuity": money(wages), "added_back": money(add_back),
            "steps": [f"Exclusions {inr(excl)} vs 50% of remuneration {inr(cap)}: excess {inr(add_back)} added to wages",
                      "Code on Wages / Code on Social Security definition of 'wages' (labour codes effective 21-Nov-2025) - "
                      "confirm state rules and EPFO circulars before changing payroll."]}
