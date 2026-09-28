---
name: month-end-close
description: Orchestrate the monthly close for a client - collect documents, book, reconcile bank/GST/TDS, compute liabilities, and report status.
---
# Month-end close checklist

Use `write_todos` to track these steps for the month being closed:
1. **Collect**: `compliance_calendar` for the month (due dates); check folders for bank statements, sales/purchase
   bills, GSTR-2B, payroll inputs; chase gaps (missing-documents-chase).
2. **File & enter**: inbox-organizer, then invoice-data-entry for new bills and invoices.
3. **Bank**: bank-reconciliation for each account.
4. **GST**: hsn-correction on the sales register, gst-2b-reconciliation, then gst-return-preparation.
5. **TDS**: tds-compliance - liability for the month, deposit by the 7th.
6. **Payroll**: `epf_contributions`, `esi_contributions` per employee (or aggregate) - deposit by the 15th.
7. **Review**: list items for CA review (blocked credits, unexplained credits, HSN/rate changes, 43B(h) risks).
8. **Report**: a one-page status in `12_Workpapers/Month_Close_<YYYY-MM>.md` - done, pending on client, liabilities
   with due dates, risks - and a short summary in chat.
