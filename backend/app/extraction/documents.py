"""Reading documents of any quality: digital PDFs, scanned PDFs, phone photos, spreadsheets, text.

Scanned or photographed documents are rendered to images and read by a vision-capable LLM,
which copes far better than classic OCR with skew, stamps, handwriting and poor contrast.
"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage

from .schema import Invoice

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")
MIN_CHARS_PER_PAGE = 40  # below this a PDF page is treated as scanned
MAX_VISION_PAGES = 6


@dataclass
class DocContent:
    kind: str  # text_pdf | scanned_pdf | image | spreadsheet | text | unsupported
    text: str = ""
    pages: int = 0
    images: list[tuple[str, str]] = field(default_factory=list)  # (mime, base64)
    notes: list[str] = field(default_factory=list)


def _render_pdf_pages(data: bytes, max_pages: int = MAX_VISION_PAGES, scale: float = 2.0) -> list[tuple[str, str]]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    out = []
    for i in range(min(len(pdf), max_pages)):
        img = pdf[i].render(scale=scale, grayscale=True).to_pil()
        # keep payload modest: long edge ~2000px
        img.thumbnail((2000, 2000))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        out.append(("image/png", base64.b64encode(buf.getvalue()).decode()))
    return out


def read_document(data: bytes, filename: str, with_images: bool = True) -> DocContent:
    name = filename.lower()
    if name.endswith(".pdf"):
        import pdfplumber

        texts = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            n = len(pdf.pages)
            for p in pdf.pages:
                texts.append(p.extract_text(layout=True) or "")
        text = "\n\n--- page break ---\n\n".join(texts)
        scanned_pages = sum(1 for t in texts if len(t.strip()) < MIN_CHARS_PER_PAGE)
        if n and scanned_pages >= max(1, n // 2):
            doc = DocContent("scanned_pdf", text, n)
            doc.notes.append(f"{scanned_pages}/{n} pages have no text layer - scanned document, using vision OCR")
            if with_images:
                doc.images = _render_pdf_pages(data)
            if n > MAX_VISION_PAGES:
                doc.notes.append(f"Only first {MAX_VISION_PAGES} pages rendered for vision")
            return doc
        return DocContent("text_pdf", text, n)
    if name.endswith(IMAGE_EXT):
        mime = "image/jpeg" if name.endswith((".jpg", ".jpeg")) else f"image/{name.rsplit('.', 1)[-1]}"
        return DocContent("image", "", 1, [(mime, base64.b64encode(data).decode())] if with_images else [])
    if name.endswith((".xlsx", ".xlsm", ".csv")):
        from ..recon.normalize import read_table_bytes

        rows = read_table_bytes(data, filename)
        lines = ["\t".join("" if c is None else str(c) for c in r) for r in rows[:400]]
        doc = DocContent("spreadsheet", "\n".join(lines), 1)
        if len(rows) > 400:
            doc.notes.append(f"Showing first 400 of {len(rows)} rows")
        return doc
    if name.endswith((".txt", ".md", ".json", ".xml", ".html", ".htm", ".eml")):
        return DocContent("text", data.decode("utf-8", errors="replace"), 1)
    return DocContent("unsupported", "", 0, notes=[f"Unsupported file type: {filename}"])


EXTRACT_SYSTEM = """You are an expert Indian GST invoice data-entry operator.
Extract the document into the given schema exactly as printed.
Rules:
- Never invent or compute values that are not printed; use null. Put unreadable-but-present fields in illegible_fields.
- Dates -> YYYY-MM-DD; Indian documents are DAY-FIRST (05/04/2025 = 5 April 2025).
- Amounts are plain numbers without commas (1,23,456.50 -> 123456.5).
- GSTIN is 15 characters; PAN is 10. Copy them character by character (O vs 0, I vs 1, S vs 5, B vs 8 are common OCR slips).
- HSN/SAC: copy digits only. gst_rate is the TOTAL rate (CGST 9% + SGST 9% = 18).
- place_of_supply_code: 2-digit state code if printed, else derive from the state name.
- supplier = the party issuing the document; buyer = bill-to party.
- extraction_confidence: high (clean digital), medium, low (poor scan / handwritten / cut off)."""


def extract_invoice(doc: DocContent, model, hint: str | None = None) -> Invoice:
    """Run structured extraction with a LangChain chat model (vision-capable for scans)."""
    content: list[dict] = [{"type": "text", "text": f"Document kind: {doc.kind}, pages: {doc.pages}." +
                            (f"\nContext: {hint}" if hint else "")}]
    if doc.text.strip():
        content.append({"type": "text", "text": "Extracted text layer:\n" + doc.text[:60000]})
    for mime, b64 in doc.images:
        content.append({"type": "image", "base64": b64, "mime_type": mime})
    structured = model.with_structured_output(Invoice)
    result = structured.invoke([SystemMessage(EXTRACT_SYSTEM), HumanMessage(content=content)])
    if isinstance(result, dict):
        result = Invoice.model_validate(result)
    result.page_count = result.page_count or doc.pages
    return result


CLASSIFY_SYSTEM = """Classify an Indian business document for filing. Reply with JSON only:
{"doc_type": one of [sales_invoice, purchase_bill, credit_note, debit_note, expense_receipt, bank_statement,
 gstr_2b, gstr_1, gstr_3b, gst_notice, tds_certificate_16_16a, form_26as_ais, tds_challan, salary_payroll,
 ledger_export, trial_balance, fixed_asset, itr_or_computation, kyc_registration, agreement, roc_mca,
 correspondence, other],
 "financial_year": "FY2025-26" or null, "party": str|null, "period": str|null, "doc_date": "YYYY-MM-DD"|null,
 "suggested_name": short filename without extension like "2025-10-05_ACME_INV-123", "confidence": 0-1}
