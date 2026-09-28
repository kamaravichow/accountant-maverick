import io
import json

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from openpyxl import Workbook

from tests.fake_llm import ScriptedModel


def _client(workspace, script):
    from app.agent.harness import build_agent
    from app.main import create_app

    app = create_app()
    client = TestClient(app)
    client.__enter__()  # run lifespan (agent disabled without a real LLM key is fine)
    model = ScriptedModel(script=script)
    app.state.agent = build_agent(checkpointer=InMemorySaver(), model=model)
    return client, model


def _events(resp_text):
    out = []
    ev = None
    for line in resp_text.splitlines():
        if line.startswith("event:"):
            ev = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and ev:
            out.append((ev, json.loads(line.split(":", 1)[1].strip())))
    return out


def test_company_files_and_formula_api(workspace):
    client, _ = _client(workspace, [AIMessage("hi")])
    r = client.post("/api/companies", json={"name": "Acme Traders", "gstins": ["27AAPFU0939F1ZV"], "fy": "FY2025-26"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    tree = client.get(f"/api/companies/{cid}/files", params={"path": "FY2025-26"}).json()
    assert any(e["name"] == "04_GST" for e in tree)
    up = client.post(f"/api/companies/{cid}/files/upload", data={"folder": "_inbox"},
                     files=[("files", ("bill.txt", b"hello", "text/plain"))])
    assert up.status_code == 200
    dl = client.get(f"/api/companies/{cid}/files/download", params={"path": "_inbox/bill.txt"})
    assert dl.content == b"hello"
    mv = client.post(f"/api/companies/{cid}/files/move",
                     json={"source": "_inbox/bill.txt", "destination": "FY2025-26/02_Purchases/Bills/bill.txt"})
    assert mv.json()["moved"] == 1
    f = client.post("/api/formulas/gst_split", json={"taxable_value": 100, "rate": 18, "supplier_state": "27",
                                                     "place_of_supply": "29"})
    assert f.json()["igst"] == 18
    assert any(s["name"] == "gst-2b-reconciliation" for s in client.get("/api/skills").json())


def test_agent_tool_loop_over_sse(workspace):
    script = [
        AIMessage("", tool_calls=[{"id": "t1", "name": "load_skill", "args": {"name": "tds-compliance"}}]),
        AIMessage("", tool_calls=[{"id": "t2", "name": "calculate", "args": {
            "formula": "tds_calc", "inputs": {"section": "194J_professional", "amount": 60000}}}]),
        AIMessage("", tool_calls=[{"id": "t3", "name": "set_spreadsheet_cells", "args": {
            "path": "FY2025-26/12_Workpapers/tds.xlsx", "sheet": "TDS",
            "cells": {"A1": "Fee", "B1": 60000, "B2": "=B1*10%"}}}]),
        AIMessage("TDS is Rs 6,000 under sec 194J."),
    ]
    client, model = _client(workspace, script)
    cid = client.post("/api/companies", json={"name": "Beta LLP", "fy": "FY2025-26"}).json()["id"]
    r = client.post(f"/api/companies/{cid}/chat", json={"message": "TDS on 60k professional fee?", "fy": "FY2025-26"})
    evs = _events(r.text)
    kinds = [e for e, _ in evs]
    assert "error" not in kinds, evs
    ends = {d["name"]: d["output"] for e, d in evs if e == "tool_end"}
    assert "# Skill: tds-compliance" in ends["load_skill"]
    assert '"tds": 6000.0' in ends["calculate"]
    assert '"B2": 6000' in ends["set_spreadsheet_cells"]
    assert kinds[-1] == "done"
    # system prompt carried company context + skill index
    sys_prompt = model.seen[0][0].text
    assert "Beta LLP" in sys_prompt and "gst-2b-reconciliation" in sys_prompt
    thread_id = evs[0][1]["thread_id"]
    hist = client.get(f"/api/companies/{cid}/threads/{thread_id}").json()
    assert hist["messages"][-1]["content"].startswith("TDS is Rs 6,000")
    assert client.get(f"/api/companies/{cid}/threads").json()[0]["id"] == thread_id


def test_reconcile_and_clean_tools(workspace):
    from app.agent.context import AgentContext
    from app.agent.tools.compliance import clean_table, reconcile_gstr2b
    from app.workspace import CompanyProfile

    prof = workspace.create_company(CompanyProfile(name="Gamma"), fy="FY2025-26")
    cs = workspace.company_storage(prof.id)
    wb = Workbook()
    ws = wb.active
    ws.append(["ABC PVT LTD - Purchase Register"])
    ws.append([])
    ws.append(["GSTIN of Supplier", "Invoice No", "Invoice Date", "Taxable Value", "CGST", "SGST"])
    ws.append(["27AAPFU0939F1ZV", "INV/25-26/001", "05/10/2025", "1,000.00", "90", "90"])
    buf = io.BytesIO()
    wb.save(buf)
    cs.write_bytes("FY2025-26/08_Books_Ledgers/purchases.xlsx", buf.getvalue())
    cs.write_text("FY2025-26/04_GST/GSTR-2B/2b.json", json.dumps({"data": {"docdata": {"b2b": [
        {"ctin": "27AAPFU0939F1ZV", "trdnm": "ACME", "inv": [{"inum": "INV-1", "dt": "05-10-2025", "val": 1180,
                                                               "items": [{"rt": 18, "txval": 1000, "cgst": 90, "sgst": 90}]}]}]}}}))

    class RT:
        context = AgentContext(company_id=prof.id, fy="FY2025-26")

    out = json.loads(reconcile_gstr2b.func(RT(), "FY2025-26/08_Books_Ledgers/purchases.xlsx",
                                           "FY2025-26/04_GST/GSTR-2B/2b.json"))
    assert out["summary"]["matched"] == 1
    assert cs.exists(out["workpaper"])
    cleaned = json.loads(clean_table.func(RT(), "FY2025-26/08_Books_Ledgers/purchases.xlsx"))
    assert cleaned["sample"][0]["taxable_value"] == 1000
