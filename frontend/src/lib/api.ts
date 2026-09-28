// Thin client for the FastAPI backend (REST + SSE over fetch).

export type Company = {
  id: string;
  name: string;
  entity_type: string;
  pan?: string | null;
  gstins: string[];
  state?: string | null;
  gst_filing: string;
  tax_regime: string;
  books_software?: string | null;
  financial_years: string[];
  contact_name?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
};

export type Entry = {
  path: string;
  name: string;
  is_dir: boolean;
  size: number;
  modified: string | null;
  content_type: string | null;
};

export type Health = { ok: boolean; agent: boolean; storage: string; model: string; web_search: boolean; auth: boolean; byo_llm?: boolean };

const TOKEN_KEY = "maverick.token";
const LLM_KEY = "maverick.llm";

/** Browser-held OpenAI-compatible endpoint. Lives in sessionStorage only (cleared when the tab closes)
 *  and is sent as headers on agent requests; the server never stores it. */
export type LLMSettings = { baseUrl: string; apiKey: string; model: string; visionModel?: string };

export function getLLM(): LLMSettings | null {
  try {
    const raw = sessionStorage.getItem(LLM_KEY);
    const v = raw ? (JSON.parse(raw) as LLMSettings) : null;
    return v && v.baseUrl && v.model ? v : null;
  } catch {
    return null;
  }
}

export function setLLM(v: LLMSettings | null) {
  try {
    if (v) sessionStorage.setItem(LLM_KEY, JSON.stringify(v));
    else sessionStorage.removeItem(LLM_KEY);
  } catch {
    /* storage unavailable: settings last only for this page load */
  }
  window.dispatchEvent(new Event("maverick-llm"));
}

function llmHeaders(v: Partial<LLMSettings> | null = getLLM()): Record<string, string> {
  if (!v || !v.baseUrl) return {};
  const h: Record<string, string> = { "X-LLM-Base-URL": v.baseUrl.trim() };
  if (v.apiKey) h["X-LLM-API-Key"] = v.apiKey.trim();
  if (v.model) h["X-LLM-Model"] = v.model.trim();
  if (v.visionModel) h["X-LLM-Vision-Model"] = v.visionModel.trim();
  return h;
}

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setToken(t: string) {
  try {
    localStorage.setItem(TOKEN_KEY, t);
  } catch {
    /* storage unavailable */
  }
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  const t = getToken();
  return { ...(t ? { Authorization: `Bearer ${t}` } : {}), ...extra };
}

async function req<T>(method: string, url: string, body?: unknown, extra: Record<string, string> = {}): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: headers({ ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...extra }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* keep status text */
    }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

const c = (id: string) => `/api/companies/${encodeURIComponent(id)}`;

