---
name: invoice-data-entry
description: Turn purchase/sales invoices (PDF, scans, phone photos) into validated register entries - replaces typing 50+ fields per invoice.
---
# Invoice data entry

## Steps
1. Locate the files (`list_files` on `<FY>/02_Purchases/Bills`, `01_Sales/Invoices` or `_inbox`). If they are still in
   `_inbox`, run the **inbox-organizer** skill first.
2. For 1-3 files use `extract_invoice_data`; for a folder use `batch_extract_invoices` (repeat until `remaining` = 0).
   Register: `purchase` for inward bills, `sales` for our invoices, `expense` for petty expenses/reimbursements.
3. Triage the results:
   - **ok** - nothing to do.
   - **review** - read the warnings; most common: missing IRN (supplier AATO > 5 cr must e-invoice), HSN rate
     mismatch, MSME supplier (43B(h) payment clock), illegible fields in scans.
   - **error** - arithmetic/tax-head/GSTIN checksum failures. Open the document (`read_file`) and confirm whether it is
     an extraction slip (fix the register row) or a genuine supplier error (needs a revised invoice / credit note).
4. For genuine supplier errors that block ITC (wrong GSTIN of ours, IGST charged intra-state, invalid GSTIN), add them
   to the chase list with `request_documents_from_client` (reason: "revised invoice needed").
5. Summarise: count processed, total taxable value and GST by head, list of items needing CA review, register path.

## Checks the validators run (explain them when flagged)
- Rule 46 particulars: invoice no. <= 16 chars, date, supplier GSTIN, recipient GSTIN (B2B), place of supply,
  HSN, taxable value, rate, tax amounts, signature.
- Intra-state (supplier state = POS) -> CGST+SGST; inter-state or SEZ/export -> IGST. Wrong head = ITC at risk
  (sec 77 CGST / sec 19 IGST: supplier must pay the right head and claim refund of the wrong one).
- Duplicate detection (same supplier GSTIN + normalised invoice no.) - never book twice.
- Scans: the model marks `illegible_fields`; never guess amounts - ask for a clearer copy.

## Accounting hints
- Capital goods vs expense: laptops/machinery > Rs 5,000 with multi-year use -> fixed asset (`09_Fixed_Assets`).
- Blocked credits sec 17(5): motor vehicles (<= 13 seats, unless for specified businesses), food & beverages,
  outdoor catering, club/health/fitness, life/health insurance, works contract for immovable property (except
  plant & machinery), personal consumption, goods lost/stolen/written off/free samples. Book tax as cost.
- Reverse charge (GTA 5%, legal services, security, rent from unregistered landlord, import of services): self-invoice
  within 30 days and pay RCM in cash before taking ITC.
