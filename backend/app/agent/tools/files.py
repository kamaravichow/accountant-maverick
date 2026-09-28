"""Workspace tools: browse, read, write, organise company files; maintain client memory."""

from __future__ import annotations

from datetime import datetime, timezone

from langchain.tools import ToolRuntime, tool

from ...extraction.documents import read_document
from ...storage import NotFound, StorageError, clean_path
from ...workspace import CONTEXT, CompanyProfile, get_workspace
from ..context import AgentContext, company_storage, dump
from ..llm import get_model

Rt = ToolRuntime[AgentContext]


@tool
def list_files(runtime: Rt, path: str = "", recursive: bool = False) -> str:
    """List files and folders in the active company's workspace.

    Args:
        path: Folder relative to the company root, e.g. "FY2025-26/02_Purchases/Bills" or "_inbox". Empty = root.
        recursive: List everything below the folder (use for small folders only).
    """
    cs = company_storage(runtime.context)
    entries = cs.list(path, recursive=recursive)
    return dump([{"path": e.path, "dir": e.is_dir, "size": e.size} if not e.is_dir else {"path": e.path + "/", "dir": True}
                 for e in entries[:500]] + ([{"note": f"{len(entries) - 500} more not shown"}] if len(entries) > 500 else []))


@tool
def read_file(runtime: Rt, path: str, max_chars: int = 30000) -> str:
    """Read any document as text: digital PDF (text layer), scanned PDF or photo (vision OCR transcription),
    spreadsheet (first rows as TSV), or plain text/JSON/email. For structured invoice data use
    extract_invoice instead; for spreadsheets with formulas use read_spreadsheet.

    Args:
        path: File path relative to the company root.
        max_chars: Truncate output to this many characters.
    """
    cs = company_storage(runtime.context)
    data = cs.read_bytes(path)
    doc = read_document(data, path)
    header = f"[{doc.kind}, {doc.pages} page(s)] " + " ".join(doc.notes)
    if doc.kind in ("scanned_pdf", "image") and doc.images:
        from langchain_core.messages import HumanMessage, SystemMessage

        content = [{"type": "text", "text": "Transcribe this document faithfully as markdown. Keep tables as markdown "
                                            "tables, keep every number exactly, mark unreadable parts as [illegible]."}]
        content += [{"type": "image", "base64": b64, "mime_type": mime} for mime, b64 in doc.images]
        msg = get_model(vision=True, override=runtime.context.llm).invoke([SystemMessage("You are a meticulous OCR engine for Indian financial documents."),
                                             HumanMessage(content=content)])
        text = msg.content if isinstance(msg.content, str) else "".join(
            b.get("text", "") for b in msg.content if isinstance(b, dict))
        return header + "\n" + text[:max_chars]
    if doc.kind == "unsupported":
        return header
    return header + "\n" + doc.text[:max_chars] + ("\n...[truncated]" if len(doc.text) > max_chars else "")


@tool
def write_text_file(runtime: Rt, path: str, content: str) -> str:
    """Create or overwrite a text file (markdown notes, CSV, JSON, email drafts, memos) in the workspace.
    Put working papers under <FY>/12_Workpapers and client letters under <FY>/11_Correspondence.

    Args:
        path: Destination path relative to the company root, e.g. "FY2025-26/12_Workpapers/notes.md".
        content: Full file content.
    """
    cs = company_storage(runtime.context)
    p = clean_path(path)
    if p.startswith(f"{CONTEXT}/company.json"):
        return "Use update_company_profile to change the company profile."
    e = cs.write_text(p, content)
    return f"Saved {e.path} ({e.size} bytes)"


@tool
def move_file(runtime: Rt, source: str, destination: str) -> str:
    """Move or rename a file/folder (e.g. file an inbox document into the right FY folder with a clean name
    like "2025-10-05_ACME-TRADERS_INV-123.pdf"). Destination must include the file name.

    Args:
        source: Current path.
        destination: New path including file name.
    """
    cs = company_storage(runtime.context)
    if cs.exists(destination) and cs.is_file(destination):
        return f"Refused: {destination} already exists. Choose a different name."
    n = cs.move(source, destination)
    return f"Moved {n} object(s): {source} -> {destination}"


@tool
def create_folder(runtime: Rt, path: str) -> str:
    """Create a folder (e.g. a per-vendor or per-month sub-folder) in the company workspace."""
    company_storage(runtime.context).mkdir(path)
    return f"Created {path}/"


@tool
def get_company_profile(runtime: Rt) -> str:
    """Return the active company's structured profile (_context/company.json)."""
    return get_workspace().get_company(runtime.context.company_id).model_dump_json(indent=1)


@tool
def update_company_profile(runtime: Rt, updates: dict) -> str:
    """Update fields of the company profile, e.g. {"gstins": ["27AAPFU0939F1ZV"], "tax_regime": "old",
    "msme_registered": true, "books_software": "Tally Prime"}. Only change facts the user confirmed."""
    ws = get_workspace()
    prof = ws.get_company(runtime.context.company_id)
    data = prof.model_dump()
    bad = [k for k in updates if k not in data or k in ("id", "created_at")]
    if bad:
        return f"Unknown/immutable fields: {bad}. Valid: {sorted(k for k in data if k not in ('id', 'created_at'))}"
    data.update(updates)
    ws.save_company(CompanyProfile(**data))
    return f"Updated: {', '.join(updates)}"


@tool
def remember(runtime: Rt, fact: str, section: str = "General") -> str:
    """Append a durable fact about this client to _context/NOTES.md (long-term memory read at the start of every
    chat): accounting policies, recurring vendors and their HSN/TDS treatment, client preferences, open issues.
    Don't store transient data.

    Args:
        fact: One concise fact.
        section: Heading to file it under, e.g. "Vendors", "GST", "TDS", "Policies", "Open issues".
    """
    cs = company_storage(runtime.context)
    path = f"{CONTEXT}/NOTES.md"
    try:
        notes = cs.read_text(path)
    except (NotFound, StorageError):
        notes = "# Notes\n"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    heading = f"## {section}"
    line = f"- {fact} _(added {stamp})_"
    if heading in notes:
        head, _, tail = notes.partition(heading)
        nxt = tail.find("\n## ")
        notes = head + heading + (tail + "\n" + line if nxt == -1 else tail[:nxt] + "\n" + line + tail[nxt:])
    else:
        notes = notes.rstrip() + f"\n\n{heading}\n{line}\n"
    cs.write_text(path, notes)
    return "Saved to NOTES.md"


@tool
def search_files(runtime: Rt, query: str, folder: str = "") -> str:
    """Find files whose path/name contains all words of the query (case-insensitive), e.g. "acme 2025-10" or
    "26AS". Use to locate a vendor's bills or a specific statement."""
    cs = company_storage(runtime.context)
    words = [w.lower() for w in query.split()]
    hits = [e.path for e in cs.list(folder, recursive=True) if not e.is_dir and all(w in e.path.lower() for w in words)]
    return dump(hits[:200] or "No matching files")


FILE_TOOLS = [list_files, search_files, read_file, write_text_file, move_file, create_folder, get_company_profile,
              update_company_profile, remember]
