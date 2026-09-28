"""Versioned rate tables for Indian direct & indirect tax.

Every table is keyed by financial year (``"2025-26"`` = FY 2025-26 / AY 2026-27).
From 1 April 2026 the Income-tax Act, 2025 replaces the 1961 Act; FY 2026-27 is
"Tax Year 2026-27" under the new Act. Budget 2026 left personal slabs unchanged,
so the FY 2026-27 tables equal FY 2025-26 unless noted.

Keep this file the single source of truth. When law changes, add a new FY key
(never edit a past year) and cite the source in ``SOURCES``. The agent is told to
verify rates with live search when a computation depends on a year or item not
covered here.
"""

from __future__ import annotations

from decimal import Decimal as Dec

INF = None  # open-ended slab upper bound

SOURCES = {
    "slabs_2025_26": "Finance Act 2025 (sec 115BAC(1A)); new regime slabs 4/8/12/16/20/24 lakh; 87A rebate "
    "to Rs 60,000 for total income up to Rs 12 lakh.",
    "slabs_2026_27": "Union Budget 2026: no change to personal income-tax slabs; Income-tax Act 2025 in force "
    "from 1-Apr-2026 (new regime = sec 202, rebate = sec 157, per section mapping tables).",
    "capital_gains": "Finance (No.2) Act 2024: STCG 111A 20%, LTCG 112A 12.5% above Rs 1.25 lakh, "
    "LTCG 112 12.5% without indexation for transfers on/after 23-Jul-2024.",
    "tds": "Finance Act 2025 revised TDS thresholds (194A, 194H, 194I per month, 194J 50k etc.), omitted "
    "206AB/206CCA and TCS 206C(1H). Under ITA 2025 TDS moves to sec 392 (salary) / 393 (others).",
    "gst_late_fee": "CGST Notification 19/2021-CT (GSTR-3B), 20/2021-CT (GSTR-1), 7/2023-CT (GSTR-9) - "
    "amounts shown are CGST+SGST combined.",
    "gst_interest": "Sec 50(1) CGST Act 18% p.a. on net cash liability; sec 50(3) read with N/N 9/2022-CT: "
    "18% on ITC wrongly availed AND utilised.",
    "gst_rates": "GST 2.0 rate rationalisation (56th GST Council, effective 22-Sep-2025): slabs 5% / 18% "
    "plus 40% demerit rate; 12% and 28% slabs largely removed.",
    "cii": "CBDT notified Cost Inflation Index (base FY 2001-02 = 100).",
}

# --- Personal income tax ---------------------------------------------------------------

_NEW_REGIME_2025 = {
    "slabs": [(400000, 0), (800000, 5), (1200000, 10), (1600000, 15), (2000000, 20), (2400000, 25), (INF, 30)],
    "standard_deduction_salary": 75000,
    "family_pension_deduction": 25000,
    "rebate_income_limit": 1200000,
    "rebate_max": 60000,
    # (threshold, rate%) - new regime surcharge is capped at 25%
    "surcharge": [(5000000, 10), (10000000, 15), (20000000, 25)],
    "employer_nps_pct_of_salary": 14,
}

_OLD_REGIME = {
    "slabs": {
        "below_60": [(250000, 0), (500000, 5), (1000000, 20), (INF, 30)],
        "senior_60_79": [(300000, 0), (500000, 5), (1000000, 20), (INF, 30)],
        "super_senior_80_plus": [(500000, 0), (1000000, 20), (INF, 30)],
    },
    "standard_deduction_salary": 50000,
    "family_pension_deduction": 15000,
    "rebate_income_limit": 500000,
    "rebate_max": 12500,
    "surcharge": [(5000000, 10), (10000000, 15), (20000000, 25), (50000000, 37)],
    "deduction_caps": {
        "80C_80CCC_80CCD1": 150000,
        "80CCD1B": 50000,
        "80D_self": 25000,
        "80D_self_senior": 50000,
        "80D_parents": 25000,
        "80D_parents_senior": 50000,
        "80TTA": 10000,
        "80TTB_senior": 50000,
        "24b_self_occupied": 200000,
        "80EEA": 150000,
    },
    "employer_nps_pct_of_salary": 10,
}

