import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Toolbar } from "@astryxdesign/core/Toolbar";
import { Selector } from "@astryxdesign/core/Selector";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Button } from "@astryxdesign/core/Button";
import { Banner } from "@astryxdesign/core/Banner";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Spinner } from "@astryxdesign/core/Spinner";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { ArrowUp, Sparkles, Square, SquarePen } from "lucide-react";
import { api, streamChat, type HistoryMessage, type Todo } from "../lib/api";

const NEW = "__new__";

type ToolCall = { id: string; name: string; args: unknown; output?: string; status?: string };
type Turn = { role: "user" | "assistant"; text: string; tools: ToolCall[] };

type Props = {
  companyId: string;
  fy: string | null;
  draft: { text: string; n: number } | null;
  modelReady: boolean;
  onOpenModel: () => void;
  onFilesChanged: () => void;
  onOpenFile: (path: string) => void;
};

const STARTERS = [
  { title: "Reconcile GSTR-2B", text: "Reconcile GSTR-2B with the purchase register for last month and list ITC at risk." },
  { title: "Extract bills", text: "Extract all bills in 02_Purchases/Bills into the purchase register and flag errors." },
  { title: "Find missing bills", text: "Which bank payments have no bill? Draft a message to the client asking for them." },
  { title: "Check HSN & rates", text: "Check HSN codes and GST rates in the sales register (GST 2.0 changes)." },
  { title: "Old vs new regime", text: "Compare old vs new regime for salary 18 lakh, 80C 1.5 lakh, 80D 25k, HRA exemption 1.2 lakh." },
  { title: "Due dates", text: "What are this month's compliance due dates for this client?" },
];

const TOOL_LABEL: Record<string, string> = {
  load_skill: "Loading playbook", calculate: "Calculating", list_formulas: "Looking up formulas", web_search: "Searching the web",
  web_fetch: "Reading source", read_file: "Reading document", extract_invoice_data: "Extracting invoice",
  batch_extract_invoices: "Extracting invoices", reconcile_gstr2b: "Reconciling GSTR-2B", reconcile_bank: "Reconciling bank",
  reconcile_tds_26as: "Reconciling 26AS", find_missing_bills: "Finding missing bills", classify_inbox: "Classifying inbox",
  clean_table: "Cleaning data", check_hsn: "Checking HSN", audit_hsn_register: "Auditing HSN codes", write_todos: "Planning",
  set_spreadsheet_cells: "Writing spreadsheet", write_spreadsheet_table: "Writing spreadsheet", read_spreadsheet: "Reading spreadsheet",
  request_documents_from_client: "Drafting client request", remember: "Saving to client memory", move_file: "Filing document",
  list_files: "Browsing files", search_files: "Searching files", validate_ids: "Validating IDs",
};

const isWorkspacePath = (s: string) => /^(FY\d{4}-\d{2}|_inbox|_context|Permanent)\/.+\.[A-Za-z]{2,5}$/.test(s.trim());

function historyToTurns(msgs: HistoryMessage[]): Turn[] {
  const turns: Turn[] = [];
  const byId: Record<string, ToolCall> = {};
  for (const m of msgs) {
    if (m.role === "user") turns.push({ role: "user", text: m.content, tools: [] });
    else if (m.role === "assistant") {
      let last = turns[turns.length - 1];
      if (!last || last.role !== "assistant") {
        last = { role: "assistant", text: "", tools: [] };
        turns.push(last);
      }
      if (m.content) last.text += (last.text ? "\n\n" : "") + m.content;
      for (const tc of m.tool_calls) {
        const t = { id: tc.id, name: tc.name, args: tc.args };
        byId[tc.id] = t;
        last.tools.push(t);
      }
    } else if (m.role === "tool" && byId[m.tool_call_id]) byId[m.tool_call_id].output = m.content;
  }
  return turns;
}