A document is a sales_invoice if the supplier GSTIN/name is our company; purchase_bill if the buyer is our company."""


def classify_document(doc: DocContent, model, company_name: str, company_gstins: list[str]) -> dict:
    content: list[dict] = [{"type": "text", "text": f"Our company: {company_name}; GSTINs: {', '.join(company_gstins) or 'n/a'}"}]
    if doc.text.strip():
        content.append({"type": "text", "text": doc.text[:12000]})
    for mime, b64 in doc.images[:2]:
        content.append({"type": "image", "base64": b64, "mime_type": mime})
    msg = model.invoke([SystemMessage(CLASSIFY_SYSTEM), HumanMessage(content=content)])
    text = msg.content if isinstance(msg.content, str) else "".join(
        b.get("text", "") for b in msg.content if isinstance(b, dict))
    start, end = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return {"doc_type": "other", "confidence": 0, "raw": text[:500]}


DOC_TYPE_FOLDER = {
    "sales_invoice": "01_Sales/Invoices",
    "credit_note": "01_Sales/Credit_Notes",
    "purchase_bill": "02_Purchases/Bills",
    "debit_note": "02_Purchases/Debit_Notes",
    "expense_receipt": "02_Purchases/Expenses_Reimbursements",
    "bank_statement": "03_Banking/Statements",
    "gstr_2b": "04_GST/GSTR-2B",
    "gstr_1": "04_GST/GSTR-1",
    "gstr_3b": "04_GST/GSTR-3B",
    "gst_notice": "04_GST/Notices",
    "tds_challan": "05_TDS_TCS/Challans",
    "tds_certificate_16_16a": "05_TDS_TCS/Form16_16A",
    "form_26as_ais": "05_TDS_TCS/26AS_AIS_TIS",
    "salary_payroll": "06_Payroll",
    "itr_or_computation": "07_Income_Tax/ITR",
    "ledger_export": "08_Books_Ledgers",
    "trial_balance": "08_Books_Ledgers",
    "fixed_asset": "09_Fixed_Assets",
    "roc_mca": "10_ROC_MCA",
    "correspondence": "11_Correspondence",
    "kyc_registration": "@Permanent/KYC_PAN_Aadhaar",
    "agreement": "@Permanent/Agreements_Leases",
}
