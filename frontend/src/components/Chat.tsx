import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, streamChat, type HistoryMessage, type Todo } from "../lib/api";

type ToolCall = { id: string; name: string; args: unknown; output?: string; status?: string };
type Turn = { role: "user" | "assistant"; text: string; tools: ToolCall[] };

type Props = {
  companyId: string;
  fy: string | null;
  draft: { text: string; n: number } | null;
  onFilesChanged: () => void;
  onOpenFile: (path: string) => void;
};

const STARTERS = [
  "Reconcile GSTR-2B with the purchase register for last month and list ITC at risk.",
  "Extract all bills in 02_Purchases/Bills into the purchase register and flag errors.",
  "Which bank payments have no bill? Draft a message to the client asking for them.",
  "Check HSN codes and GST rates in the sales register (GST 2.0 changes).",
  "Compare old vs new regime for salary 18 lakh, 80C 1.5 lakh, 80D 25k, HRA exemption 1.2 lakh.",
  "What are this month's compliance due dates for this client?",
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

export default function Chat({ companyId, fy, draft, onFilesChanged, onOpenFile }: Props) {
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
        else if (ev.event === "error") patch((a) => ({ ...a, text: a.text + `\n\n> ⚠️ ${ev.data.message}` }));
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
              return <button className="link code" onClick={() => onOpenFile(s.trim())}>{s}</button>;
            }
            return <code {...props}>{children}</code>;
          },
        }}
      >
        {text}
      </ReactMarkdown>
    );
  }

  return (
    <div className="chat">
      <div className="chat-head">
        <select value={threadId ?? ""} onChange={(e) => (e.target.value ? openThread(e.target.value) : (setThreadId(null), setTurns([]), setTodos([])))}>
          <option value="">+ New conversation</option>
          {threads.map((t) => (
            <option key={t.id} value={t.id}>{t.title}</option>
          ))}
        </select>
      </div>
      <div className="messages" ref={listRef}>
        {!turns.length && (
          <div className="welcome">
            <h2>What should we work on?</h2>
            <p className="muted">The agent reads this client's folders, uses audited tax formulas, searches the web for current law, and writes workpapers you can edit in the spreadsheet tab.</p>
            <div className="starters">
              {STARTERS.map((s) => (
                <button key={s} className="starter" onClick={() => send(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`turn ${t.role}`}>
            {t.tools.length > 0 && (
              <div className="tools">
                {t.tools.map((tc) => (
                  <details key={tc.id} className={`tool ${tc.output === undefined ? "running" : tc.status === "error" ? "failed" : "done"}`}>
                    <summary>
                      <span className="dot" />
                      {TOOL_LABEL[tc.name] ?? tc.name}
                      <span className="muted small"> {summarizeArgs(tc.args)}</span>
                    </summary>
                    <div className="tool-body">
                      <div className="muted small">{tc.name} input</div>
                      <pre>{JSON.stringify(tc.args, null, 1)}</pre>
                      {tc.output !== undefined && (
                        <>
                          <div className="muted small">output</div>
                          <pre>{tc.output}</pre>
                        </>
                      )}
                    </div>
                  </details>
                ))}
              </div>
            )}
            {t.text ? <div className="bubble">{renderText(t.text)}</div> : t.role === "assistant" && running && i === turns.length - 1 && <div className="bubble muted">Working…</div>}
          </div>
        ))}
        {todos.length > 0 && (
          <div className="todos">
            <div className="muted small">Plan</div>
            {todos.map((td, i) => (
              <div key={i} className={`todo ${td.status}`}>{td.status === "completed" ? "✓" : td.status === "in_progress" ? "◐" : "○"} {td.content}</div>
            ))}
          </div>
        )}
      </div>
      <div className="composer">
        <textarea
          ref={inputRef}
          value={input}
          placeholder="Ask Maverick… (Shift+Enter for a new line)"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          rows={3}
        />
        {running ? (
          <button className="danger" onClick={() => abortRef.current?.abort()}>Stop</button>
        ) : (
          <button onClick={() => send()} disabled={!input.trim()}>Send</button>
        )}
      </div>
    </div>
  );
}

function summarizeArgs(args: unknown): string {
  if (!args || typeof args !== "object") return "";
  const a = args as Record<string, unknown>;
  const v = a.path ?? a.name ?? a.formula ?? a.query ?? a.folder ?? a.books_path ?? a.statement_path ?? a.code;
  return v ? `· ${String(v).slice(0, 60)}` : "";
}
