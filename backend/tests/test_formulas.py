"""Hand-verified expectations for the preset formulas."""

from datetime import date

import pytest

from app.formulas import FORMULAS, run_formula
from app.formulas.common import months_or_part, round10


def it(**kw):
    return run_formula("income_tax_individual", kw)


# ---------- helpers ----------

def test_round10():
    assert round10(1234) == 1230
    assert round10(1235) == 1240


@pytest.mark.parametrize(
    "start,end,months",
    [
        (date(2025, 7, 31), date(2025, 8, 5), 1),
        (date(2025, 7, 31), date(2025, 8, 31), 1),
        (date(2025, 7, 31), date(2025, 9, 1), 2),
        (date(2026, 3, 31), date(2026, 7, 31), 4),
        (date(2025, 7, 31), date(2025, 7, 31), 0),
    ],
)
def test_months_or_part(start, end, months):
    assert months_or_part(start, end) == months


# ---------- income tax: new regime FY 2025-26 ----------

def test_new_regime_salary_12_75_lakh_is_nil():
    r = it(fy="2025-26", regime="new", incomes={"salary_gross": 1275000})
    assert r["total_income"] == 1200000
    assert r["rebate_87a"] == 60000
    assert r["total_tax_liability"] == 0


def test_new_regime_marginal_relief_87a():
    r = it(fy="2025-26", regime="new", incomes={"other_sources": 1210000})
    # slab tax 61,500 limited to income above 12L = 10,000; + 4% cess = 10,400
    assert r["total_tax_liability"] == 10400


def test_new_regime_16_lakh():
    r = it(fy="2025-26", regime="new", incomes={"other_sources": 1600000})
    assert r["total_tax_liability"] == 124800


def test_new_regime_25_lakh():
    r = it(fy="2025-26", regime="new", incomes={"business_profession": 2500000})
    assert r["total_tax_liability"] == 343200


def test_surcharge_marginal_relief_51_lakh():
    r = it(fy="2025-26", regime="new", incomes={"business_profession": 5100000})
    # tax 11,10,000 + sc 1,11,000 capped at 10,80,000 + 1,00,000 = 11,80,000; cess 47,200
    assert r["marginal_relief"] == 41000
    assert r["total_tax_liability"] == 1227200


def test_old_regime_10_lakh_below_60():
    r = it(fy="2025-26", regime="old", incomes={"other_sources": 1000000})
    assert r["total_tax_liability"] == 117000


def test_old_regime_rebate_5_lakh():
    r = it(fy="2025-26", regime="old", incomes={"other_sources": 500000})
    assert r["total_tax_liability"] == 0


def test_old_regime_deductions_capped():
    r = it(fy="2025-26", regime="old", incomes={"salary_gross": 1050000},
           deductions={"sec_80c": 200000, "sec_80d_self": 30000})
    # 10.5L - 50k std = 10L; 80C capped 1.5L, 80D capped 25k -> 8.25L
    assert r["total_income"] == 825000
    # 12,500 + 20% of 3.25L = 65,000 -> 77,500 + cess 3,100
    assert r["total_tax_liability"] == 80600


def test_ltcg_112a_exemption_and_no_rebate_new_regime():
    r = it(fy="2025-26", regime="new", incomes={"other_sources": 1000000, "ltcg_112a": 325000})
    # normal income 10L -> slab tax 40k (0-4:0, 4-8:20k, 8-10:20k); total income 13.25L > 12L so no rebate
    # LTCG taxable 2L @12.5% = 25,000 -> total 65,000 + 2,600 cess
    assert r["tax_on_special_income"] == 25000
    assert r["total_tax_liability"] == 67600


def test_regime_comparison():
    r = run_formula("compare_tax_regimes", {"fy": "2025-26", "incomes": {"salary_gross": 1500000},
                                            "deductions": {"sec_80c": 150000}})
    assert r["recommended"] == "new"


