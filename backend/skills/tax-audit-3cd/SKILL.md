---
name: tax-audit-3cd
description: Gather data and prepare schedules for a tax audit report (Form 3CA/3CB-3CD) - applicability, key clauses and supporting workpapers.
---
# Tax audit (sec 44AB) support

1. Applicability: turnover > Rs 1 crore (Rs 10 crore if cash receipts and payments are each <= 5%); professionals
   gross receipts > Rs 50 lakh (Rs 75 lakh if cash <= 5%); 44AD/44ADA/44AE cases declaring lower profit with income
   above the basic exemption. Use `presumptive_income` to test.
2. Schedules to build (each as a sheet in `07_Income_Tax/Tax_Audit_3CD/3CD_Schedules_<FY>.xlsx`):
   - Cl. 18 depreciation: `it_block_depreciation` per block (180-day rule, additions with dates).
   - Cl. 21 disallowances: 40(a)(ia) TDS defaults (`disallowance_40a_ia`), 40A(3) cash payments > Rs 10,000/day,
     personal expenses, penalties.
   - Cl. 22 & 26: MSME 43B(h) (msme-43bh skill) and 43B statutory dues (PF/ESI paid after due date = employee
     contribution disallowed permanently - Checkmate Services SC 2022).
   - Cl. 34: TDS compliance - sections, amounts, deducted, deposited, late (from tds-compliance working).
   - Cl. 44: expenditure break-up: GST registered vs unregistered vs composition vs exempt - build from the purchase
     register (supplier GSTIN present/absent).
   - Cl. 31: loans/deposits accepted or repaid in cash (269SS/269T).
3. Due date: 30 Sep (verify extensions via `web_search`). Report is prepared, never filed.