PERSONAL = {
    "2024-25": {  # AY 2025-26 (for revised/belated returns and 234 interest work)
        "new": {
            "slabs": [(300000, 0), (700000, 5), (1000000, 10), (1200000, 15), (1500000, 20), (INF, 30)],
            "standard_deduction_salary": 75000,
            "family_pension_deduction": 25000,
            "rebate_income_limit": 700000,
            "rebate_max": 25000,
            "surcharge": [(5000000, 10), (10000000, 15), (20000000, 25)],
            "employer_nps_pct_of_salary": 14,
        },
        "old": _OLD_REGIME,
        "cess_pct": 4,
        "special_rate_surcharge_cap_pct": 15,
    },
    "2025-26": {"new": _NEW_REGIME_2025, "old": _OLD_REGIME, "cess_pct": 4, "special_rate_surcharge_cap_pct": 15},
    "2026-27": {"new": _NEW_REGIME_2025, "old": _OLD_REGIME, "cess_pct": 4, "special_rate_surcharge_cap_pct": 15},
}

SPECIAL_RATES = {
    # rate %, annual exemption (Rs)
    "stcg_111a": (20, 0),
    "ltcg_112a": (Dec("12.5"), 125000),
    "ltcg_112": (Dec("12.5"), 0),
    "winnings_115bb": (30, 0),
}

# --- Entity income tax (firms, LLPs, companies) ------------------------------------------

ENTITY = {
    "firm_llp": {"rate": 30, "surcharge": [(10000000, 12)], "cess": 4},
    "domestic_company_small": {  # turnover in base year (FY 2022-23) <= Rs 400 cr
        "rate": 25,
        "surcharge": [(10000000, 7), (100000000, 12)],
        "cess": 4,
        "turnover_limit": 4000000000,
    },
    "domestic_company": {"rate": 30, "surcharge": [(10000000, 7), (100000000, 12)], "cess": 4},
    "company_115baa": {"rate": 22, "surcharge_flat": 10, "cess": 4},  # effective 25.168%
    "company_115bab": {"rate": 15, "surcharge_flat": 10, "cess": 4},  # new manufacturing; eff. 17.16%
    "mat_115jb": {"rate": 15},
    "cooperative_115bad": {"rate": 22, "surcharge_flat": 10, "cess": 4},
}

# --- Presumptive taxation ---------------------------------------------------------------

PRESUMPTIVE = {
    "44AD": {
        "rate_digital": 6,
        "rate_cash": 8,
        "turnover_limit": 20000000,
        "turnover_limit_if_cash_le_5pct": 30000000,
    },
    "44ADA": {"rate": 50, "receipts_limit": 5000000, "receipts_limit_if_cash_le_5pct": 7500000},
    "44AE": {"heavy_per_ton_per_month": 1000, "other_per_vehicle_per_month": 7500, "max_vehicles": 10},
}

# --- TDS (FY 2025-26 onwards; ITA 2025 sec 392/393 from 1-Apr-2026) -----------------------
# rate is % ; threshold semantics documented per entry.

