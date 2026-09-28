---
name: advance-tax-interest
description: Estimate advance tax installments and compute interest u/s 234A, 234B and 234C.
---
# Advance tax & interest

1. Estimate the year's tax (income-tax-computation skill) less expected TDS/TCS.
2. `calculate advance_tax_schedule` - 15/45/75/100% by 15 Jun/15 Sep/15 Dec/15 Mar; presumptive 44AD/44ADA pay 100%
   by 15 Mar. Not required if liability < Rs 10,000; resident senior citizens without business income are exempt.
3. After year end:
   - `interest_234c` with cumulative payments by each date (12%/36% safe harbour for the first two installments).
     Capital gains/dividend arising after an installment date - no 234C on tax on that income if paid in remaining
     installments (explain; the formula assumes the plain case).
   - `interest_234b` if advance tax < 90% of assessed tax; interest to the date of self-assessment payment.
   - `interest_234a` if the return is filed after the due date.
4. Present a table of installments, amounts paid, shortfall and interest, plus the self-assessment tax to pay
   (Challan 280 / e-Pay Tax, minor head 300).
