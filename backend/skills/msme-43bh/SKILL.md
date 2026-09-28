---
name: msme-43bh
description: Year-end review of payables to micro/small enterprises for sec 43B(h) disallowance, MSMED interest and Form 3CD/MSME-1 reporting.
---
# MSME payments - sec 43B(h)

1. Identify MSME suppliers: Udyam numbers on invoices (extraction captures `udyam_number`), vendor master, or ask the
   client to collect Udyam certificates. Only **micro and small** enterprises count; traders registered on Udyam
   are excluded for this purpose. Medium enterprises are outside 43B(h).
2. Build the payables list: vendor, invoice date, acceptance date, agreed credit days (max 45 with written
   agreement; 15 days without), amount, payment date (from bank statement).
3. `calculate msme_43bh` with the list and optionally the RBI bank rate (fetch with `web_search` "RBI bank rate").
4. Explain: unpaid/late amounts at FY end are disallowed this year and allowed in the year of payment; MSMED sec 16
   interest (3x bank rate, monthly compounding) is not deductible (sec 23 MSMED Act).
5. Report in Form 3CD (clause 22 and the 43B clause) and MSME Form-1 (companies, half-yearly, for dues > 45 days).
6. Save the schedule to `07_Income_Tax/Tax_Audit_3CD/MSME_43Bh_<FY>.xlsx`.