TDS = {
    "194A": {
        "nature": "Interest other than on securities",
        "rate": 10,
        "threshold_single": 0,
        "threshold_aggregate": {"bank_coop_post_office": 50000, "bank_senior_citizen": 100000, "others": 10000},
    },
    "194C": {
        "nature": "Payment to contractors / sub-contractors",
        "rate_individual_huf": 1,
        "rate_others": 2,
        "threshold_single": 30000,
        "threshold_aggregate": 100000,
    },
    "194D": {"nature": "Insurance commission", "rate_individual_huf": 2, "rate_others": 10, "threshold_aggregate": 20000},
    "194H": {"nature": "Commission or brokerage", "rate": 2, "threshold_aggregate": 20000},
    "194I_plant": {"nature": "Rent - plant, machinery, equipment", "rate": 2, "threshold_per_month": 50000},
    "194I_building": {"nature": "Rent - land, building, furniture", "rate": 10, "threshold_per_month": 50000},
    "194IA": {"nature": "Transfer of immovable property (non-agricultural)", "rate": 1, "threshold_single": 5000000},
    "194IB": {"nature": "Rent by individual/HUF not under audit", "rate": 2, "threshold_per_month": 50000},
    "194J_technical": {
        "nature": "Fees for technical services, call centre, royalty on film sale",
        "rate": 2,
        "threshold_aggregate": 50000,
    },
    "194J_professional": {"nature": "Fees for professional services, royalty, non-compete", "rate": 10, "threshold_aggregate": 50000},
    "194J_director": {"nature": "Remuneration/fees to director (non-salary)", "rate": 10, "threshold_aggregate": 0},
    "194M": {"nature": "Contract/commission/professional by individual/HUF not liable to audit", "rate": 2, "threshold_aggregate": 5000000},
    "194N": {"nature": "Cash withdrawal", "rate": 2, "threshold_aggregate": 10000000},
    "194O": {"nature": "E-commerce operator payments", "rate": Dec("0.1"), "threshold_aggregate": 500000},
    "194Q": {"nature": "Purchase of goods (buyer turnover > Rs 10 cr)", "rate": Dec("0.1"), "threshold_excess_over": 5000000},
    "194R": {"nature": "Business perquisites", "rate": 10, "threshold_aggregate": 20000},
    "194S": {"nature": "Transfer of virtual digital asset", "rate": 1, "threshold_aggregate": 50000},
    "194T": {"nature": "Salary/commission/interest to partners", "rate": 10, "threshold_aggregate": 20000},
    "194": {"nature": "Dividend", "rate": 10, "threshold_aggregate": 10000},
}
TDS_NO_PAN_RATE = 20  # sec 206AA: higher of twice the rate, the rate in force, or 20% (5% for 194O/194Q)
TDS_NO_PAN_RATE_LOW = 5
ITA2025_SECTION_MAP = {
    "192": "392",
    "194*": "393 (table entry)",
    "206C*": "394",
    "115BAC": "202",
    "87A": "157",
    "80C": "123",
    "10(*)": "Schedule II",
}

TDS_DUE = {
    "deposit": "7th of the following month; for March deductions 30 April (govt: same day if without challan)",
    "returns": {"Q1": "31-Jul", "Q2": "31-Oct", "Q3": "31-Jan", "Q4": "31-May"},
    "late_fee_234E_per_day": 200,
    "interest_201_1A_not_deducted_pct_pm": 1,
    "interest_201_1A_not_paid_pct_pm": Dec("1.5"),
    "disallowance_40a_ia_pct": 30,
}

# --- GST --------------------------------------------------------------------------------

GST_INTEREST = {"50(1)": 18, "50(3)": 18}

# Late fee per day and caps, CGST+SGST combined (IGST-only filers pay the same total).
GST_LATE_FEE = {
    "GSTR-3B": {
        "per_day": 50,
        "per_day_nil": 20,
        "caps": [(0, "nil", 500), (15000000, "upto_1.5cr", 2000), (50000000, "1.5cr_to_5cr", 5000), (INF, "above_5cr", 10000)],
    },
    "GSTR-1": {
        "per_day": 50,
        "per_day_nil": 20,
        "caps": [(0, "nil", 500), (15000000, "upto_1.5cr", 2000), (50000000, "1.5cr_to_5cr", 5000), (INF, "above_5cr", 10000)],
    },
    "GSTR-9": {
        # (turnover upper bound, per day, cap as % of turnover in the state)
        "slabs": [(50000000, 50, Dec("0.04")), (200000000, 100, Dec("0.04")), (INF, 200, Dec("0.5"))],
    },
    "GSTR-4": {"per_day": 50, "per_day_nil": 20, "cap": 2000, "cap_nil": 500},
}

GST_STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu (pre-merger)", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra",
    "28": "Andhra Pradesh (old)", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
    "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction",
}

GST_VALID_RATES_POST_22SEP2025 = [0, Dec("0.1"), Dec("0.25"), 1, Dec("1.5"), 3, 5, 18, 40]
GST_VALID_RATES_PRE_22SEP2025 = [0, Dec("0.1"), Dec("0.25"), 1, Dec("1.5"), 3, 5, 6, 12, 18, 28]
GST_RATE_CHANGE_DATE = "2025-09-22"

