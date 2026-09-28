"""Statutory compliance calendar (India). Dates are the *statutory* defaults - CBDT/CBIC extend
them frequently, so entries marked ``verify`` should be confirmed with a live search."""

from __future__ import annotations

import calendar as cal
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from . import rates as R


class CalendarInput(BaseModel):
    fy: str = "2025-26"
    month: int | None = Field(None, description="1-12 to filter to one calendar month; None for the whole FY")
    gst_filing: Literal["monthly", "qrmp", "composition", "none"] = "monthly"
    qrmp_state_category: Literal["X", "Y"] = Field("X", description="QRMP GSTR-3B: X states 22nd, Y states 24th")
    tax_audit: bool = False
    transfer_pricing: bool = False
    company: bool = False
    has_employees: bool = True
    tds_deductor: bool = True


def _q_end(month: int) -> bool:
    return month in (6, 9, 12, 3)


def compliance_calendar(inp: CalendarInput) -> dict:
    fy = R.fy_key(inp.fy)
    y0 = int(fy[:4])
    items: list[dict] = []

    def add(d: date, what: str, law: str, verify: bool = False):
        items.append({"due_date": d.isoformat(), "compliance": what, "law": law, "verify_extensions": verify})

    for i in range(12):
        m = (4 + i - 1) % 12 + 1
        y = y0 if m >= 4 else y0 + 1
        nm, ny = (m % 12) + 1, y + (1 if m == 12 else 0)  # following month
        label = f"{cal.month_abbr[m]}-{y}"
        if inp.tds_deductor:
            add(date(y + 1, 4, 30) if m == 3 else date(ny, nm, 7), f"TDS/TCS deposit for {label}", "Rule 30/37CA")
        if inp.has_employees:
            add(date(ny, nm, 15), f"PF ECR & ESI contribution for {label}", "EPF Scheme para 38 / ESI Reg. 31")
        if inp.gst_filing == "monthly":
            add(date(ny, nm, 11), f"GSTR-1 for {label}", "Sec 37 CGST")
            add(date(ny, nm, 20), f"GSTR-3B for {label}", "Sec 39 CGST")
        elif inp.gst_filing == "qrmp":
            if _q_end(m):
                add(date(ny, nm, 13), f"GSTR-1 (quarter ending {label})", "Sec 37 CGST (QRMP)")
                add(date(ny, nm, 22 if inp.qrmp_state_category == "X" else 24), f"GSTR-3B (quarter ending {label})",
                    "Sec 39 CGST (QRMP)")
            else:
                add(date(ny, nm, 13), f"IFF (optional) for {label}", "Rule 59 CGST")
                add(date(ny, nm, 25), f"PMT-06 tax payment for {label}", "Rule 61 CGST (QRMP)")
        elif inp.gst_filing == "composition" and _q_end(m):
            add(date(ny, nm, 18), f"CMP-08 (quarter ending {label})", "Rule 62 CGST")
    for md, pct_ in (((6, 15), 15), ((9, 15), 45), ((12, 15), 75), ((3, 15), 100)):
        d = date(y0 + (1 if md[0] <= 3 else 0), *md)
        add(d, f"Advance tax installment (cumulative {pct_}%)", "Sec 211 ITA 1961 / ITA 2025")
    if inp.tds_deductor:
        for q, d in (("Q1", date(y0, 7, 31)), ("Q2", date(y0, 10, 31)), ("Q3", date(y0 + 1, 1, 31)),
                     ("Q4", date(y0 + 1, 5, 31))):
            add(d, f"TDS returns 24Q/26Q/27Q for {q}", "Rule 31A", verify=True)
        add(date(y0 + 1, 6, 15), "Form 16 to employees", "Rule 31")
    ay = y0 + 1
    add(date(ay, 7, 31), "ITR - non-audit cases (individuals/HUF)", "Sec 139(1)", verify=True)
    if inp.tax_audit or inp.company:
        add(date(ay, 9, 30), "Tax audit report (Form 3CA/3CB-3CD)", "Sec 44AB", verify=True)
        add(date(ay, 10, 31), "ITR - audit cases / companies", "Sec 139(1)", verify=True)
    if inp.transfer_pricing:
        add(date(ay, 10, 31), "Form 3CEB (transfer pricing)", "Sec 92E", verify=True)
        add(date(ay, 11, 30), "ITR - transfer pricing cases", "Sec 139(1)", verify=True)
    add(date(ay, 12, 31), "Belated / revised ITR (last date)", "Sec 139(4)/(5)", verify=True)
    if inp.gst_filing in ("monthly", "qrmp"):
        add(date(ay, 12, 31), f"GSTR-9 / 9C annual return FY {fy}", "Sec 44 CGST", verify=True)
        add(date(ay, 11, 30), f"Last date to claim ITC / rectify FY {fy} invoices (or GSTR-9 date if earlier)",
            "Sec 16(4) / 37(3) / 39(9)")
    if inp.gst_filing == "composition":
        add(date(ay, 4, 30), f"GSTR-4 annual return FY {fy}", "Sec 39(2)")
    if inp.company:
        add(date(ay, 9, 30), "AGM (within 6 months of FY end)", "Sec 96 Companies Act")
        add(date(ay, 10, 30), "AOC-4 financial statements (30 days from AGM)", "Sec 137", verify=True)
        add(date(ay, 11, 29), "MGT-7/7A annual return (60 days from AGM)", "Sec 92", verify=True)
        add(date(ay, 9, 30), "DIR-3 KYC for directors", "Rule 12A", verify=True)
        add(date(ay, 6, 30), "DPT-3 return of deposits", "Rule 16A")
        add(date(ay, 4, 30), "MSME Form-1 (Oct-Mar half)", "MSMED sec 9 order")
        add(date(y0, 10, 31), "MSME Form-1 (Apr-Sep half)", "MSMED sec 9 order")
    items.sort(key=lambda x: x["due_date"])
    if inp.month:
        items = [i for i in items if int(i["due_date"][5:7]) == inp.month]
    return {"fy": fy, "count": len(items), "items": items,
            "note": "Statutory due dates; check CBDT/CBIC/MCA extensions for entries flagged verify_extensions. "
                    "State professional-tax and labour-welfare-fund dates are not included."}
