"""Company workspaces: a standard folder layout + a `_context` folder the agent reads first.

Layout (per company)::

    _context/company.json   structured profile (PAN, GSTINs, FY, regime, ...)
    _context/NOTES.md       long-term memory the agent maintains (policies, quirks)
    _context/requests.json  documents requested from the client (chase tracker)
    _inbox/                 unsorted uploads - the agent classifies and files these
    Permanent/              KYC, registrations, deeds, MoA/AoA, agreements
    FY2025-26/01_Sales/...  one tree per financial year (see FY_TEMPLATE)
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone

from pydantic import BaseModel, Field

from .storage import ScopedStorage, Storage, get_storage, join

COMPANIES = "companies"
CONTEXT = "_context"
INBOX = "_inbox"

PERMANENT_TEMPLATE = [
    "Permanent/KYC_PAN_Aadhaar",
    "Permanent/Registrations_GST_TAN_MSME",
    "Permanent/Constitution_Deeds_MoA",
    "Permanent/Agreements_Leases",
    "Permanent/Bank_Accounts",
]

FY_TEMPLATE = [
    "01_Sales/Invoices",
    "01_Sales/Credit_Notes",
    "01_Sales/E-Invoice_EWay_Bills",
    "02_Purchases/Bills",
    "02_Purchases/Debit_Notes",
    "02_Purchases/Expenses_Reimbursements",
    "03_Banking/Statements",
    "03_Banking/Reconciliations",
    "04_GST/GSTR-1",
    "04_GST/GSTR-2B",
    "04_GST/GSTR-3B",
    "04_GST/GSTR-9_9C",
    "04_GST/Notices",
    "05_TDS_TCS/Challans",
    "05_TDS_TCS/Returns_24Q_26Q",
    "05_TDS_TCS/Form16_16A",
    "05_TDS_TCS/26AS_AIS_TIS",
    "06_Payroll",
    "07_Income_Tax/Advance_Tax",
    "07_Income_Tax/ITR",
    "07_Income_Tax/Tax_Audit_3CD",
    "08_Books_Ledgers",
    "09_Fixed_Assets",
    "10_ROC_MCA",
    "11_Correspondence",
    "12_Workpapers",
]

# What belongs where - shown to the agent so it can file documents consistently.
FOLDER_GUIDE = {
    "_inbox": "Unsorted uploads. Classify each file and move it into the right FY folder.",
    "01_Sales/Invoices": "Outward tax invoices / bills of supply issued by the company.",
    "02_Purchases/Bills": "Inward supplier invoices (needed to claim ITC u/s 16).",
    "03_Banking/Statements": "Bank statements (PDF/CSV/XLSX), one file per account per period.",
    "04_GST/GSTR-2B": "GSTR-2B JSON/Excel downloaded from the GST portal (auto-drafted ITC).",
    "05_TDS_TCS/26AS_AIS_TIS": "Form 26AS / AIS / TIS downloads for TDS credit reconciliation.",
    "08_Books_Ledgers": "Exports from Tally/Zoho/Busy: day book, ledgers, trial balance.",
    "12_Workpapers": "Agent + accountant outputs: reconciliations, computations, schedules.",
}


def current_fy(today: date | None = None) -> str:
    today = today or date.today()
    start = today.year if today.month >= 4 else today.year - 1
    return f"FY{start}-{str(start + 1)[-2:]}"


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return s[:40] or "company"


class CompanyProfile(BaseModel):
    id: str = ""
    name: str
    entity_type: str = Field(
        "company", description="individual | huf | firm | llp | company | trust | aop"
    )
    pan: str | None = None
    tan: str | None = None
    gstins: list[str] = Field(default_factory=list)
    state: str | None = None
    gst_filing: str = Field("monthly", description="monthly | qrmp | composition | none")
    tax_regime: str = Field("new", description="new (sec 115BAC / sec 202 of ITA 2025) | old")
    books_software: str | None = Field(None, description="Tally Prime, Zoho Books, Busy, ...")
    msme_registered: bool = False
    turnover_band: str | None = None
    tax_audit_applicable: bool | None = None
    financial_years: list[str] = Field(default_factory=list)
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    notes: str | None = None
    created_at: str | None = None


class Workspace:
    """Company registry backed by the configured storage."""

    def __init__(self, storage: Storage | None = None):
        self.storage = storage or get_storage()

    def company_storage(self, company_id: str) -> ScopedStorage:
        if not re.fullmatch(r"[a-z0-9-]{1,64}", company_id or ""):
            raise ValueError(f"Invalid company id: {company_id!r}")
        return ScopedStorage(self.storage, join(COMPANIES, company_id))

    def list_companies(self) -> list[CompanyProfile]:
        out = []
        for e in self.storage.list(COMPANIES):
            if e.is_dir:
                try:
                    out.append(self.get_company(e.name))
                except Exception:
                    continue
        return sorted(out, key=lambda c: c.name.lower())

    def get_company(self, company_id: str) -> CompanyProfile:
        cs = self.company_storage(company_id)
        data = json.loads(cs.read_text(f"{CONTEXT}/company.json"))
        return CompanyProfile(**data)

    def save_company(self, profile: CompanyProfile) -> CompanyProfile:
        cs = self.company_storage(profile.id)
        cs.write_text(
            f"{CONTEXT}/company.json", profile.model_dump_json(indent=2), "application/json"
        )
        return profile

    def create_company(self, profile: CompanyProfile, fy: str | None = None) -> CompanyProfile:
        profile.id = profile.id or f"{slugify(profile.name)}-{uuid.uuid4().hex[:6]}"
        profile.created_at = datetime.now(timezone.utc).isoformat()
        fy = fy or current_fy()
        if fy not in profile.financial_years:
            profile.financial_years.append(fy)
        cs = self.company_storage(profile.id)
        self.save_company(profile)
        cs.write_text(
            f"{CONTEXT}/NOTES.md",
            f"# {profile.name} - working notes\n\n"
            "Long-term memory for this client. The AI agent appends durable facts here\n"
            "(accounting policies, recurring vendors, HSN choices, client preferences).\n",
        )
        cs.write_text(f"{CONTEXT}/requests.json", "[]", "application/json")
        cs.mkdir(INBOX)
        for folder in PERMANENT_TEMPLATE:
            cs.mkdir(folder)
        self.add_financial_year(profile.id, fy)
        return profile

    def add_financial_year(self, company_id: str, fy: str) -> list[str]:
        if not re.fullmatch(r"FY\d{4}-\d{2}", fy):
            raise ValueError("FY must look like FY2025-26")
        cs = self.company_storage(company_id)
        created = []
        for folder in FY_TEMPLATE:
            cs.mkdir(f"{fy}/{folder}")
            created.append(f"{fy}/{folder}")
        profile = self.get_company(company_id)
        if fy not in profile.financial_years:
            profile.financial_years.append(fy)
            profile.financial_years.sort()
            self.save_company(profile)
        return created

    def delete_company(self, company_id: str) -> int:
        return self.storage.delete(join(COMPANIES, company_id))

    def context_summary(self, company_id: str) -> str:
        """Compact text block injected into the agent's system prompt."""
        cs = self.company_storage(company_id)
        p = self.get_company(company_id)
        try:
            notes = cs.read_text(f"{CONTEXT}/NOTES.md")
        except Exception:
            notes = ""
        try:
            open_requests = [
                r for r in json.loads(cs.read_text(f"{CONTEXT}/requests.json")) if r.get("status") != "received"
            ]
        except Exception:
            open_requests = []
        inbox = [e.name for e in cs.list(INBOX) if not e.is_dir]
        profile = p.model_dump(exclude_none=True, exclude={"created_at"})
        lines = [
            "## Active company profile (_context/company.json)",
            json.dumps(profile, indent=2),
            "",
            "## Folder layout",
            "_context/ (profile, NOTES.md memory, requests.json chase tracker), _inbox/ (unsorted), "
            "Permanent/, and one tree per FY: " + ", ".join(p.financial_years),
            "Each FY tree: " + ", ".join(FY_TEMPLATE),
            "Filing guide: " + "; ".join(f"{k} = {v}" for k, v in FOLDER_GUIDE.items()),
            "",
            f"## Inbox: {len(inbox)} unsorted file(s)" + (": " + ", ".join(inbox[:25]) if inbox else ""),
            f"## Open document requests to client: {len(open_requests)}",
        ]
        if notes.strip():
            lines += ["", "## NOTES.md (client memory)", notes[-4000:]]
        return "\n".join(lines)


_workspace: Workspace | None = None


def get_workspace() -> Workspace:
    global _workspace
    if _workspace is None:
        _workspace = Workspace()
    return _workspace