GST_THRESHOLDS = {
    "e_invoice_aato": 50000000,
    "e_invoice_30_day_reporting_aato": 100000000,
    "hsn_digits": [(50000000, 4), (INF, 6)],  # AATO up to 5 cr: 4 digits; above: 6 digits
    "eway_bill_value": 50000,
    "itc_rule37_days": 180,
    "registration_goods": 4000000,
    "registration_services": 2000000,
    "registration_special_category": 1000000,
}

# --- Capital gains ----------------------------------------------------------------------

CII = {
    "2001-02": 100, "2002-03": 105, "2003-04": 109, "2004-05": 113, "2005-06": 117, "2006-07": 122,
    "2007-08": 129, "2008-09": 137, "2009-10": 148, "2010-11": 167, "2011-12": 184, "2012-13": 200,
    "2013-14": 220, "2014-15": 240, "2015-16": 254, "2016-17": 264, "2017-18": 272, "2018-19": 280,
    "2019-20": 289, "2020-21": 301, "2021-22": 317, "2022-23": 331, "2023-24": 348, "2024-25": 363,
    "2025-26": 376,
}
CG_REGIME_CHANGE_DATE = "2024-07-23"
HOLDING_PERIOD_MONTHS = {"listed_security": 12, "other": 24}

# --- Depreciation -----------------------------------------------------------------------

IT_DEPRECIATION_BLOCKS = {
    "building_residential": 5,
    "building_non_residential": 10,
    "building_temporary": 40,
    "furniture_fittings": 10,
    "plant_machinery_general": 15,
    "motor_car_non_commercial": 15,
    "motor_vehicle_commercial_hire": 30,
    "computers_software": 40,
    "books_professional": 40,
    "energy_saving_devices": 40,
    "intangibles": 25,
    "ships": 20,
}
ADDITIONAL_DEPRECIATION_PCT = 20  # sec 32(1)(iia), new P&M by manufacturers

# Companies Act 2013 Schedule II useful lives (years), residual value 5%.
COMPANIES_ACT_USEFUL_LIFE = {
    "building_rcc_non_factory": 60,
    "building_factory": 30,
    "plant_machinery_general": 15,
    "furniture_fittings": 10,
    "motor_car": 8,
    "motor_cycle": 10,
    "commercial_vehicle": 6,
    "computers_end_user": 3,
    "servers_networks": 6,
    "office_equipment": 5,
    "electrical_installations": 10,
}

# --- Payroll ----------------------------------------------------------------------------

PAYROLL = {
    "epf_employee_pct": 12,
    "epf_employer_pct": 12,
    "eps_pct": Dec("8.33"),
    "eps_wage_ceiling": 15000,
    "edli_pct": Dec("0.5"),
    "edli_wage_ceiling": 15000,
    "epf_admin_pct": Dec("0.5"),
    "esi_employee_pct": Dec("0.75"),
    "esi_employer_pct": Dec("3.25"),
    "esi_wage_ceiling": 21000,
    "gratuity_exempt_limit": 2000000,
    "leave_encashment_exempt_limit": 2500000,
    # Code on Social Security 2020 (labour codes in force from 21-Nov-2025): exclusions from
    # "wages" above 50% of total remuneration are added back to wages.
    "labour_code_wage_exclusion_cap_pct": 50,
}

# --- MSME / sec 43B(h) ------------------------------------------------------------------

MSME = {
    "days_without_agreement": 15,
    "days_with_agreement_max": 45,
    "msmed_interest_multiple_of_bank_rate": 3,  # sec 16 MSMED Act, compounded monthly
}

ADVANCE_TAX = {
    "threshold": 10000,
    "installments": [("06-15", 15, 12), ("09-15", 45, 36), ("12-15", 75, None), ("03-15", 100, None)],
    "presumptive_installments": [("03-15", 100, None)],
}


def fy_key(fy: str) -> str:
    """Accepts 'FY2025-26', '2025-26', '2025', 'AY2026-27' -> '2025-26'."""
    s = str(fy).upper().replace(" ", "").replace("FY", "").replace("TY", "")
    if s.startswith("AY"):
        start = int(s[2:6]) - 1
        return f"{start}-{str(start + 1)[-2:]}"
    start = int(s[:4])
    return f"{start}-{str(start + 1)[-2:]}"
