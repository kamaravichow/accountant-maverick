"""Capital gains: holding period, indexation (CII), and post 23-Jul-2024 rates."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from . import rates as R
from .common import D, Trail, inr, money, pct


def fy_of(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    import calendar

    day = min(d.day, calendar.monthrange(d.year + y, m + 1)[1])
    return date(d.year + y, m + 1, day)


class CapitalGainInput(BaseModel):
    asset: Literal["listed_equity_stt", "equity_mf_stt", "land_building", "unlisted_shares", "debt_mf_specified",
                   "gold_other"] = "listed_equity_stt"
    purchase_date: date
    sale_date: date
    cost: float
    sale_consideration: float
    transfer_expenses: float = 0
    improvement_cost: float = 0
    improvement_date: date | None = None
    fmv_31jan2018: float | None = Field(None, description="Grandfathering for equity acquired before 1-Feb-2018 (112A)")
    stamp_duty_value: float | None = Field(None, description="Sec 50C: SDV used if > 110% of consideration")
    resident_individual_huf: bool = True


def capital_gain(inp: CapitalGainInput) -> dict:
    t = Trail()
    listed = inp.asset in ("listed_equity_stt", "equity_mf_stt")
    months = R.HOLDING_PERIOD_MONTHS["listed_security" if listed else "other"]
    long_term = inp.sale_date > _add_months(inp.purchase_date, months)
    if inp.asset == "debt_mf_specified":
        long_term = False
        t("Specified mutual fund / market-linked debenture (sec 50AA): always short-term, taxed at slab")
    t(f"Holding {inp.purchase_date} to {inp.sale_date}: {'LONG' if long_term else 'SHORT'}-term "
      f"(threshold > {months} months)")

    consideration = D(inp.sale_consideration)
    if inp.asset == "land_building" and inp.stamp_duty_value and D(inp.stamp_duty_value) > consideration * D("1.1"):
        consideration = D(inp.stamp_duty_value)
        t(f"Sec 50C: stamp duty value {inr(consideration)} exceeds 110% of consideration - deemed consideration")
    net_consideration = consideration - D(inp.transfer_expenses)

    cost = D(inp.cost)
    if inp.asset in ("listed_equity_stt", "equity_mf_stt") and inp.purchase_date < date(2018, 2, 1) and inp.fmv_31jan2018:
        fmv = min(D(inp.fmv_31jan2018), consideration)
        cost = max(cost, fmv)
        t(f"Grandfathering (sec 55(2)(ac)): cost = higher of actual cost and lower of FMV/sale = {inr(cost)}")

    gain_plain = net_consideration - cost - D(inp.improvement_cost)
    result = {"long_term": long_term, "net_consideration": money(net_consideration)}

    if not long_term:
        if listed:
            result.update(section="111A", rate_pct=20, gain=money(gain_plain))
        else:
            result.update(section="slab (STCG)", rate_pct=None, gain=money(gain_plain))
        t(f"STCG = {inr(net_consideration)} - {inr(cost + D(inp.improvement_cost))} = {inr(gain_plain)}")
    elif listed:
        result.update(section="112A", rate_pct=12.5, gain=money(gain_plain),
                      note="Rs 1.25 lakh aggregate annual exemption applies across all 112A gains")
        t(f"LTCG u/s 112A = {inr(gain_plain)} @ 12.5% above Rs 1.25 lakh")
    else:
        result.update(section="112", rate_pct=12.5, gain=money(gain_plain))
        t(f"LTCG u/s 112 without indexation = {inr(gain_plain)} @ 12.5%")
        if (inp.asset == "land_building" and inp.resident_individual_huf
                and inp.purchase_date < date(2024, 7, 23) and inp.sale_date >= date(2024, 7, 23)):
            fy_buy = max(fy_of(inp.purchase_date), "2001-02")
            fy_sale = fy_of(inp.sale_date)
            if fy_sale in R.CII and fy_buy in R.CII:
                idx_cost = cost * D(R.CII[fy_sale]) / D(R.CII[fy_buy])
                idx_imp = Decimal(0)
                if inp.improvement_cost and inp.improvement_date:
                    fy_imp = max(fy_of(inp.improvement_date), "2001-02")
                    idx_imp = D(inp.improvement_cost) * D(R.CII[fy_sale]) / D(R.CII[fy_imp])
                gain_idx = net_consideration - idx_cost - idx_imp
                tax_idx = max(gain_idx, Decimal(0)) * pct(20)
                tax_plain = max(gain_plain, Decimal(0)) * pct("12.5")
                t(f"Option (proviso to sec 112(1)): indexed cost {inr(idx_cost)} (CII {R.CII[fy_sale]}/{R.CII[fy_buy]}), "
                  f"gain {inr(gain_idx)} @ 20% = {inr(tax_idx)} vs {inr(tax_plain)} @ 12.5%")
                result["indexation_option"] = {"indexed_gain": money(gain_idx), "tax_20pct": money(tax_idx),
                                               "tax_12_5pct": money(tax_plain),
                                               "better": "indexation_20pct" if tax_idx < tax_plain else "no_indexation_12_5pct"}
            else:
                t(f"CII not available for {fy_sale}/{fy_buy} - verify via live search before using the option")
    result["steps"] = t.steps
    result["legal_basis"] = R.SOURCES["capital_gains"]
    result["exemptions_to_consider"] = ["54 (residential house)", "54EC (bonds, LTCG on land/building, max Rs 50 lakh)",
                                        "54F (any LTCG into house)", "Set-off of carried forward capital losses"]
    return result
