"""Preset, audited formulas. The agent never does tax arithmetic in its head - it calls these.

``FORMULAS`` maps a stable name to (function, pydantic input model, description). The same
registry backs the agent's ``calculate`` tool and the ``/api/formulas`` endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel

from . import business, capital_gains, depreciation, gst, income_tax, interest, payroll, tds


@dataclass(frozen=True)
class Formula:
    name: str
    fn: Callable[[Any], dict]
    model: type[BaseModel]
    description: str
    category: str

    def run(self, args: dict) -> dict:
        return self.fn(self.model.model_validate(args))

    def schema(self) -> dict:
        return self.model.model_json_schema()


_F = [
    Formula("income_tax_individual", income_tax.compute_individual_tax, income_tax.IndividualTaxInput,
            "Individual/HUF income tax for a FY under old or new regime: slabs, special-rate CG, 87A rebate with marginal "
            "relief, surcharge with marginal relief, cess, rounding u/s 288A/288B.", "Income tax"),
    Formula("compare_tax_regimes", income_tax.compare_regimes, income_tax.IndividualTaxInput,
            "Old vs new regime comparison for the same inputs with recommendation.", "Income tax"),
    Formula("income_tax_entity", income_tax.compute_entity_tax, income_tax.EntityTaxInput,
            "Firm/LLP/company tax incl. 115BAA/115BAB, surcharge marginal relief, and MAT check.", "Income tax"),
    Formula("interest_234a", interest.interest_234a, interest.Interest234AInput,
            "Interest for late filing of return (1% per month or part).", "Income tax"),
    Formula("interest_234b", interest.interest_234b, interest.Interest234BInput,
            "Interest for default in advance tax (paid < 90% of assessed tax).", "Income tax"),
    Formula("interest_234c", interest.interest_234c, interest.Interest234CInput,
            "Interest for deferment of advance tax installments (15/45/75/100%; 44AD/ADA single installment).", "Income tax"),
    Formula("advance_tax_schedule", interest.advance_tax_schedule, interest.AdvanceTaxScheduleInput,
            "Advance tax due dates and installment amounts.", "Income tax"),
    Formula("capital_gain", capital_gains.capital_gain, capital_gains.CapitalGainInput,
            "Capital gain: holding period, grandfathering, 50C, 111A/112/112A rates, indexation option for pre-23-Jul-2024 "
            "land/building.", "Income tax"),
    Formula("presumptive_income", business.presumptive_income, business.PresumptiveInput,
            "Presumptive income u/s 44AD (6%/8%) or 44ADA (50%) with eligibility limits.", "Income tax"),
    Formula("msme_43bh", business.msme_43bh, business.MSME43BhInput,
            "Sec 43B(h) disallowance for late payments to micro/small enterprises + MSMED sec 16 interest.", "Income tax"),
    Formula("it_block_depreciation", depreciation.it_block_depreciation, depreciation.ITBlockInput,
            "Income-tax WDV block depreciation with 180-day rule, additional depreciation, sec 50 STCG.", "Depreciation"),
    Formula("companies_act_depreciation", depreciation.companies_act_depreciation, depreciation.CompaniesActInput,
            "Companies Act Schedule II depreciation (SLM/WDV) from useful life and residual value.", "Depreciation"),
    Formula("tds_calc", tds.tds_calc, tds.TDSInput,
            "TDS applicability, threshold, rate (incl. 206AA no-PAN) for a payment.", "TDS"),
    Formula("tds_interest_201", tds.tds_interest_201, tds.TDSInterestInput,
            "Interest u/s 201(1A): 1% p.m. late deduction, 1.5% p.m. late deposit.", "TDS"),
    Formula("late_fee_234e", tds.late_fee_234e, tds.LateFee234EInput,
            "Late fee for TDS/TCS return: Rs 200/day capped at TDS.", "TDS"),
    Formula("disallowance_40a_ia", tds.disallowance_40a_ia, tds.Disallowance40aiaInput,
            "30% disallowance for TDS default on resident payments.", "TDS"),
    Formula("gst_split", gst.gst_split, gst.GSTSplitInput,
            "GST computation and IGST vs CGST+SGST split by place of supply; back-calculation from inclusive value.", "GST"),
    Formula("gst_interest", gst.gst_interest, gst.GSTInterestInput,
            "GST interest u/s 50(1)/50(3) at 18% p.a., day-wise.", "GST"),
    Formula("gst_late_fee", gst.gst_late_fee, gst.GSTLateFeeInput,
            "Late fee for GSTR-3B/GSTR-1/GSTR-9/GSTR-4 with turnover-based caps.", "GST"),
    Formula("itc_time_limit", gst.itc_time_limit, gst.ITCTimeLimitInput,
            "Last date to avail ITC for an invoice u/s 16(4).", "GST"),
    Formula("rule37_reversal", gst.rule37_reversal, gst.Rule37Input,
            "Rule 37 ITC reversal if supplier not paid within 180 days.", "GST"),
    Formula("hsn_digits_required", gst.hsn_digits_required, gst.HSNDigitsInput,
            "Minimum HSN digits and e-invoicing applicability from AATO.", "GST"),
    Formula("epf_contributions", payroll.epf_contributions, payroll.EPFInput,
            "EPF/EPS/EDLI/admin contributions.", "Payroll"),
    Formula("esi_contributions", payroll.esi_contributions, payroll.ESIInput, "ESI contributions.", "Payroll"),
    Formula("gratuity", payroll.gratuity, payroll.GratuityInput, "Gratuity amount and sec 10(10) exemption.", "Payroll"),
    Formula("hra_exemption", payroll.hra_exemption, payroll.HRAInput, "HRA exemption u/s 10(13A).", "Payroll"),
    Formula("labour_code_wages", payroll.labour_code_wages, payroll.LabourCodeWagesInput,
            "'Wages' under the labour codes (50% exclusion cap) for PF/gratuity base.", "Payroll"),
]

FORMULAS: dict[str, Formula] = {f.name: f for f in _F}


def run_formula(name: str, args: dict) -> dict:
    if name not in FORMULAS:
        raise KeyError(f"Unknown formula '{name}'. Available: {', '.join(FORMULAS)}")
    return FORMULAS[name].run(args)


def catalog() -> list[dict]:
    return [{"name": f.name, "category": f.category, "description": f.description} for f in _F]
