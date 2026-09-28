import { useState } from "react";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Banner } from "@astryxdesign/core/Banner";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Text } from "@astryxdesign/core/Text";
import { Eye, EyeOff } from "lucide-react";
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
  const set = (k: keyof LLMSettings) => (value: string) => setV((cur) => ({ ...cur, [k]: value }));

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
    if (!/^https?:\/\/.+/.test(v.baseUrl.trim()) || !v.model.trim()) return;
    setLLM({ ...v, baseUrl: v.baseUrl.trim().replace(/\/+$/, ""), model: v.model.trim(), visionModel: v.visionModel?.trim() || undefined });
    onClose();
  }

  const statusBanner = status && (
    status.kind === "busy" ? (
      <HStack gap={2} align="center"><Spinner size="sm" /><Text type="supporting">{status.text}</Text></HStack>
    ) : (
      <Banner status={status.kind === "ok" ? "success" : status.kind === "warn" ? "warning" : "error"} title={status.kind === "ok" ? "Connected" : status.kind === "warn" ? "Check the model" : "Connection failed"} description={status.text} />
    )
  );

  return (
    <Dialog isOpen onOpenChange={(o) => !o && onClose()} purpose="form" width={600} maxHeight="90dvh">
      <form onSubmit={save}>
        <Layout
          header={<DialogHeader title="Model settings" subtitle="Use any OpenAI-compatible API that supports tool calling." onOpenChange={onClose} />}
          content={
            <LayoutContent>
              <VStack gap={4}>
                <Text type="supporting" as="p">
                  The base URL, key and model stay in this browser tab's session storage (cleared when the tab closes) and are sent with each
                  agent request. The server does not save or log them.
                </Text>
                <VStack gap={1}>
                  <Text type="label">Quick presets</Text>
                  <div className="presets">
                    {PRESETS.map((p) => (
                      <Button key={p.label} label={p.label} size="sm" variant={v.baseUrl === p.baseUrl ? "primary" : "secondary"} onClick={() => setV({ ...v, baseUrl: p.baseUrl, model: p.model || v.model })} />
                    ))}
                  </div>
                </VStack>
                <TextInput label="Base URL" isRequired value={v.baseUrl} onChange={set("baseUrl")} placeholder="https://api.openai.com/v1" width="100%"
                  status={v.baseUrl && !/^https?:\/\/.+/.test(v.baseUrl) ? { type: "error", message: "Must start with http:// or https://" } : undefined} />
                <HStack gap={2} align="end">
                  <div className="grow">
                    <TextInput label="API key" type={showKey ? "text" : "password"} value={v.apiKey} onChange={set("apiKey")} placeholder="sk-… (leave empty for local servers)" autoComplete="off" width="100%" />
                  </div>
                  <IconButton label={showKey ? "Hide key" : "Show key"} tooltip={showKey ? "Hide key" : "Show key"} icon={showKey ? <EyeOff size={16} /> : <Eye size={16} />} onClick={() => setShowKey(!showKey)} />
                </HStack>
                <HStack gap={2} align="end">
                  <div className="grow">
                    <label className="native-field">
                      <Text type="label">Model <span className="req">Required</span></Text>
                      <input className="native-input" required value={v.model} onChange={(e) => set("model")(e.target.value)} list="llm-models" placeholder="gpt-5, anthropic/claude-sonnet-5, llama-3.3-70b…" />
                    </label>
                  </div>
                  <Button label="List models" variant="secondary" clickAction={fetchModels} isDisabled={!v.baseUrl} />
                </HStack>
                <label className="native-field">
                  <Text type="label">Vision model for scanned documents <Text type="supporting">(optional; defaults to the model above)</Text></Text>
                  <input className="native-input" value={v.visionModel ?? ""} onChange={(e) => set("visionModel")(e.target.value)} list="llm-models" />
                </label>
                <datalist id="llm-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
                <Text type="supporting">“localhost” URLs are reached from the server, not your computer.</Text>
                {statusBanner}
              </VStack>
            </LayoutContent>
          }
          footer={
            <LayoutFooter>
              <HStack gap={2} justify="between" wrap="wrap">
                {cur ? <Button label="Use server default" variant="ghost" onClick={() => (setLLM(null), onClose())} /> : <span />}
                <HStack gap={2} wrap="wrap">
                  <Button label="Test connection" variant="secondary" clickAction={test} isDisabled={!v.baseUrl || !v.model} />
                  <Button label="Save for this session" variant="primary" type="submit" isDisabled={!v.baseUrl || !v.model} />
                </HStack>
              </HStack>
            </LayoutFooter>
          }
        />
      </form>
    </Dialog>
  );
}
