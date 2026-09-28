---
name: bank-reconciliation
description: Prepare a Bank Reconciliation Statement from the bank statement and bank ledger, and propose the missing book entries.
---
# Bank reconciliation

1. Get both files for the same account and period: statement (`03_Banking/Statements`) and bank ledger exported
   from Tally/Zoho (`08_Books_Ledgers`). Messy PDFs/Excel are fine - the loader cleans them - but if the result looks
   wrong run `clean_table` first and inspect the `_clean.xlsx`.
2. Ask for (or read) closing balances as per books and as per bank on the period end date.
3. `reconcile_bank(statement, ledger, book_balance, bank_balance)`.
4. Explain the BRS:
   - Cheques issued but not presented; deposits not yet credited (timing - normal if within ~7 days).
   - Bank debits not in books: charges (book with GST - banks charge 18% GST, ITC available if bank has our GSTIN),
     ECS/NACH EMIs (split principal/interest), TDS on cash withdrawal (194N), auto-sweeps.
   - Bank credits not in books: interest (TDS may appear in 26AS), NEFT/UPI receipts (identify customer; if unknown,
     ask client - unexplained credits are a sec 68 risk).
   - `unexplained_difference` must be 0; if not, look for duplicated entries, reversed signs, wrong period, or
     opening balance differences.
5. Draft journal/payment/receipt entries as a table (date, ledger, Dr, Cr, narration) in the workpaper.
6. Unidentified items -> `request_documents_from_client` asking for details.
7. Old unreconciled items (> 3 months): flag for write-back/cancellation of stale cheques.
