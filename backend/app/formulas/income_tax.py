"""Income-tax computation for individuals/HUF (old vs new regime) and entities."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from . import rates as R
from .common import D, Trail, inr, money, pct, r0, round10


class IncomeHeads(BaseModel):
    salary_gross: float = Field(0, description="Gross salary incl. taxable perquisites, before standard deduction")
    salary_exemptions: float = Field(0, description="Old regime only: HRA 10(13A), LTA etc. already exempt")
    professional_tax: float = Field(0, description="Old regime only: sec 16(iii)")
    family_pension: float = 0
    house_property: float = Field(0, description="Net income from house property (negative = loss)")
    business_profession: float = 0
    other_sources: float = Field(0, description="Interest, dividends etc. at normal rates")
    stcg_111a: float = Field(0, description="STT-paid equity STCG (20%)")
    ltcg_112a: float = Field(0, description="STT-paid equity LTCG before Rs 1.25 lakh exemption (12.5%)")
    ltcg_112: float = Field(0, description="Other LTCG (12.5% without indexation, or 20% if indexation opted)")
    ltcg_112_rate: float = Field(12.5, description="12.5 (default) or 20 for pre-23-Jul-2024 land/building with indexation")
    stcg_normal: float = Field(0, description="Other STCG taxed at slab rates")
    winnings_115bb: float = Field(0, description="Lottery, online games etc. (flat 30%)")


class Deductions(BaseModel):
    """Chapter VI-A and similar. Caps are applied automatically; new regime allows only some."""

    sec_80c: float = 0
    sec_80ccd_1b: float = 0
    sec_80ccd_2: float = Field(0, description="Employer NPS contribution (allowed in both regimes, capped)")
    sec_80d_self: float = 0
    sec_80d_parents: float = 0
    parents_senior: bool = False
    sec_80e: float = 0
    sec_80g: float = Field(0, description="Eligible amount after qualifying-limit working")
    sec_80tta_ttb: float = 0
    sec_24b_self_occupied: float = Field(0, description="Interest on self-occupied house loan (old regime only)")
    other_old_regime: float = Field(0, description="Any other old-regime deduction already capped by you")
    sec_80jjaa: float = 0
    basic_plus_da: float = Field(0, description="Needed to cap 80CCD(2)")


class IndividualTaxInput(BaseModel):
    fy: str = Field("2025-26", description="Financial year, e.g. 2025-26 (AY 2026-27) or 2026-27 (tax year)")
    regime: Literal["new", "old"] = "new"
    age: int = 35
    resident: bool = True
    incomes: IncomeHeads = Field(default_factory=IncomeHeads)
    deductions: Deductions = Field(default_factory=Deductions)
    tds_tcs: float = 0
    advance_tax_paid: float = 0
    self_assessment_paid: float = 0


def slab_tax(income: Decimal, slabs: list[tuple], trail: Trail | None = None) -> Decimal:
    tax = Decimal(0)
    lower = Decimal(0)
    for upper, rate in slabs:
        top = income if upper is None else min(income, D(upper))
        if top > lower:
            part = (top - lower) * pct(rate)
            if trail is not None and rate:
                trail(f"  {inr(lower)} - {inr(top)} @ {rate}% = {inr(part)}")
            tax += part
        if upper is None or income <= D(upper):
            break
        lower = D(upper)
    return tax


def _surcharge_rate(total_income: Decimal, table: list[tuple]) -> Decimal:
    rate = Decimal(0)
    for threshold, r in table:
        if total_income > D(threshold):
            rate = D(r)
    return rate


def _age_band(age: int) -> str:
    if age >= 80:
        return "super_senior_80_plus"
    if age >= 60:
        return "senior_60_79"
    return "below_60"


def compute_individual_tax(inp: IndividualTaxInput) -> dict:
    fy = R.fy_key(inp.fy)
    if fy not in R.PERSONAL:
        raise ValueError(f"No personal tax tables for FY {fy}; verify rates via live search.")
    year = R.PERSONAL[fy]
    reg = year[inp.regime]
    t = Trail()
    inc, ded = inp.incomes, inp.deductions
    t(f"FY {fy}, {inp.regime.upper()} regime, age {inp.age}, {'resident' if inp.resident else 'non-resident'}")

    # --- Salary -------------------------------------------------------------------
    salary = D(inc.salary_gross)
    if salary > 0:
        std = min(salary, D(reg["standard_deduction_salary"]))
        salary -= std
        t(f"Salary {inr(inc.salary_gross)} - standard deduction {inr(std)}")
        if inp.regime == "old":
            salary -= D(inc.salary_exemptions) + min(D(inc.professional_tax), D(2500))
            if inc.salary_exemptions or inc.professional_tax:
                t(f"  less exemptions {inr(inc.salary_exemptions)} and professional tax {inr(min(inc.professional_tax, 2500))}")
        salary = max(salary, Decimal(0))
    fam = D(inc.family_pension)
    if fam > 0:
        fam -= min(fam / 3, D(reg["family_pension_deduction"]))

    # --- House property: set-off of loss limited to Rs 2 lakh (old); new regime disallows set-off
    hp = D(inc.house_property)
    if inp.regime == "old":
        hp -= min(D(ded.sec_24b_self_occupied), D(R._OLD_REGIME["deduction_caps"]["24b_self_occupied"]))
        if hp < -200000:
            t(f"House property loss {inr(hp)} restricted to Rs 2,00,000 for set-off (sec 71(3A))")
            hp = D(-200000)
    elif hp < 0:
        t("House property loss cannot be set off against other heads under the new regime - ignored")
        hp = Decimal(0)

    gti_normal = salary + fam + hp + D(inc.business_profession) + D(inc.other_sources) + D(inc.stcg_normal)
    gti_normal = max(gti_normal, Decimal(0))

    # --- Chapter VI-A ----------------------------------------------------------------
    caps = R._OLD_REGIME["deduction_caps"]
    cap_80ccd2 = D(ded.basic_plus_da) * pct(reg["employer_nps_pct_of_salary"]) if ded.basic_plus_da else D(ded.sec_80ccd_2)
    allowed = {"80CCD(2)": min(D(ded.sec_80ccd_2), cap_80ccd2), "80JJAA": D(ded.sec_80jjaa)}
    if inp.regime == "old":
        senior = inp.age >= 60
        allowed.update(
            {
                "80C/80CCC/80CCD(1)": min(D(ded.sec_80c), D(caps["80C_80CCC_80CCD1"])),
                "80CCD(1B)": min(D(ded.sec_80ccd_1b), D(caps["80CCD1B"])),
                "80D (self/family)": min(D(ded.sec_80d_self), D(caps["80D_self_senior" if senior else "80D_self"])),
                "80D (parents)": min(
                    D(ded.sec_80d_parents), D(caps["80D_parents_senior" if ded.parents_senior else "80D_parents"])
                ),
                "80E": D(ded.sec_80e),
                "80G": D(ded.sec_80g),
                "80TTA/80TTB": min(D(ded.sec_80tta_ttb), D(caps["80TTB_senior" if senior else "80TTA"])),
                "other": D(ded.other_old_regime),
            }
        )
    via = sum(allowed.values(), Decimal(0))
    via = min(via, gti_normal)  # deductions cannot exceed income at normal rates
    for k, v in allowed.items():
        if v:
            t(f"Deduction {k}: {inr(v)}")

    normal_income = gti_normal - via
    special = {
        "stcg_111a": D(inc.stcg_111a),
        "ltcg_112": D(inc.ltcg_112),
        "ltcg_112a": max(D(inc.ltcg_112a) - D(R.SPECIAL_RATES["ltcg_112a"][1]), Decimal(0)),
        "winnings_115bb": D(inc.winnings_115bb),
    }
    if inc.ltcg_112a:
        t(f"LTCG 112A {inr(inc.ltcg_112a)} less exemption Rs 1,25,000 = {inr(special['ltcg_112a'])}")

    total_income = round10(normal_income + sum(special.values(), Decimal(0)) + min(D(inc.ltcg_112a), D(125000)))
    # Note: the 1.25 lakh 112A exemption is part of total income but taxed at nil.
    t(f"Total income (rounded u/s 288A): {inr(total_income)}")

    # --- Basic exemption shortfall adjusted against special-rate income (residents only) ---
    slabs = reg["slabs"] if inp.regime == "new" else reg["slabs"][_age_band(inp.age)]
    basic_exemption = D(slabs[0][0])
    if inp.resident and normal_income < basic_exemption:
        shortfall = basic_exemption - normal_income
        for key in ("stcg_111a", "ltcg_112", "ltcg_112a"):
            use = min(shortfall, special[key])
            if use > 0:
                special[key] -= use
                shortfall -= use
                t(f"Unused basic exemption {inr(use)} adjusted against {key}")

    # --- Tax -------------------------------------------------------------------------
    t("Tax on normal income at slab rates:")
    tax_normal = slab_tax(normal_income, slabs, t)
    ltcg112_rate = D(inc.ltcg_112_rate)
    tax_special = {
        "stcg_111a": special["stcg_111a"] * pct(R.SPECIAL_RATES["stcg_111a"][0]),
        "ltcg_112a": special["ltcg_112a"] * pct(R.SPECIAL_RATES["ltcg_112a"][0]),
        "ltcg_112": special["ltcg_112"] * pct(ltcg112_rate),
        "winnings_115bb": special["winnings_115bb"] * pct(R.SPECIAL_RATES["winnings_115bb"][0]),
    }
    for k, v in tax_special.items():
        if v:
            t(f"Tax on {k}: {inr(v)}")
    tax_special_total = sum(tax_special.values(), Decimal(0))
    tax_before_rebate = tax_normal + tax_special_total

    # --- Rebate 87A (sec 157 of ITA 2025) -----------------------------------------------
    rebate = Decimal(0)
    if inp.resident:
        limit, rmax = D(reg["rebate_income_limit"]), D(reg["rebate_max"])
        # New regime: not available against special-rate tax; old: available except 112A/115BB.
        eligible_tax = tax_normal if inp.regime == "new" else tax_normal + tax_special["stcg_111a"] + tax_special["ltcg_112"]
        if total_income <= limit:
            rebate = min(eligible_tax, rmax)
            t(f"Rebate u/s 87A (income <= {inr(limit)}): {inr(rebate)}")
        elif inp.regime == "new" and fy >= "2023-24":
            excess = total_income - limit
            if eligible_tax > excess:
                rebate = eligible_tax - excess
                t(f"Marginal relief on 87A: tax on normal income limited to income above {inr(limit)} = {inr(excess)}")
    tax_after_rebate = max(tax_before_rebate - rebate, Decimal(0))

    # --- Surcharge with marginal relief --------------------------------------------------
    table = reg["surcharge"]
    rate = _surcharge_rate(total_income, table)
    surcharge = Decimal(0)
    relief = Decimal(0)
    if rate:
        cap = D(year["special_rate_surcharge_cap_pct"])
        spec_eq = tax_special["stcg_111a"] + tax_special["ltcg_112a"] + tax_special["ltcg_112"]
        normal_part = tax_after_rebate - spec_eq
        surcharge = normal_part * pct(rate) + spec_eq * pct(min(rate, cap))
        t(f"Surcharge @ {rate}% (special-rate capital gains capped at {cap}%): {inr(surcharge)}")
        # marginal relief: tax+surcharge must not exceed tax at threshold + income above threshold
        threshold = max(D(th) for th, r in table if total_income > D(th))
        lower_rate = _surcharge_rate(threshold, table)
        tax_at_threshold = _individual_tax_at(threshold, total_income, normal_income, tax_normal, tax_special_total, slabs)
        ceiling = tax_at_threshold * (1 + pct(lower_rate)) + (total_income - threshold)
        if tax_after_rebate + surcharge > ceiling:
            relief = tax_after_rebate + surcharge - ceiling
            t(f"Marginal relief on surcharge: {inr(relief)}")
    tax_plus_sc = tax_after_rebate + surcharge - relief
    cess = tax_plus_sc * pct(year["cess_pct"])
    t(f"Health & education cess @ {year['cess_pct']}%: {inr(cess)}")
    gross_liability = round10(tax_plus_sc + cess)
    prepaid = D(inp.tds_tcs) + D(inp.advance_tax_paid) + D(inp.self_assessment_paid)
    net = gross_liability - prepaid
    t(f"Total tax liability (rounded u/s 288B): {inr(gross_liability)}; prepaid taxes {inr(prepaid)}; "
      f"{'payable' if net >= 0 else 'refund'} {inr(abs(net))}")

    return {
        "fy": fy,
        "regime": inp.regime,
        "gross_total_income": money(gti_normal + sum(special.values(), Decimal(0))),
        "deductions_via": money(via),
        "total_income": money(total_income),
        "tax_on_normal_income": money(tax_normal),
        "tax_on_special_income": money(tax_special_total),
        "rebate_87a": money(rebate),
        "surcharge": money(surcharge),
        "marginal_relief": money(relief),
        "cess": money(cess),
        "total_tax_liability": money(gross_liability),
        "prepaid_taxes": money(prepaid),
        "net_payable": money(net) if net > 0 else 0.0,
        "refund": money(-net) if net < 0 else 0.0,
        "effective_rate_pct": money(gross_liability * 100 / total_income) if total_income else 0.0,
        "steps": t.steps,
        "legal_basis": [R.SOURCES["slabs_2026_27" if fy >= "2026-27" else "slabs_2025_26"], R.SOURCES["capital_gains"]],
    }


def _individual_tax_at(threshold: Decimal, total_income: Decimal, normal_income: Decimal,
                       tax_normal: Decimal, tax_special: Decimal, slabs: list) -> Decimal:
    """Tax (before surcharge) on an income exactly equal to ``threshold``, holding the
    special-rate component constant and trimming normal income - the standard marginal
    relief working."""
    excess = total_income - threshold
    normal_at = max(normal_income - excess, Decimal(0))
    if normal_at == normal_income:
        return tax_normal + tax_special
    return slab_tax(normal_at, slabs) + tax_special


def compare_regimes(inp: IndividualTaxInput) -> dict:
    old = compute_individual_tax(inp.model_copy(update={"regime": "old"}))
    new = compute_individual_tax(inp.model_copy(update={"regime": "new"}))
    better = "new" if new["total_tax_liability"] <= old["total_tax_liability"] else "old"
    return {
        "old_regime_tax": old["total_tax_liability"],
        "new_regime_tax": new["total_tax_liability"],
        "recommended": better,
        "saving": round(abs(old["total_tax_liability"] - new["total_tax_liability"]), 2),
        "note": "Salaried individuals may switch regime every year; those with business income can "
        "opt out of the new regime (Form 10-IEA) only once.",
        "old": old,
        "new": new,
    }


class EntityTaxInput(BaseModel):
    fy: str = "2025-26"
    entity: Literal[
        "firm_llp", "domestic_company_small", "domestic_company", "company_115baa", "company_115bab",
        "cooperative_115bad",
    ] = "company_115baa"
    total_income: float
    book_profit_115jb: float | None = Field(None, description="For MAT check (not applicable to 115BAA/115BAB)")


def compute_entity_tax(inp: EntityTaxInput) -> dict:
    t = Trail()
    cfg = R.ENTITY[inp.entity]
    ti = round10(inp.total_income)
    tax = ti * pct(cfg["rate"])
    t(f"{inp.entity}: total income {inr(ti)} @ {cfg['rate']}% = {inr(tax)}")
    surcharge = Decimal(0)
    relief = Decimal(0)
    if "surcharge_flat" in cfg:
        surcharge = tax * pct(cfg["surcharge_flat"])
        t(f"Flat surcharge {cfg['surcharge_flat']}% = {inr(surcharge)}")
    else:
        rate = _surcharge_rate(ti, cfg["surcharge"])
        if rate:
            surcharge = tax * pct(rate)
            threshold = max(D(th) for th, r in cfg["surcharge"] if ti > D(th))
            lower = _surcharge_rate(threshold, cfg["surcharge"])
            ceiling = threshold * pct(cfg["rate"]) * (1 + pct(lower)) + (ti - threshold)
            if tax + surcharge > ceiling:
                relief = tax + surcharge - ceiling
                t(f"Marginal relief {inr(relief)}")
            t(f"Surcharge @ {rate}% = {inr(surcharge)}")
    cess = (tax + surcharge - relief) * pct(cfg["cess"])
    total = round10(tax + surcharge - relief + cess)
    t(f"Cess @ {cfg['cess']}% = {inr(cess)}; total {inr(total)}")
    out = {
        "entity": inp.entity,
        "total_income": money(ti),
        "tax": money(tax),
        "surcharge": money(surcharge),
        "marginal_relief": money(relief),
        "cess": money(cess),
        "total_tax": money(total),
        "effective_rate_pct": money(total * 100 / ti) if ti else 0.0,
        "steps": t.steps,
    }
    if inp.book_profit_115jb is not None and inp.entity not in ("company_115baa", "company_115bab", "firm_llp"):
        bp = D(inp.book_profit_115jb)
        mat = bp * pct(R.ENTITY["mat_115jb"]["rate"])
        mat_rate = _surcharge_rate(bp, R.ENTITY["domestic_company"]["surcharge"])
        mat_total = r0((mat * (1 + pct(mat_rate))) * D("1.04"))
        out["mat_115jb"] = money(mat_total)
        out["tax_payable"] = max(out["total_tax"], money(mat_total))
        out["mat_credit_generated"] = money(max(mat_total - total, 0))
        t(f"MAT @ 15% on book profit {inr(bp)} incl. surcharge & cess = {inr(mat_total)}")
    return out
