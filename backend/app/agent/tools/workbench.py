"""Spreadsheet, live web research, client document-chase, and skills tools."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

from langchain.tools import ToolRuntime, tool

from ... import spreadsheet as xl
from ...workspace import CONTEXT, get_workspace
from .. import web
from ..context import AgentContext, active_fy, company_storage, dump
from ..skills import all_skills

Rt = ToolRuntime[AgentContext]


# ------------------------------------------------------------------ spreadsheets

@tool
def read_spreadsheet(runtime: Rt, path: str, sheet: str | None = None, cell_range: str | None = None,
                     max_rows: int = 150) -> str:
    """Read an .xlsx: without sheet/range returns the sheet list; otherwise returns values for the range with
    formulas evaluated (and the formulas themselves), e.g. sheet="Computation", cell_range="A1:F40"."""
    cs = company_storage(runtime.context)
    data = cs.read_bytes(path)
    if sheet is None and cell_range is None:
        info = xl.describe(data)
        if len(info["sheets"]) > 1:
            return dump(info)
    return dump(xl.read_range(data, sheet, cell_range, max_rows))


@tool
def write_spreadsheet_table(runtime: Rt, path: str, sheet: str, headers: list[str], rows: list[list],
                            title: str | None = None, total_columns: list[str] | None = None) -> str:
    """Write a formatted table to a sheet (creates the workbook if needed; replaces the sheet if it exists).
    Cells may contain Excel formulas as strings starting with '=' (e.g. "=C5*18%"), so the accountant can audit
    them. total_columns adds a live =SUBTOTAL row. Save workpapers under <FY>/12_Workpapers/."""
    cs = company_storage(runtime.context)
    existing = cs.read_bytes(path) if cs.exists(path) else None
    cs.write_bytes(path, xl.write_table(existing, sheet, headers, rows, title=title, totals=total_columns))
    return f"Wrote {len(rows)} rows to {path} [{sheet}]. Open it in the Spreadsheet tab to review."


@tool
def set_spreadsheet_cells(runtime: Rt, path: str, sheet: str, cells: dict, number_format: str | None = None) -> str:
    """Set individual cells to values or formulas and get the recalculated results back. Use this to build
    computation sheets with live formulas, e.g. {"A1": "Taxable", "B1": 125000, "B2": "=B1*18%",
    "B3": "=ROUND(B1+B2,0)"}. number_format: "inr" (Indian lakh grouping), "0.00%", "dd-mm-yyyy" etc."""
    cs = company_storage(runtime.context)
    existing = cs.read_bytes(path) if cs.exists(path) else None
    data = xl.set_cells(existing, sheet, cells, number_format)
    cs.write_bytes(path, data)
    computed = xl.evaluate_workbook(data) if any(isinstance(v, str) and v.startswith("=") for v in cells.values()) else {}
    results = {ref: computed.get((sheet.upper(), ref.upper()), v) for ref, v in cells.items()}
    return dump({"saved": path, "sheet": sheet, "values": results})


# ------------------------------------------------------------------ live web (TinyFish)

@tool
async def web_search(query: str, trusted_sources_only: bool = True, recent_days: int | None = None) -> str:
    """Live web search (TinyFish) for current Indian tax law, notifications, circulars, rates, due-date
    extensions, portal advisories, case law, or a vendor's details. Prefer trusted government/professional
    sources. Cite URLs in your answer. Follow up with web_fetch to read the actual notification.

    Args:
        query: e.g. "CBIC notification GST rate HSN 8415 September 2025" or "CBDT extends ITR due date AY 2026-27".
        trusted_sources_only: Restrict to govt/ICAI/major tax portals.
        recent_days: Only results published within N days (for extensions/advisories).
    """
    try:
        res = await web.search(query, include_domains=web.TRUSTED_DOMAINS if trusted_sources_only else None,
                               recency_minutes=recent_days * 1440 if recent_days else None)
    except web.TinyFishError as exc:
        return f"Search unavailable: {exc}"
    results = res.get("results", [])
    if not results and trusted_sources_only:
        try:
            res = await web.search(query, recency_minutes=recent_days * 1440 if recent_days else None)
            results = res.get("results", [])
        except web.TinyFishError as exc:
            return f"Search unavailable: {exc}"
    return dump([{"title": r.get("title"), "url": r.get("url"), "site": r.get("site_name"), "date": r.get("date"),
                  "snippet": r.get("snippet")} for r in results[:10]])


@tool
async def web_fetch(urls: list[str], focus: str | None = None, max_chars_per_page: int = 12000) -> str:
    """Fetch and read up to 5 web pages (TinyFish renders them in a real browser and returns clean markdown).
    Pass `focus` (what you are looking for) to get the most relevant passages ranked first."""
    try:
        res = await web.fetch(urls[:5], highlights_query=focus)
    except web.TinyFishError as exc:
        return f"Fetch unavailable: {exc}"
    pages = []
    for r in res.get("results", []):
        page = {"url": r.get("final_url") or r.get("url"), "title": r.get("title"), "published": r.get("published_date")}
        if r.get("highlights"):
            page["highlights"] = [h.get("text") for h in r["highlights"]]
        page["text"] = (r.get("text") or "")[:max_chars_per_page]
        pages.append(page)
    return dump({"pages": pages, "errors": res.get("errors", [])}, limit=40000)


# ------------------------------------------------------------------ client document chase

REQ = f"{CONTEXT}/requests.json"


def _requests(cs) -> list[dict]:
    try:
        return json.loads(cs.read_text(REQ))
    except Exception:
        return []


@tool
def request_documents_from_client(runtime: Rt, items: list[dict], channel: str = "email",
                                  tone: str = "polite") -> str:
    """Record missing documents in the chase tracker (_context/requests.json) and draft a consolidated message to
    the client (email or WhatsApp) saved under <FY>/11_Correspondence. Each item: {"document": "Purchase bill from
    Sharma Traders for Rs 25,000 paid on 01-May-2025", "reason": "needed to claim ITC / support expense",
    "due_date": "2025-10-15" (optional), "priority": "high|normal"}. The message is a draft - it is not sent."""
    ctx = runtime.context
    cs = company_storage(ctx)
    prof = get_workspace().get_company(ctx.company_id)
    reqs = _requests(cs)
    now = datetime.now(timezone.utc).isoformat()
    new = []
    for it in items:
        r = {"id": uuid.uuid4().hex[:8], "document": it.get("document"), "reason": it.get("reason"),
             "due_date": it.get("due_date"), "priority": it.get("priority", "normal"), "status": "requested",
             "requested_at": now, "reminders": 0}
        reqs.append(r)
        new.append(r)
    cs.write_text(REQ, json.dumps(reqs, indent=1))
    greet = f"Dear {prof.contact_name or 'Sir/Madam'},"
    lines = [f"{i}. {r['document']}" + (f" - {r['reason']}" if r.get("reason") else "") +
             (f" (by {r['due_date']})" if r.get("due_date") else "") for i, r in enumerate(new, 1)]
    if channel == "whatsapp":
        body = f"Hi {prof.contact_name or ''}, for {prof.name}'s books/GST we still need:\n" + "\n".join(lines) + \
               "\nPlease share clear PDFs/photos (all pages). Thank you!"
    else:
        body = (f"Subject: Pending documents - {prof.name}\n\n{greet}\n\n"
                f"To complete the accounting and GST/TDS compliance for {prof.name}, we need the following:\n\n"
                + "\n".join(lines) +
                "\n\nPlease share clear scans or PDFs (all pages, with GSTIN and invoice number visible). Where a bill is not "
                "available, a short note on the nature of the payment will help us classify it correctly."
                + ("\n\nSome of these affect input tax credit, which lapses if not claimed in time." if tone != "urgent"
                   else "\n\nThese are urgent: input tax credit / due dates are at risk.")
                + "\n\nRegards")
    path = f"{active_fy(ctx)}/11_Correspondence/document_request_{date.today():%Y%m%d}_{channel}.txt"
    cs.write_text(path, body)
    return dump({"tracked": len(new), "draft_saved": path, "to": prof.contact_email or prof.contact_phone, "draft": body})


@tool
def list_document_requests(runtime: Rt, status: str | None = "requested") -> str:
    """List tracked document requests (status: requested | received | cancelled | null for all), with age in days."""
    cs = company_storage(runtime.context)
    today = date.today()
    out = []
    for r in _requests(cs):
        if status and r.get("status") != status:
            continue
        age = (today - date.fromisoformat(r["requested_at"][:10])).days
        out.append({**r, "age_days": age, "overdue": bool(r.get("due_date") and r["due_date"] < today.isoformat())})
    return dump(out or "No requests")


@tool
def update_document_request(runtime: Rt, request_id: str, status: str, note: str | None = None) -> str:
    """Mark a tracked request as received/cancelled (or bump reminders with status='reminded')."""
    cs = company_storage(runtime.context)
    reqs = _requests(cs)
    for r in reqs:
        if r["id"] == request_id:
            if status == "reminded":
                r["reminders"] = r.get("reminders", 0) + 1
                r["last_reminder"] = datetime.now(timezone.utc).isoformat()
            else:
                r["status"] = status
                r["closed_at"] = datetime.now(timezone.utc).isoformat()
            if note:
                r["note"] = note
            cs.write_text(REQ, json.dumps(reqs, indent=1))
            return f"Request {request_id} -> {status}"
    return f"No request with id {request_id}"


# ------------------------------------------------------------------ skills

@tool
def load_skill(runtime: Rt, name: str) -> str:
    """Load the full playbook for a skill listed in the system prompt (e.g. "gst-2b-reconciliation"). Always load
    the matching skill before starting a multi-step compliance task and follow its steps and checks."""
    skills = all_skills(company_storage(runtime.context))
    if name not in skills:
        return f"No skill '{name}'. Available: {', '.join(skills)}"
    s = skills[name]
    return f"# Skill: {s.name}\n{s.body}"


WORKBENCH_TOOLS = [read_spreadsheet, write_spreadsheet_table, set_spreadsheet_cells, web_search, web_fetch,
                   request_documents_from_client, list_document_requests, update_document_request, load_skill]
