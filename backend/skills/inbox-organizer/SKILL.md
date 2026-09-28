---
name: inbox-organizer
description: Classify, rename and file unsorted client uploads from _inbox into the standard FY folder structure.
---
# Inbox organiser

1. `classify_inbox(apply=false)` and show the proposed plan as a table: file -> type, party, destination.
2. Resolve doubts before moving:
   - A document is a **sales invoice** only if the *supplier* is this company (check GSTIN in the company profile).
   - Bank statements: name `BANKNAME_last4_YYYY-MM.pdf`; one file per account per period.
   - GSTR-2B downloads (JSON/Excel) go to `04_GST/GSTR-2B`, named `GSTR2B_YYYY-MM.json`.
   - Zip files/password-protected PDFs: ask the user for the password (common: PAN in caps / DOB DDMMYYYY).
3. With the user's go-ahead (or if they asked you to just file), `classify_inbox(apply=true)`. Low-confidence items stay
   in `_inbox` - list them for the user.
4. After filing, suggest the next action per type (e.g. purchase bills -> invoice-data-entry; 2B -> gst-2b-reconciliation;
   statements -> bank-reconciliation).
5. If a new FY folder was created, mention it. Use `remember` for recurring patterns (e.g. "Client sends HDFC
   statements as Excel on the 5th").
