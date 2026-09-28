"""REST API: companies, files (streamed via S3/local), formulas, skills, document requests."""

from __future__ import annotations

import json
import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from ..agent.skills import all_skills
from ..config import get_settings
from ..formulas import FORMULAS, catalog, run_formula
from ..storage import NotFound, StorageError, clean_path, join
from ..workspace import CONTEXT, CompanyProfile, current_fy, get_workspace

router = APIRouter()


def _cs(company_id: str):
    try:
        ws = get_workspace()
        ws.get_company(company_id)
        return ws.company_storage(company_id)
    except (NotFound, ValueError):
        raise HTTPException(404, "Company not found")


# ------------------------------------------------------------------ companies

@router.get("/companies")
def list_companies():
    return [c.model_dump() for c in get_workspace().list_companies()]


class CreateCompany(CompanyProfile):
    fy: str | None = None


@router.post("/companies")
def create_company(body: CreateCompany):
    data = body.model_dump(exclude={"fy", "id", "created_at"})
    prof = get_workspace().create_company(CompanyProfile(**data), fy=body.fy or current_fy())
    return prof.model_dump()


@router.get("/companies/{company_id}")
def get_company(company_id: str):
    _cs(company_id)
    return get_workspace().get_company(company_id).model_dump()


@router.put("/companies/{company_id}")
def update_company(company_id: str, body: dict):
    ws = get_workspace()
    _cs(company_id)
    data = ws.get_company(company_id).model_dump()
    data.update({k: v for k, v in body.items() if k not in ("id", "created_at")})
    try:
        return ws.save_company(CompanyProfile(**data)).model_dump()
    except ValidationError as exc:
        raise HTTPException(422, exc.errors())


@router.delete("/companies/{company_id}")
def delete_company(company_id: str):
    _cs(company_id)
    return {"deleted_objects": get_workspace().delete_company(company_id)}


class FYBody(BaseModel):
    fy: str


@router.post("/companies/{company_id}/fy")
def add_fy(company_id: str, body: FYBody):
    _cs(company_id)
    try:
        return {"created": get_workspace().add_financial_year(company_id, body.fy)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ------------------------------------------------------------------ files

@router.get("/companies/{company_id}/files")
def list_files(company_id: str, path: str = "", recursive: bool = False):
    cs = _cs(company_id)
    return [e.to_dict() for e in cs.list(path, recursive=recursive)]


@router.post("/companies/{company_id}/files/upload")
async def upload(company_id: str, folder: str = Form(""), files: list[UploadFile] = File(...)):
    cs = _cs(company_id)
    limit = get_settings().max_upload_mb * 1024 * 1024
    saved = []
    for f in files:
        data = await f.read()
        if len(data) > limit:
            raise HTTPException(413, f"{f.filename} exceeds {get_settings().max_upload_mb} MB - use presigned upload")
        name = clean_path(f.filename or "upload.bin").split("/")[-1]
        target = join(folder or "_inbox", name)
        if cs.exists(target):
            stem, _, ext = name.rpartition(".")
            n = 2
            while cs.exists(target):
                target = join(folder or "_inbox", f"{stem or name}_{n}{'.' + ext if stem else ''}")
                n += 1
        saved.append(cs.write_bytes(target, data, f.content_type).to_dict())
    return {"saved": saved}


class PresignBody(BaseModel):
    path: str
    content_type: str | None = None


@router.post("/companies/{company_id}/files/presign-upload")
def presign_upload(company_id: str, body: PresignBody):
    """Direct browser -> S3 upload for large files (returns null url on local storage)."""
    cs = _cs(company_id)
    return {"url": cs.presigned_put(body.path, body.content_type), "path": clean_path(body.path)}


@router.get("/companies/{company_id}/files/download")
def download(company_id: str, path: str, inline: bool = True, redirect: bool = False):
    cs = _cs(company_id)
    try:
        entry = cs.stat(path)
    except NotFound:
        raise HTTPException(404, "File not found")
    if entry.is_dir:
        raise HTTPException(400, "Path is a folder")
    if redirect:
        url = cs.presigned_get(path, entry.name)
        if url:
            return RedirectResponse(url)
    media = entry.content_type or mimetypes.guess_type(entry.name)[0] or "application/octet-stream"
    disp = "inline" if inline else "attachment"
    return StreamingResponse(cs.iter_bytes(path), media_type=media, headers={
        "Content-Disposition": f"{disp}; filename*=UTF-8''{quote(entry.name)}",
        "Content-Length": str(entry.size), "Cache-Control": "no-store"})


@router.put("/companies/{company_id}/files/raw")
async def save_raw(company_id: str, path: str, request: Request):
    """Save raw bytes (used by the in-browser spreadsheet editor)."""
    cs = _cs(company_id)
    data = await request.body()
    p = clean_path(path)
    if p.startswith(f"{CONTEXT}/company.json"):
        raise HTTPException(400, "Use the company API")
    return cs.write_bytes(p, data, request.headers.get("content-type")).to_dict()


class MkdirBody(BaseModel):
    path: str


@router.post("/companies/{company_id}/files/mkdir")
def mkdir(company_id: str, body: MkdirBody):
    _cs(company_id).mkdir(body.path)
    return {"ok": True}


class MoveBody(BaseModel):
    source: str
    destination: str


@router.post("/companies/{company_id}/files/move")
def move(company_id: str, body: MoveBody):
    cs = _cs(company_id)
    try:
        return {"moved": cs.move(body.source, body.destination)}
    except (NotFound, StorageError) as exc:
        raise HTTPException(400, str(exc))


@router.delete("/companies/{company_id}/files")
def delete(company_id: str, path: str = Query(...)):
    cs = _cs(company_id)
    if clean_path(path).startswith(CONTEXT):
        raise HTTPException(400, "The _context folder is managed by the app")
    try:
        return {"deleted": cs.delete(path)}
    except (NotFound, StorageError) as exc:
        raise HTTPException(400, str(exc))


@router.get("/companies/{company_id}/requests")
def document_requests(company_id: str):
    cs = _cs(company_id)
    try:
        return json.loads(cs.read_text(f"{CONTEXT}/requests.json"))
    except Exception:
        return []


# ------------------------------------------------------------------ formulas & skills

@router.get("/formulas")
def formulas():
    return catalog()


@router.get("/formulas/{name}")
def formula_schema(name: str):
    if name not in FORMULAS:
        raise HTTPException(404, "Unknown formula")
    f = FORMULAS[name]
    return {"name": name, "description": f.description, "category": f.category, "schema": f.schema()}


@router.post("/formulas/{name}")
def formula_run(name: str, args: dict):
    try:
        return run_formula(name, args)
    except KeyError:
        raise HTTPException(404, "Unknown formula")
    except ValidationError as exc:
        raise HTTPException(422, json.loads(exc.json()))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/skills")
def skills():
    return [{"name": s.name, "description": s.description, "source": s.source} for s in all_skills().values()]