export default function Chat({ companyId, fy, draft, modelReady, onOpenModel, onFilesChanged, onOpenFile }: Props) {
  const [threads, setThreads] = useState<{ id: string; title: string }[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [todos, setTodos] = useState<Todo[]>([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const refreshThreads = () => api.threads(companyId).then(setThreads).catch(() => setThreads([]));

  useEffect(() => {
    setThreadId(null);
    setTurns([]);
    setTodos([]);
    refreshThreads();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => {
    if (draft) {
      setInput(draft.text);
      inputRef.current?.focus();
    }
  }, [draft]);

  // Scroll only the message list (scrollIntoView would also scroll the page layout on mobile).
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, todos]);

  async function openThread(id: string) {
    if (running) return;
    setThreadId(id);
    const t = await api.thread(companyId, id);
    setTurns(historyToTurns(t.messages));
    setTodos(t.todos ?? []);
  }

  async function send(text?: string) {
    const message = (text ?? input).trim();
    if (!message || running) return;
    setInput("");
    setRunning(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setTurns((t) => [...t, { role: "user", text: message, tools: [] }, { role: "assistant", text: "", tools: [] }]);
    const patch = (fn: (a: Turn) => Turn) =>
      setTurns((t) => {
        const copy = t.slice();
        copy[copy.length - 1] = fn({ ...copy[copy.length - 1], tools: copy[copy.length - 1].tools.slice() });
        return copy;
      });
    let touchedFiles = false;
    try {
      for await (const ev of streamChat(companyId, { message, thread_id: threadId, fy }, ctrl.signal)) {
        if (ev.event === "thread") {
          if (!threadId) setThreadId(ev.data.thread_id);
        } else if (ev.event === "token") patch((a) => ({ ...a, text: a.text + ev.data.text }));
        else if (ev.event === "tool_start") patch((a) => ({ ...a, tools: [...a.tools, { id: ev.data.id, name: ev.data.name, args: ev.data.args }] }));
        else if (ev.event === "tool_end") {
          if (/write|move|extract|reconcile|clean|request|classify|create|set_|remember/.test(ev.data.name)) touchedFiles = true;
          patch((a) => ({ ...a, tools: a.tools.map((t) => (t.id === ev.data.id ? { ...t, output: ev.data.output, status: ev.data.status } : t)) }));
        } else if (ev.event === "todos") setTodos(ev.data);
        else if (ev.event === "error")
          patch((a) => ({
            ...a,
            text: a.text + `\n\n> ⚠️ ${ev.data.message}` + (/model|503|api key|401/i.test(ev.data.message) ? "\n>\n> Open **Model settings** in the top bar to add an OpenAI-compatible endpoint." : ""),
          }));
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") patch((a) => ({ ...a, text: a.text + `\n\n> ⚠️ ${(e as Error).message}` }));
    } finally {
      setRunning(false);
      abortRef.current = null;
      refreshThreads();
      if (touchedFiles) onFilesChanged();
    }
  }

  function renderText(text: string) {
    return (
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ children, ...props }) {
            const s = String(children);
            if (isWorkspacePath(s)) {
              return <button className="link-code" onClick={() => onOpenFile(s.trim())}>{s}</button>;
            }
            return <code {...props}>{children}</code>;
          },
        }}
      >
        {text}
      </ReactMarkdown>
    );
  }

  const threadOptions = [{ value: NEW, label: "New conversation" }, ...threads.map((t) => ({ value: t.id, label: t.title }))];
  const reset = () => (setThreadId(null), setTurns([]), setTodos([]), inputRef.current?.focus());

  return (
    <div className="chat">
      <Toolbar
        label="Conversation"
        size="sm"
        dividers={["bottom"]}
        startContent={
          <Selector
            label="Conversation"
            isLabelHidden
            variant="ghost"
            size="sm"
            hasSearch={threads.length > 8}
            searchPlaceholder="Find a conversation…"
            startIcon={<Sparkles size={16} />}
            options={threadOptions}
            value={threadId ?? NEW}
            isDisabled={running}
            onChange={(v) => (v === NEW ? reset() : openThread(v))}
          />
        }
        endContent={<IconButton label="New conversation" tooltip="New conversation" icon={<SquarePen size={16} />} variant="ghost" onClick={reset} isDisabled={running} />}
      />
      <div className="messages" ref={listRef} aria-live="polite">
        {!turns.length && (
          <div className="welcome">
            <div className="welcome-mark"><Sparkles size={22} /></div>
            <Heading level={2}>What should we work on?</Heading>
            <Text type="supporting" as="p">
              The assistant reads this client's folders, uses audited tax formulas, searches the web for current law, and writes workpapers you can edit.
            </Text>
            {!modelReady && (
              <Banner
                status="warning"
                title="No model configured"
                description="Connect any OpenAI-compatible endpoint to start."
                endContent={<Button label="Set up model" size="sm" onClick={onOpenModel} />}
              />
            )}
            <div className="starters">
              {STARTERS.map((s) => (
                <button key={s.text} className="starter" onClick={() => send(s.text)} disabled={running}>
                  <span className="starter-title">{s.title}</span>
                  <span className="starter-text">{s.text}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`turn ${t.role}`}>
            {t.tools.length > 0 && (
              <div className="tools">
                {t.tools.map((tc) => {
                  const state = tc.output === undefined ? "running" : tc.status === "error" ? "failed" : "done";
                  return (
                    <details key={tc.id} className={`tool ${state}`}>
                      <summary>
                        {state === "running" ? (
                          <Spinner size="sm" />
                        ) : (
                          <StatusDot variant={state === "failed" ? "error" : "success"} label={state === "failed" ? "Failed" : "Done"} />
                        )}
                        <span className="tool-name">{TOOL_LABEL[tc.name] ?? tc.name}</span>
                        <span className="tool-arg">{summarizeArgs(tc.args)}</span>
                      </summary>
                      <div className="tool-body">
                        <Text type="supporting">{tc.name} input</Text>
                        <pre>{JSON.stringify(tc.args, null, 1)}</pre>
                        {tc.output !== undefined && (
                          <>
                            <Text type="supporting">Output</Text>
                            <pre>{tc.output}</pre>
                          </>
                        )}
                      </div>
                    </details>
                  );
                })}
              </div>
            )}
            {t.text ? (
              <div className="bubble">{renderText(t.text)}</div>
            ) : (
              t.role === "assistant" && running && i === turns.length - 1 && (
                <div className="bubble thinking"><Spinner size="sm" /> <Text type="supporting">Working…</Text></div>
              )
            )}
          </div>
        ))}
        {todos.length > 0 && (
          <div className="todos">
            <Text type="label" weight="semibold">Plan</Text>
            {todos.map((td, i) => (
              <div key={i} className={`todo ${td.status}`}>
                <span className="todo-mark" aria-hidden>{td.status === "completed" ? "✓" : td.status === "in_progress" ? "◐" : "○"}</span> {td.content}
              </div>
            ))}
          </div>
        )}
      </div>
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <textarea
          ref={inputRef}
          value={input}
          aria-label="Message the assistant"
          placeholder="Ask Maverick anything about this client…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
          rows={2}
        />
        <div className="composer-bar">
          <Text type="supporting" size="xsm">{fy ? `${fy} · ` : ""}Enter to send · Shift+Enter for new line</Text>
          {running ? (
            <IconButton label="Stop" tooltip="Stop" icon={<Square size={14} fill="currentColor" />} variant="secondary" size="sm" onClick={() => abortRef.current?.abort()} />
          ) : (
            <IconButton label="Send" tooltip="Send (Enter)" icon={<ArrowUp size={16} />} variant="primary" size="sm" isDisabled={!input.trim()} onClick={() => send()} />
          )}
        </div>
      </form>
    </div>
  );
}

function summarizeArgs(args: unknown): string {
  if (!args || typeof args !== "object") return "";
  const a = args as Record<string, unknown>;
  const v = a.path ?? a.name ?? a.formula ?? a.query ?? a.folder ?? a.books_path ?? a.statement_path ?? a.code;
  return v ? `· ${String(v).slice(0, 60)}` : "";
}
