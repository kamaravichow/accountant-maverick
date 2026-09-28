import { useState } from "react";
import { api, getLLM, setLLM, type LLMSettings } from "../lib/api";

const PRESETS: { label: string; baseUrl: string; model: string }[] = [
  { label: "OpenAI", baseUrl: "https://api.openai.com/v1", model: "gpt-5" },
  { label: "OpenRouter", baseUrl: "https://openrouter.ai/api/v1", model: "anthropic/claude-sonnet-5" },
  { label: "Groq", baseUrl: "https://api.groq.com/openai/v1", model: "" },
  { label: "Together", baseUrl: "https://api.together.xyz/v1", model: "" },
  { label: "DeepSeek", baseUrl: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  { label: "Ollama (server-local)", baseUrl: "http://localhost:11434/v1", model: "" },
  { label: "LM Studio (server-local)", baseUrl: "http://localhost:1234/v1", model: "" },
];

type Status = { kind: "ok" | "warn" | "error" | "busy"; text: string } | null;

export default function ModelSettings({ onClose }: { onClose: () => void }) {
  const cur = getLLM();
  const [v, setV] = useState<LLMSettings>(cur ?? { baseUrl: "", apiKey: "", model: "", visionModel: "" });
  const [models, setModels] = useState<string[]>([]);
  const [status, setStatus] = useState<Status>(null);
  const [showKey, setShowKey] = useState(false);
  const set = (k: keyof LLMSettings) => (e: React.ChangeEvent<HTMLInputElement>) => setV({ ...v, [k]: e.target.value });

  async function fetchModels() {
    setStatus({ kind: "busy", text: "Fetching models…" });
    try {
      const list = await api.llmModels(v);
      setModels(list);
      setStatus({ kind: "ok", text: `${list.length} models available` });
    } catch (e) {
      setStatus({ kind: "error", text: (e as Error).message });
    }
  }

  async function test() {
    setStatus({ kind: "busy", text: "Testing a completion and a tool call…" });
    try {
      const r = await api.llmTest(v);
      setStatus(r.tool_calling ? { kind: "ok", text: `Connected. Tool calling works. Reply: “${r.reply}”` } : { kind: "warn", text: r.warning ?? "No tool call returned" });
    } catch (e) {
      setStatus({ kind: "error", text: (e as Error).message });
    }
  }

  function save(e: React.FormEvent) {
    e.preventDefault();
    setLLM({ ...v, baseUrl: v.baseUrl.trim().replace(/\/+$/, ""), model: v.model.trim(), visionModel: v.visionModel?.trim() || undefined });
    onClose();
  }

  return (
    <div className="modal-bg" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={save}>
        <h3>Model settings</h3>
        <p className="muted small">
          Use any <strong>OpenAI-compatible</strong> API for the agent. The base URL, key and model are kept only in this browser
          tab's session storage (cleared when the tab closes) and sent with each agent request. The server does not save or log them.
          The model must support tool/function calling.
        </p>
        <div className="presets">
          {PRESETS.map((p) => (
            <button type="button" key={p.label} className="ghost small" onClick={() => setV({ ...v, baseUrl: p.baseUrl, model: p.model || v.model })}>
              {p.label}
            </button>
          ))}
        </div>
        <label className="field">Base URL
          <input required value={v.baseUrl} onChange={set("baseUrl")} placeholder="https://api.openai.com/v1" pattern="https?://.+" />
        </label>
        <label className="field">API key
          <span className="row">
            <input type={showKey ? "text" : "password"} value={v.apiKey} onChange={set("apiKey")} placeholder="sk-… (leave empty for local servers)" autoComplete="off" />
            <button type="button" className="ghost small" onClick={() => setShowKey(!showKey)}>{showKey ? "Hide" : "Show"}</button>
          </span>
        </label>
        <label className="field">Model
          <span className="row">
            <input required value={v.model} onChange={set("model")} list="llm-models" placeholder="gpt-5, anthropic/claude-sonnet-5, llama-3.3-70b…" />
            <button type="button" className="ghost small" onClick={fetchModels} disabled={!v.baseUrl}>List models</button>
          </span>
        </label>
        <label className="field">Vision model for scanned documents <span className="muted small">(optional; defaults to the model above)</span>
          <input value={v.visionModel ?? ""} onChange={set("visionModel")} list="llm-models" />
        </label>
        <datalist id="llm-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
        <p className="muted small">“localhost” URLs are reached from the <em>server</em>, not your computer.</p>
        {status && <div className={`notice ${status.kind}`}>{status.text}</div>}
        <div className="modal-actions">
          {cur && (
            <button type="button" className="ghost" onClick={() => (setLLM(null), onClose())}>Use server default</button>
          )}
          <span className="spacer" />
          <button type="button" className="ghost" onClick={test} disabled={!v.baseUrl || !v.model}>Test connection</button>
          <button type="button" className="ghost" onClick={onClose}>Cancel</button>
          <button type="submit">Save for this session</button>
        </div>
      </form>
    </div>
  );
}
