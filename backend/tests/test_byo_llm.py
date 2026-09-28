"""Browser-supplied OpenAI-compatible endpoint: headers -> ChatOpenAI -> agent run, without a server model."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from fastapi.testclient import TestClient

CALLS = []


class FakeOpenAI(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer sk-test":
            return self._send({"error": "bad key"}, 401)
        self._send({"data": [{"id": "gpt-test"}, {"id": "gpt-mini"}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        CALLS.append({"auth": self.headers.get("Authorization"), "body": req})
        msgs = req["messages"]
        has_tool_result = any(m["role"] == "tool" for m in msgs)
        if req.get("tools") and not has_tool_result and "calculate" in [t["function"]["name"] for t in req["tools"]]:
            msg = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_1", "type": "function", "function": {"name": "calculate", "arguments": json.dumps(
                    {"formula": "gst_split", "inputs": {"taxable_value": 1000, "rate": 18, "supplier_state": "27",
                                                       "place_of_supply": "29"}})}}]}
        elif req.get("tools") and not has_tool_result:
            msg = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_t", "type": "function", "function": {"name": "add", "arguments": '{"a": 2, "b": 3}'}}]}
        else:
            msg = {"role": "assistant", "content": "IGST is Rs 180."}
        if req.get("stream"):
            delta = {"role": "assistant", "content": msg["content"] or ""}
            if msg.get("tool_calls"):
                delta["tool_calls"] = [{**tc, "index": i} for i, tc in enumerate(msg["tool_calls"])]
            chunks = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                      {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for c in chunks:
                c.update(id="x", object="chat.completion.chunk", created=0, model=req["model"])
                self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        self._send({"id": "x", "object": "chat.completion", "created": 0, "model": req["model"],
                    "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


def _server():
    srv = HTTPServer(("127.0.0.1", 0), FakeOpenAI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_byo_openai_compatible_endpoint(workspace, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "anthropic:claude-sonnet-5")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from app.main import create_app

    srv = _server()
    base = f"http://127.0.0.1:{srv.server_port}/v1"
    hdrs = {"X-LLM-Base-URL": base, "X-LLM-API-Key": "sk-test", "X-LLM-Model": "gpt-test"}
    with TestClient(create_app()) as client:
        assert client.get("/api/llm/models", headers={k: v for k, v in hdrs.items() if k != "X-LLM-Model"}).json() \
            == ["gpt-mini", "gpt-test"]
        t = client.post("/api/llm/test", headers=hdrs).json()
        assert t["ok"] and t["tool_calling"] is True

        cid = client.post("/api/companies", json={"name": "Byo Co", "fy": "FY2025-26"}).json()["id"]
        # no server model and no headers -> clear 503
        if client.app.state.agent is None:
            assert client.post(f"/api/companies/{cid}/chat", json={"message": "hi"}).status_code == 503
        CALLS.clear()
        r = client.post(f"/api/companies/{cid}/chat", json={"message": "GST on 1000 from MH to KA?"}, headers=hdrs)
        text = r.text
        assert "IGST is Rs 180." in text and '\\"igst\\": 180.0' in text
        assert all(c["auth"] == "Bearer sk-test" and c["body"]["model"] == "gpt-test" for c in CALLS)
        thread_id = json.loads(text.split("data:", 1)[1].split("\n", 1)[0])["thread_id"]
        hist = client.get(f"/api/companies/{cid}/threads/{thread_id}").json()
        assert hist["messages"][-1]["content"] == "IGST is Rs 180."
        # key never persisted in workspace files
    srv.shutdown()
    root = workspace.storage.root
    assert not any("sk-test" in p.read_text(errors="ignore") for p in root.rglob("*") if p.is_file())


def test_bad_headers_rejected(workspace):
    from app.main import create_app

    with TestClient(create_app()) as client:
        cid = client.post("/api/companies", json={"name": "X", "fy": "FY2025-26"}).json()["id"]
        r = client.post(f"/api/companies/{cid}/chat", json={"message": "hi"},
                        headers={"X-LLM-Base-URL": "ftp://x", "X-LLM-Model": "m"})
        assert r.status_code == 400
