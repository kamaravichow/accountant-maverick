"""Depreciation: Income-tax Act block (WDV) and Companies Act Schedule II (SLM/WDV)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from . import rates as R
from .common import D, Trail, inr, money, pct


class ITBlockInput(BaseModel):
    block: str = Field("plant_machinery_general", description=f"One of: {', '.join(R.IT_DEPRECIATION_BLOCKS)}")
    rate_override: float | None = None
    opening_wdv: float = 0
    additions_180_days_or_more: float = 0
    additions_less_than_180_days: float = 0
    sale_proceeds: float = 0
    additional_depreciation_eligible: float = Field(0, description="New P&M cost eligible u/s 32(1)(iia) (manufacturers)")
    additional_put_to_use_less_than_180_days: bool = False


def it_block_depreciation(inp: ITBlockInput) -> dict:
    t = Trail()
    rate = D(inp.rate_override if inp.rate_override is not None else R.IT_DEPRECIATION_BLOCKS[inp.block])
    full = D(inp.opening_wdv) + D(inp.additions_180_days_or_more)
    half = D(inp.additions_less_than_180_days)
    sales = D(inp.sale_proceeds)
    # sale proceeds reduce the full-rate pool first, then the half-rate pool
    s1 = min(sales, full)
    full -= s1
    s2 = min(sales - s1, half)
    half -= s2
    excess = sales - s1 - s2
    if excess > 0 or (full + half) == 0 and sales > 0:
        t(f"Block ceases/negative: excess sale proceeds {inr(excess)} is STCG u/s 50; no depreciation")
        return {"depreciation": 0.0, "closing_wdv": 0.0, "stcg_sec50": money(excess), "steps": t.steps}
    dep_full = full * pct(rate)
    dep_half = half * pct(rate) / 2
    t(f"Full-rate pool {inr(full)} @ {rate}% = {inr(dep_full)}")
    t(f"Half-rate pool (put to use < 180 days) {inr(half)} @ {rate / 2}% = {inr(dep_half)}")
    add_dep = Decimal(0)
    if inp.additional_depreciation_eligible:
        add_rate = D(R.ADDITIONAL_DEPRECIATION_PCT) / (2 if inp.additional_put_to_use_less_than_180_days else 1)
        add_dep = D(inp.additional_depreciation_eligible) * pct(add_rate)
        t(f"Additional depreciation u/s 32(1)(iia) @ {add_rate}% = {inr(add_dep)} (balance half allowed next year if < 180 days)")
    total = dep_full + dep_half + add_dep
    closing = full + half - total
    return {"rate_pct": float(rate), "depreciation": money(total), "normal": money(dep_full + dep_half),
            "additional": money(add_dep), "closing_wdv": money(closing), "steps": t.steps}


class CompaniesActInput(BaseModel):
    asset_class: str = Field("plant_machinery_general", description=f"One of: {', '.join(R.COMPANIES_ACT_USEFUL_LIFE)}")
    useful_life_override: float | None = None
    cost: float
    residual_pct: float = 5
    method: Literal["SLM", "WDV"] = "SLM"
    days_used_in_year: int = 365
    opening_carrying_amount: float | None = Field(None, description="For WDV after year 1")


def companies_act_depreciation(inp: CompaniesActInput) -> dict:
    life = D(inp.useful_life_override or R.COMPANIES_ACT_USEFUL_LIFE[inp.asset_class])
    cost = D(inp.cost)
    residual = cost * pct(inp.residual_pct)
    frac = D(inp.days_used_in_year) / 365
    if inp.method == "SLM":
        annual = (cost - residual) / life
        dep = annual * frac
        steps = [f"SLM: ({inr(cost)} - residual {inr(residual)}) / {life} years = {inr(annual)} p.a. x {inp.days_used_in_year}/365"]
        rate = annual * 100 / cost
    else:
        # WDV rate = 1 - (residual / cost) ^ (1 / life)
        rate_f = 1 - (float(residual) / float(cost)) ** (1 / float(life))
        rate = D(str(rate_f * 100))
        base = D(inp.opening_carrying_amount) if inp.opening_carrying_amount is not None else cost
        dep = base * D(str(rate_f)) * frac
        steps = [f"WDV rate = 1 - (residual/cost)^(1/{life}) = {rate:.2f}%; on {inr(base)} x {inp.days_used_in_year}/365"]
    return {"method": inp.method, "useful_life_years": float(life), "rate_pct": money(rate), "depreciation": money(dep),
            "steps": steps}
