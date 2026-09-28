---
name: hsn-correction
description: Detect and fix HSN/SAC code mismatches and wrong GST rates in sales/purchase registers, including the 22-Sep-2025 GST 2.0 rate transition.
---
# HSN / rate mismatch correction

1. Run `audit_hsn_register(path)` on the register (or `check_hsn` for a single item).
2. Group findings:
   - **Format** - 3/5/7-digit codes (Excel dropped the leading zero -> fix: prefix 0), "8471.0" float artefacts,
     text like "NA". Fix in the master data, not only in the report.
   - **Digits for AATO** - AATO <= Rs 5 cr: 4 digits (B2B mandatory); > Rs 5 cr: 6 digits in GSTR-1 Table 12 and
     e-invoices (Notification 78/2020-CT). GSTR-1 Table 12 is split B2B/B2C and validated against a dropdown of HSNs.
   - **Rate vs HSN** - compare with the reference rate; the local table is only a starter list. For anything
     unusual or not in the table, confirm with `web_search` on cbic-gst.gov.in (rate notification 1/2017-CT(Rate)
     as amended; GST 2.0 changes via notifications of Sept 2025) and cite it.
   - **Rate transition (22-Sep-2025)** - time of supply rules (sec 14 CGST) decide old vs new rate when the invoice,
     payment and supply straddle the change date. Explain which rate applies with dates.
   - **Inconsistency** - same item under different HSNs or same HSN at different rates. Pick one code per item
     (store the decision with `remember` under "HSN master").
   - **Goods vs services** - SAC (99xxxx) for services; e.g. freight = 9965 (GTA), rent = 9972, repairs = 9987.
3. Impact assessment:
   - Sales at a lower rate than applicable -> short payment: tax + interest (`gst_interest`, 18%) via DRC-03;
     issue debit notes/supplementary invoices.
   - Sales at a higher rate -> excess collected: credit note (sec 34) by 30 Nov following FY end, or refund issues
     (unjust enrichment).
   - Purchases where supplier charged a wrong rate -> ITC only of tax actually payable; ask for revised invoice.
4. Output a correction sheet: row, current HSN/rate, proposed HSN/rate, reason, source URL, action. Save under
   `12_Workpapers/HSN_Corrections_<date>.xlsx` via `write_spreadsheet_table`.
5. Optionally create a client HSN master at `_context/hsn_master.json` (list of {code, desc, kw, pre, post, note})
   for recurring items.
