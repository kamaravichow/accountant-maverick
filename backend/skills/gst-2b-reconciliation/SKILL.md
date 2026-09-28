---
name: gst-2b-reconciliation
description: Monthly ITC reconciliation of the purchase register with GSTR-2B/IMS before filing GSTR-3B, with ITC eligibility and supplier follow-up.
---
# GSTR-2B vs books (ITC reconciliation)

## Inputs
- Purchase register for the month (books export or `02_Purchases/Purchase_Register.xlsx`).
- GSTR-2B JSON (preferred) or Excel for the same return period from `04_GST/GSTR-2B`.
If either is missing, request it (the 2B is generated on the 14th of the following month).

## Steps
1. `reconcile_gstr2b(books_path, gstr2b_path)` - writes the workpaper. Tolerance Rs 1 per invoice by default.
2. Explain the summary: ITC per books vs 2B, eligible ITC (matched), ITC at risk, unclaimed ITC in 2B.
3. Work each bucket:
   - **Matched with differences** - value/tax difference: check debit/credit notes and rounding; head mismatch
     (IGST vs CGST/SGST) = supplier's POS error -> revised invoice; date/invoice-no typos -> correct the books.
   - **Only in books** - do NOT claim this month (sec 16(2)(aa): ITC only if reflected in 2B; rule 36(4) no
     provisional credit). Chase supplier to file/correct GSTR-1; carry forward to next month's recon.
   - **Only in 2B** - either the bill is missing from books (chase client: `request_documents_from_client`), belongs to
     another month (timing), or isn't ours (reject in IMS / report to supplier).
   - **ITC unavailable (itcavl = N)** - POS in the supplier's state for inter-state, or sec 16(4) time-barred.
   - **RCM supplies** - pay tax in cash in 3B Table 3.1(d) before claiming in 4(A)(3).
4. Apply eligibility on top of matching: blocked credits sec 17(5), rule 37 (supplier unpaid > 180 days - check with
   `calculate rule37_reversal`), rule 42/43 reversals for exempt supplies, sec 16(4) time limit (`itc_time_limit`).
5. IMS (Invoice Management System): invoices are accepted/rejected/kept pending on the portal before the 2B is
   finalised. Advise which only-in-2B entries to *reject* (not ours / wrong) and which to keep *pending* (goods not yet
   received - sec 16(2)(b)).
6. Produce the 3B Table 4 figures: 4(A) ITC available (as per 2B, eligible), 4(B)(1) reversals (rules 38/42/43, 17(5)),
   4(B)(2) reversals that can be reclaimed (rule 37, 16(2)(b)), 4(D) ineligible. Put them in the workpaper's
   Summary sheet with `set_spreadsheet_cells` using formulas referencing the buckets.
7. Draft supplier follow-ups for ITC at risk (grouped by supplier, with invoice list) and save to `11_Correspondence`.
8. `remember` chronic defaulters ("Supplier X files GSTR-1 late - check 2B of next month").

## Interest risk
If ITC was already claimed wrongly and utilised, compute interest with `calculate gst_interest` kind "50(3)".