export const api = {
  health: () => req<Health>("GET", "/api/health"),
  companies: () => req<Company[]>("GET", "/api/companies"),
  createCompany: (body: Partial<Company> & { name: string; fy?: string }) => req<Company>("POST", "/api/companies", body),
  updateCompany: (id: string, body: Partial<Company>) => req<Company>("PUT", c(id), body),
  addFY: (id: string, fy: string) => req<{ created: string[] }>("POST", `${c(id)}/fy`, { fy }),
  list: (id: string, path = "") => req<Entry[]>("GET", `${c(id)}/files?path=${encodeURIComponent(path)}`),
  mkdir: (id: string, path: string) => req("POST", `${c(id)}/files/mkdir`, { path }),
  move: (id: string, source: string, destination: string) => req("POST", `${c(id)}/files/move`, { source, destination }),
  remove: (id: string, path: string) => req("DELETE", `${c(id)}/files?path=${encodeURIComponent(path)}`),
  threads: (id: string) => req<{ id: string; title: string; updated_at: string }[]>("GET", `${c(id)}/threads`),
  thread: (id: string, tid: string) => req<{ messages: HistoryMessage[]; todos: Todo[] }>("GET", `${c(id)}/threads/${tid}`),
  requests: (id: string) => req<DocRequest[]>("GET", `${c(id)}/requests`),
  formulas: () => req<FormulaInfo[]>("GET", "/api/formulas"),
  formula: (name: string) => req<FormulaInfo & { schema: JsonSchema }>("GET", `/api/formulas/${name}`),
  runFormula: (name: string, args: unknown) => req<Record<string, unknown>>("POST", `/api/formulas/${name}`, args),
  skills: () => req<{ name: string; description: string; source: string }[]>("GET", "/api/skills"),
  llmModels: (v: Partial<LLMSettings>) => req<string[]>("GET", "/api/llm/models", undefined, llmHeaders({ ...v, model: "" })),
  llmTest: (v: LLMSettings) =>
    req<{ ok: boolean; reply: string; tool_calling: boolean; warning: string | null }>("POST", "/api/llm/test", undefined, llmHeaders(v)),

  fileUrl(id: string, path: string, download = false) {
    const t = getToken();
    return `${c(id)}/files/download?path=${encodeURIComponent(path)}&inline=${!download}${t ? `&token=${encodeURIComponent(t)}` : ""}`;
  },
  async fetchBytes(id: string, path: string): Promise<ArrayBuffer> {
    const r = await fetch(`${c(id)}/files/download?path=${encodeURIComponent(path)}`, { headers: headers() });
    if (!r.ok) throw new Error(`Download failed: ${r.status}`);
    return r.arrayBuffer();
  },
  async saveBytes(id: string, path: string, data: ArrayBuffer | Blob, contentType: string) {
    const r = await fetch(`${c(id)}/files/raw?path=${encodeURIComponent(path)}`, {
      method: "PUT",
      headers: headers({ "Content-Type": contentType }),
      body: data,
    });
    if (!r.ok) throw new Error(`Save failed: ${r.status}`);
    return r.json();
  },
  async upload(id: string, folder: string, files: File[]) {
    // Large files go straight to S3 via a presigned URL when the backend is on S3.
    const small: File[] = [];
    for (const f of files) {
      if (f.size > 25 * 1024 * 1024) {
        const p = await req<{ url: string | null; path: string }>("POST", `${c(id)}/files/presign-upload`, {
          path: `${folder || "_inbox"}/${f.name}`,
          content_type: f.type || "application/octet-stream",
        });
        if (p.url) {
          const r = await fetch(p.url, { method: "PUT", body: f, headers: { "Content-Type": f.type || "application/octet-stream" } });
          if (!r.ok) throw new Error(`S3 upload failed for ${f.name}`);
          continue;
        }
      }
      small.push(f);
    }
    if (!small.length) return;
    const fd = new FormData();
    fd.append("folder", folder);
    small.forEach((f) => fd.append("files", f));
    const r = await fetch(`${c(id)}/files/upload`, { method: "POST", headers: headers(), body: fd });
    if (!r.ok) throw new Error(`Upload failed: ${(await r.text()).slice(0, 200)}`);
    return r.json();
  },
};

export type Todo = { content: string; status: "pending" | "in_progress" | "completed" };
export type HistoryMessage =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string; tool_calls: { id: string; name: string; args: unknown }[] }
  | { role: "tool"; tool_call_id: string; name: string; content: string };
export type DocRequest = { id: string; document: string; reason?: string; due_date?: string; status: string; requested_at: string };
export type FormulaInfo = { name: string; category: string; description: string };
export type JsonSchema = {
  type?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  $defs?: Record<string, JsonSchema>;
  $ref?: string;
  anyOf?: JsonSchema[];
  enum?: unknown[];
  default?: unknown;
  description?: string;
  title?: string;
  items?: JsonSchema;
  format?: string;
};

export type StreamEvent =
  | { event: "thread"; data: { thread_id: string } }
  | { event: "token"; data: { text: string } }
  | { event: "tool_start"; data: { id: string; name: string; args: unknown } }
  | { event: "tool_end"; data: { id: string; name: string; status: string; output: string } }
  | { event: "todos"; data: Todo[] }
  | { event: "done"; data: { thread_id: string } }
  | { event: "error"; data: { message: string } };

/** POST a chat message and yield parsed SSE events. */
export async function* streamChat(
  companyId: string,
  body: { message: string; thread_id?: string | null; fy?: string | null; attachments?: string[] },
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const r = await fetch(`${c(companyId)}/chat`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", Accept: "text/event-stream", ...llmHeaders() }),
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok || !r.body) {
    let msg = `${r.status}`;
    try {
      msg = (await r.json()).detail ?? msg;
    } catch {
      /* ignore */
    }
    yield { event: "error", data: { message: msg } };
    return;
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let ev = "message";
      const data: string[] = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) ev = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (!data.length || ev === "ping") continue;
      try {
        yield { event: ev, data: JSON.parse(data.join("\n")) } as StreamEvent;
      } catch {
        /* ignore malformed */
      }
    }
  }
}

export function fmtSize(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
