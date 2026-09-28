---
name: tds-compliance
description: Monthly/quarterly TDS compliance - identify payments liable to TDS, correct section/rate/threshold, deposit, returns, interest/fees, and 26AS reconciliation.
---
# TDS compliance

## Law map
Payments before 1-Apr-2026 follow the Income-tax Act 1961 (sec 192-194T); from 1-Apr-2026 the Income-tax Act 2025
consolidates TDS in sec 392 (salary) and sec 393 (tables for other payments), TCS in sec 394. Rates/thresholds were
largely carried over; confirm the table entry with `web_search` if a client asks for the new section code.

## Steps
1. Pull the expense/purchase ledger for the month. For each payee aggregate FY-to-date payments.
2. For each nature of payment use `calculate tds_calc` (section, amount, aggregate_in_fy_before, payee_type,
   pan_available). Key judgements:
   - Contract (194C) vs professional (194J 10%) vs technical (194J 2%) - look at the invoice description.
   - Rent: land/building 10%, plant/machinery 2%, threshold Rs 50,000 per month.
   - 194Q (buyer turnover > 10 cr, purchases > 50 lakh from a seller) - TCS 206C(1H) was omitted from 1-Apr-2025.
   - 194T partners' remuneration/interest (from 1-Apr-2025).
   - Deduct on GST-exclusive amount when GST is shown separately (CBDT Circular 23/2017).
   - No/inoperative PAN -> 206AA higher rate. 206AB (non-filers) was omitted from 1-Apr-2025.
3. Deposit by the 7th of next month (30 April for March). Late: `tds_interest_201` (1%/1.5% per month, calendar
   months as per TRACES).
4. Quarterly returns 24Q/26Q/27Q (due 31 Jul/31 Oct/31 Jan/31 May): late fee `late_fee_234e` (Rs 200/day capped);
   issue Form 16A within 15 days of the return due date.
5. Non-deduction risk: `disallowance_40a_ia` (30% of the expense) until paid.
6. Receivables side: `reconcile_tds_26as` quarterly; chase deductors with missing credits.
7. Output: a TDS working (payee, PAN, section, amount, rate, TDS, challan) in `05_TDS_TCS/` and a summary.
