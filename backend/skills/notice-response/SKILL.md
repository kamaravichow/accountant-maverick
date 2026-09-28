---
name: notice-response
description: Triage GST and income-tax notices (ASMT-10, DRC-01/01A, sec 61/73/74, 143(1), 139(9), 148A, AIS mismatch) and draft a reasoned reply with annexures.
---
# Responding to notices

1. Read the notice (`read_file`) and extract: authority, section, period, demand/discrepancy, **reply due date**,
   hearing date, DIN (income-tax notices without DIN are invalid - CBDT Circular 19/2019).
2. Identify the discrepancy type and gather evidence from the workspace:
   - GSTR-1 vs 3B liability difference, GSTR-2B vs 3B ITC excess (DRC-01C), e-way bill vs return, 17(5) credits.
   - 143(1)(a) adjustments: AIS income not reported, TDS credit mismatch (`reconcile_tds_26as`), 43B/40(a)(ia).
3. Quantify with preset formulas (tax, `gst_interest`, `interest_234*`) and reconciliations; distinguish what is
   accepted (pay via DRC-03 / challan) vs contested.
4. For law points, search primary sources and recent case law (`web_search`, `web_fetch`) and cite them;
   note limitation periods (GST sec 73: order within 3 years of the annual-return due date, SCN at least 3 months
   earlier; sec 74 (fraud): 5 years / 6 months; for FY 2024-25 onwards sec 74A: SCN within 42 months, order within
   12 months of the SCN - verify current text).
5. Draft the reply in `<FY>/04_GST/Notices` or `07_Income_Tax`: facts, point-wise response, reconciliation annexure
   (Excel), legal submissions, prayer. Mark it DRAFT for CA review; list documents the client must sign/provide.
