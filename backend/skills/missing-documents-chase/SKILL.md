---
name: missing-documents-chase
description: Find which bills/documents are missing (bank payments without bills, 2B invoices not in books, pending statements) and chase the client with a tracked, consolidated request.
---
# Chasing clients for missing documents

1. Build the list from evidence, not guesses:
   - `find_missing_bills(bank_statement, purchase_register)` - payments without a bill.
   - `reconcile_gstr2b` -> "only in 2B" = bills the supplier reported but the client never gave us.
   - Month folders that are empty (`list_files`) - e.g. no bank statement for a month, no GSTR-2B.
   - Open items from `list_document_requests` (don't re-ask what's already requested - send a reminder instead).
2. Prioritise: ITC value at stake and due dates (GSTR-3B 20th; ITC lapses 30 Nov after FY end), then amount.
3. `request_documents_from_client(items, channel)` - one consolidated message per client, grouped by type, with
   amounts/dates so the client can find each document. Tone: polite first time; firm on 2nd reminder; state the
   consequence (ITC loss, interest) on the 3rd.
4. When documents arrive in `_inbox`, run inbox-organizer, then mark requests `received` with
   `update_document_request`.
5. For reminders, use `update_document_request(id, "reminded")` and draft a short follow-up referencing the
   original date.
