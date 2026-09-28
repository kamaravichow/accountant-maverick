---
name: income-tax-computation
description: Compute income tax for individuals/HUFs/firms/companies, compare old vs new regime, and prepare a computation sheet for ITR.
---
# Income-tax computation

1. Collect heads of income from the workspace (Form 16, AIS/TIS, 26AS, capital gains statements, rent, business
   P&L). Reconcile with AIS first - AIS mismatches trigger 143(1)(a) adjustments.
2. Capital gains: one `calculate capital_gain` per transaction (or per scrip summary). Remember 23-Jul-2024 rate
   change (STCG 111A 15% -> 20%, LTCG 10% -> 12.5%, 112A exemption 1 lakh -> 1.25 lakh) - split FY 2024-25
   transactions by date.
3. Individuals/HUF: `calculate income_tax_individual` for the chosen regime, then `compare_tax_regimes`.
   - New regime (default; sec 115BAC / sec 202 ITA 2025): no 80C/80D/HRA/LTA/24(b) self-occupied; allows standard
     deduction Rs 75,000, 80CCD(2), family pension deduction. Rebate up to Rs 60,000 for income <= Rs 12 lakh with
     marginal relief; rebate not available against special-rate income.
   - Business income: switching back from the new regime is allowed only once (Form 10-IEA).
4. Firms/companies: `income_tax_entity` (115BAA 25.168% effective; MAT not applicable to 115BAA).
5. Interest: `interest_234a/234b/234c`. Rounding: income and tax to nearest Rs 10 (288A/288B).
6. Build the computation sheet in `07_Income_Tax/ITR/Computation_<AY>.xlsx` with `write_spreadsheet_table`
   (heads of income, deductions, tax, credits, payable) using formulas for the totals so the CA can tweak it.
7. List open questions (missing documents, judgement calls) at the end.