def test_fy_2026_27_tables_present():
    r = it(fy="FY2026-27", regime="new", incomes={"salary_gross": 1275000})
    assert r["total_tax_liability"] == 0


def test_company_115baa():
    r = run_formula("income_tax_entity", {"entity": "company_115baa", "total_income": 10000000})
    assert r["total_tax"] == 2516800  # 25.168%


# ---------- interest ----------

def test_234c_regular():
    r = run_formula("interest_234c", {"tax_on_returned_income": 100000, "paid_by_jun15": 0, "paid_by_sep15": 45000,
                                      "paid_by_dec15": 75000, "paid_by_mar15": 100000})
    # Jun: 15,000 x 3% = 450; others fully paid
    assert r["interest"] == 450


def test_234b():
    r = run_formula("interest_234b", {"fy": "2025-26", "assessed_tax": 100000, "advance_tax_paid": 50000,
                                      "payment_date": "2026-07-31"})
    # 50,000 x 1% x 4 months (Apr-Jul)
    assert r["interest"] == 2000


def test_234a():
    r = run_formula("interest_234a", {"tax_on_assessed_income": 55555, "prepaid_before_due_date": 5000,
                                      "due_date": "2026-07-31", "filing_date": "2026-09-15"})
    assert r["amount_basis"] == 50500 and r["months"] == 2 and r["interest"] == 1010


# ---------- TDS ----------

def test_194c_threshold_and_rate():
    below = run_formula("tds_calc", {"section": "194C", "amount": 25000, "payee_type": "individual_huf"})
    assert below["tds_applicable"] is False
    above = run_formula("tds_calc", {"section": "194C", "amount": 40000, "payee_type": "company"})
    assert above["tds"] == 800


def test_194j_professional_crossing_threshold_deducts_on_aggregate():
    r = run_formula("tds_calc", {"section": "194J_professional", "amount": 20000, "aggregate_in_fy_before": 40000})
    assert r["tds"] == 6000


def test_no_pan_rate():
    r = run_formula("tds_calc", {"section": "194H", "amount": 50000, "pan_available": False})
    assert r["rate_pct"] == 20 and r["tds"] == 10000


def test_194q_only_excess_over_50_lakh():
    r = run_formula("tds_calc", {"section": "194Q", "amount": 2000000, "aggregate_in_fy_before": 4000000})
    assert r["base"] == 1000000 and r["tds"] == 1000


def test_tds_interest_late_deposit():
    r = run_formula("tds_interest_201", {"tds_amount": 10000, "deductible_date": "2025-05-10",
                                         "deposited_date": "2025-07-01"})
    # due 7 Jun; late: 10-May..1-Jul = 3 months (May, Jun, Jul part) x 1.5%
    assert r["interest"] == 450


def test_234e_capped():
    r = run_formula("late_fee_234e", {"tds_in_return": 5000, "due_date": "2025-07-31", "filing_date": "2025-10-31"})
    assert r["fee"] == 5000


# ---------- GST ----------

def test_gst_split_intra_and_inter():
    intra = run_formula("gst_split", {"taxable_value": 1000, "rate": 18, "supplier_state": "27AAPFU0939F1ZV",
                                      "place_of_supply": "27"})
    assert intra["cgst"] == 90 and intra["sgst_utgst"] == 90 and intra["igst"] == 0
    inter = run_formula("gst_split", {"taxable_value": 1000, "rate": 18, "supplier_state": "27", "place_of_supply": "29"})
    assert inter["igst"] == 180


def test_gst_back_calculation():
    r = run_formula("gst_split", {"inclusive_value": 1180, "rate": 18, "supplier_state": "07", "place_of_supply": "07"})
    assert r["taxable_value"] == 1000


def test_gst_interest():
    r = run_formula("gst_interest", {"tax_amount": 100000, "due_date": "2025-06-20", "payment_date": "2025-07-20"})
    assert r["days"] == 30 and r["interest"] == pytest.approx(1479.45, abs=0.01)


