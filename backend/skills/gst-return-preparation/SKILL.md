---
name: gst-return-preparation
description: Prepare GSTR-1 and GSTR-3B working papers from the registers - outward supplies, credit notes, RCM, ITC tables, interest and late fees.
---
# GSTR-1 / GSTR-3B preparation

## GSTR-1 (due 11th; QRMP 13th)
1. Sales register for the period -> classify: B2B (with GSTIN), B2CL (inter-state B2C > Rs 1 lakh per invoice),
   B2CS, exports/SEZ (with/without payment), nil/exempt/non-GST, credit/debit notes (CDNR/CDNUR), advances.
2. E-invoices (IRN) auto-populate B2B/CDNR: reconcile the register with the e-invoice data and remove duplicates.
3. HSN summary Table 12 (B2B and B2C tabs): run hsn-correction checks first.
4. Document summary Table 13 (series, cancelled invoices).
5. Credit notes for a FY must be declared by 30 Nov following the FY end (sec 34(2)).

## GSTR-3B (due 20th; QRMP 22nd/24th)
1. 3.1(a) outward taxable = GSTR-1 totals (the auto-drafted 3B from GSTR-1 must match; explain differences).
2. 3.1(d) inward supplies liable to RCM - self-invoices, pay in cash.
3. Table 4 ITC from the gst-2b-reconciliation workpaper (eligible, reversals 4(B)(1)/(2), ineligible 4(D)).
4. Electronic credit ledger set-off order (sec 49/49A/49B, rule 88A): IGST credit first against IGST, then CGST and
   SGST in any order; CGST credit not against SGST and vice versa. Cash for RCM and interest/late fee.
5. Late filing: `gst_late_fee` and `gst_interest` (on net cash liability) - include in the working.
6. Rule 86B (1% cash payment) if taxable supplies > Rs 50 lakh in a month - check exceptions.
7. Output a return working in `04_GST/GSTR-3B/GSTR3B_Working_<YYYY-MM>.xlsx` with formulas, and a checklist of
   items for the CA to confirm before filing. Never file.
