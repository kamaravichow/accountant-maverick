import json

import boto3
import httpx
import pytest
from langchain_core.messages import AIMessage
from moto import mock_aws

from tests.fake_llm import ScriptedModel


@mock_aws
def test_s3_storage_roundtrip():
    from app.storage.base import ScopedStorage
    from app.storage.s3 import S3Storage

    client = boto3.client("s3", region_name="us-east-1")
    store = S3Storage("bucket", prefix="ws", client=client)
    store.ensure_bucket()
    cs = ScopedStorage(store, "companies/acme")
    cs.mkdir("FY2025-26/04_GST/GSTR-2B")
    cs.write_text("FY2025-26/04_GST/GSTR-2B/2b.json", "{}")
    cs.write_text("_inbox/a.pdf", "x")
    top = {e.name: e.is_dir for e in cs.list("")}
    assert top == {"FY2025-26": True, "_inbox": True}
    assert [e.name for e in cs.list("FY2025-26/04_GST/GSTR-2B")] == ["2b.json"]
    assert b"".join(cs.iter_bytes("_inbox/a.pdf")) == b"x"
    cs.move("_inbox/a.pdf", "FY2025-26/a.pdf")
    assert cs.exists("FY2025-26/a.pdf") and not cs.exists("_inbox/a.pdf")
    assert "Signature" in cs.presigned_get("FY2025-26/a.pdf")
    assert cs.delete("FY2025-26") == 2




def test_tinyfish_search_and_fetch(monkeypatch):
    import asyncio

    from app import config
    from app.agent import web

    monkeypatch.setenv("TINYFISH_API_KEY", "tf_test")
    config.get_settings.cache_clear()
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        assert request.headers["X-API-Key"] == "tf_test"
        if request.method == "GET":
            return httpx.Response(200, json={"query": request.url.params["query"], "total_results": 1, "page": 0,
                                             "results": [{"position": 1, "site_name": "cbic-gst.gov.in", "title": "N",
                                                          "snippet": "s", "url": "https://cbic-gst.gov.in/x"}]})
        body = json.loads(request.content)
        return httpx.Response(200, json={"results": [{"url": body["urls"][0], "format": "markdown", "text": "# Notif"}],
                                         "errors": []})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    s = asyncio.run(web.search("gst rate 8415", include_domains=["cbic-gst.gov.in"]))
    assert s["results"][0]["site_name"] == "cbic-gst.gov.in"
    assert calls[0].url.params["include_domains"] == "cbic-gst.gov.in"
    f = asyncio.run(web.fetch(["https://cbic-gst.gov.in/x"], highlights_query="rate"))
    assert f["results"][0]["text"] == "# Notif"
    assert json.loads(calls[1].content)["highlights"]["query"] == "rate"
    config.get_settings.cache_clear()


def test_invoice_extraction_pipeline(workspace, monkeypatch):
    from app.agent.context import AgentContext
    from app.agent.tools import documents
    from app.workspace import CompanyProfile

    prof = workspace.create_company(CompanyProfile(name="Delta", gstins=["29AAGCB7383J1Z4"]), fy="FY2025-26")
    cs = workspace.company_storage(prof.id)
    cs.write_text("FY2025-26/02_Purchases/Bills/acme.txt", "TAX INVOICE ... (text)")
    inv = {"invoice_no": "A-17", "invoice_date": "2025-10-05", "place_of_supply_code": "29",
           "supplier": {"name": "Acme", "gstin": "27AAPFU0939F1ZV"},
           "buyer": {"name": "Delta", "gstin": "29AAGCB7383J1Z4"},
           "line_items": [{"description": "Split AC", "hsn_sac": "84151010", "quantity": 1, "unit_price": 30000,
                           "taxable_value": 30000, "gst_rate": 18, "cgst_amount": 2700, "sgst_utgst_amount": 2700}],
           "total_taxable_value": 30000, "total_cgst": 2700, "total_sgst_utgst": 2700, "grand_total": 35400,
           "extraction_confidence": "high"}
    model = ScriptedModel(script=[AIMessage("", tool_calls=[{"id": "x", "name": "Invoice", "args": inv}])])
    monkeypatch.setattr(documents, "get_model", lambda vision=False, override=None: model)

    class RT:
        context = AgentContext(company_id=prof.id, fy="FY2025-26")

    out = json.loads(documents.extract_invoice_data.func(RT(), "FY2025-26/02_Purchases/Bills/acme.txt"))
    # inter-state (27 -> 29) but CGST/SGST charged: must be flagged
    assert out["status"] == "error"
    assert any("should be IGST" in e for e in out["errors"])
    assert "Added 1 line" in out["register"]
    again = json.loads(documents.extract_invoice_data.func(RT(), "FY2025-26/02_Purchases/Bills/acme.txt"))
    assert "duplicate" in again["register"]
