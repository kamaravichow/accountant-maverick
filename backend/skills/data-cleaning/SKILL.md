---
name: data-cleaning
description: Clean and standardise messy client data - Tally/Busy/Zoho exports, bank PDFs, Excel with merged headers, Indian number formats - into analysis-ready sheets.
---
# Data cleaning

1. `clean_table(path)` - it detects the header row, maps columns to standard names (date, narration, reference,
   debit, credit, amount, balance, gstin, party, invoice_no, taxable_value, igst/cgst/sgst/cess, hsn, rate...),
   parses Indian amounts ("1,23,456.00 Dr", "(500)"), day-first dates and Excel serials, merges wrapped narration
   lines, drops totals/opening balance rows and exact duplicates.
2. Read back the stats (`input`, `output`, `duplicates`, `unparsed_dates`) and a sample. Sanity checks:
   - Running balance continuity for statements (prev balance +/- amount = balance) - use `set_spreadsheet_cells`
     to add a check column with a formula and look for non-zero rows.
   - Debit/credit totals vs the source file's printed totals.
   - Dates within the expected period; no future dates.
3. Standardise masters: party names (strip "M/s", "Pvt Ltd" variants), GSTIN uppercase + `validate_ids`, HSN via
   `check_hsn`.
4. Never overwrite the original; save as `_clean.xlsx` beside it or in `12_Workpapers`.
5. For Tally import, produce columns in the order the user's import template expects (ask for it once and
   `remember` it).