def test_gst_late_fee_caps():
    r = run_formula("gst_late_fee", {"return_type": "GSTR-3B", "due_date": "2025-05-20", "filing_date": "2025-08-20",
                                     "aggregate_turnover_prev_fy": 10000000})
    assert r["late_fee_total"] == 2000
    nil = run_formula("gst_late_fee", {"return_type": "GSTR-3B", "due_date": "2025-05-20", "filing_date": "2025-05-30",
                                       "nil_return": True})
    assert nil["late_fee_total"] == 200


def test_itc_time_limit():
    r = run_formula("itc_time_limit", {"invoice_date": "2025-02-10"})
    assert r["last_date_to_avail_itc"] == "2025-11-30"


def test_rule37():
    r = run_formula("rule37_reversal", {"invoice_date": "2025-01-01", "itc_amount": 1800, "as_on": "2025-08-01"})
    assert r["must_reverse"] is True


# ---------- capital gains / depreciation / payroll / business ----------

def test_ltcg_land_indexation_option():
    r = run_formula("capital_gain", {"asset": "land_building", "purchase_date": "2010-06-01", "sale_date": "2025-06-01",
                                     "cost": 1000000, "sale_consideration": 5000000})
    assert r["long_term"] and r["section"] == "112"
    opt = r["indexation_option"]
    # indexed cost = 10L x 376/167 = 22,51,497
    assert opt["indexed_gain"] == pytest.approx(5000000 - 1000000 * 376 / 167, abs=1)


def test_listed_equity_short_term():
    r = run_formula("capital_gain", {"purchase_date": "2025-01-10", "sale_date": "2025-06-10", "cost": 100,
                                     "sale_consideration": 150})
    assert r["section"] == "111A" and r["gain"] == 50


def test_block_depreciation():
    r = run_formula("it_block_depreciation", {"block": "plant_machinery_general", "opening_wdv": 100000,
                                              "additions_180_days_or_more": 50000, "additions_less_than_180_days": 40000,
                                              "sale_proceeds": 20000})
    # (130,000 x 15%) + (40,000 x 7.5%) = 19,500 + 3,000
    assert r["depreciation"] == 22500


def test_epf():
    r = run_formula("epf_contributions", {"basic_plus_da": 30000})
    assert r["employee_epf_12pct"] == 1800 and r["employer_eps_8_33pct"] == 1250 and r["employer_epf_3_67pct"] == 550


def test_gratuity():
    r = run_formula("gratuity", {"last_drawn_basic_da_monthly": 52000, "years_of_service": 10, "extra_months": 7,
                                 "gratuity_received": 400000})
    assert r["formula_gratuity"] == 330000
    assert r["exempt_10_10"] == 330000 and r["taxable"] == 70000


def test_hra():
    r = run_formula("hra_exemption", {"basic_plus_da_annual": 600000, "hra_received_annual": 240000,
                                      "rent_paid_annual": 300000, "metro": True})
    assert r["exempt_hra"] == 240000


def test_43bh():
    r = run_formula("msme_43bh", {"fy": "2025-26", "payables": [
        {"vendor": "A", "invoice_date": "2026-03-01", "amount": 100000, "payment_date": "2026-03-10"},
        {"vendor": "B", "invoice_date": "2026-02-01", "amount": 50000, "payment_date": "2026-04-20"},
        {"vendor": "C", "invoice_date": "2026-02-01", "amount": 70000, "written_agreement_days": 60},
    ]})
    assert r["total_disallowance_43Bh"] == 120000


def test_44ad():
    r = run_formula("presumptive_income", {"section": "44AD", "turnover_digital": 25000000, "turnover_cash": 500000})
    assert r["eligible"] is True and r["minimum_presumptive_income"] == 1540000


def test_registry_schemas_are_valid():
    for f in FORMULAS.values():
        assert f.schema()["type"] == "object"
