import { useEffect, useState } from "react";
import { api, getLLM, getToken, setToken, type Company, type Health } from "./lib/api";
import FileExplorer from "./components/FileExplorer";
import FileViewer from "./components/FileViewer";
import Chat from "./components/Chat";
import Calculators from "./components/Calculators";
import ModelSettings from "./components/ModelSettings";

const CALC_TAB = "__calculators__";
const LAST_KEY = "maverick.company";

function currentFY() {
  const d = new Date();
  const y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
  return `FY${y}-${String(y + 1).slice(-2)}`;
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [fy, setFy] = useState<string | null>(null);
  const [tabs, setTabs] = useState<string[]>([CALC_TAB]);
  const [active, setActive] = useState<string>(CALC_TAB);
  const [refreshKey, setRefreshKey] = useState(0);
  const [draft, setDraft] = useState<{ text: string; n: number } | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [authError, setAuthError] = useState(false);
  const [showModel, setShowModel] = useState(false);
  const [llm, setLlmState] = useState(getLLM());

  useEffect(() => {
    const sync = () => setLlmState(getLLM());
    window.addEventListener("maverick-llm", sync);
    return () => window.removeEventListener("maverick-llm", sync);
  }, []);

  async function loadCompanies(select?: string) {
    try {
      const list = await api.companies();
      setCompanies(list);
      setAuthError(false);
      let last: string | null = null;
      try {
        last = localStorage.getItem(LAST_KEY);
      } catch {
        /* ignore */
      }
      const pick = select ?? (list.find((c) => c.id === last)?.id || list[0]?.id || null);
      setCompanyId(pick);
      if (!list.length) setShowNew(true);
    } catch (e) {
      if (String((e as Error).message).startsWith("401") || /token/i.test((e as Error).message)) setAuthError(true);
    }
  }

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    loadCompanies();
  }, []);

  const company = companies.find((c) => c.id === companyId) ?? null;
  useEffect(() => {
    if (!company) return;
    try {
      localStorage.setItem(LAST_KEY, company.id);
    } catch {
      /* ignore */
    }
    const cur = currentFY();
    setFy(company.financial_years.includes(cur) ? cur : company.financial_years[company.financial_years.length - 1] ?? cur);
    setTabs([CALC_TAB]);
    setActive(CALC_TAB);
  }, [company?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  function openFile(path: string) {
    setTabs((t) => (t.includes(path) ? t : [...t, path]));
    setActive(path);
  }
  function closeTab(path: string) {
    setTabs((t) => {
      const next = t.filter((x) => x !== path);
      if (active === path) setActive(next[next.length - 1] ?? CALC_TAB);
      return next;
    });
  }
  const ask = (text: string) => setDraft({ text, n: Date.now() });

  if (authError) return <TokenGate onSaved={() => loadCompanies()} />;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand"><span className="logo">₹</span> Accountant Maverick</div>
        <select value={companyId ?? ""} onChange={(e) => setCompanyId(e.target.value)} aria-label="Company">
          {companies.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <button className="ghost small" onClick={() => setShowNew(true)}>+ Company</button>
        {company && (
          <>
            <select value={fy ?? ""} onChange={(e) => setFy(e.target.value)} aria-label="Financial year">
              {company.financial_years.map((y) => (
                <option key={y}>{y}</option>
              ))}
            </select>
            <button
              className="ghost small"
              title="Add a financial year folder tree"
              onClick={async () => {
                const y = prompt("Add financial year (e.g. FY2026-27)", currentFY());
                if (!y) return;
                try {
                  await api.addFY(company.id, y);
                  await loadCompanies(company.id);
                  setRefreshKey((k) => k + 1);
                } catch (e) {
                  alert((e as Error).message);
                }
              }}
            >+ FY</button>
          </>
        )}
        <span className="spacer" />
        {health && (
          <span className="status">
            <button
              className={`pill button-pill ${llm || health.agent ? "ok" : "warn"}`}
              title={llm ? `Your endpoint: ${llm.baseUrl}` : `Server model: ${health.model}`}
              onClick={() => setShowModel(true)}
            >
              ⚙ {llm ? `Model: ${llm.model}` : health.agent ? "Server model" : "Set up a model"}
            </button>
            <span className={`pill ${health.web_search ? "ok" : "warn"}`}>{health.web_search ? "Live search" : "No web search"}</span>
            <span className="pill">{health.storage === "s3" ? "S3" : "Local storage"}</span>
          </span>
        )}
      </header>

      {company ? (
        <main className="layout">
          <aside className="left">
            <FileExplorer
              companyId={company.id}
              refreshKey={refreshKey}
              selected={active}
              onOpen={openFile}
              onAsk={ask}
              onChanged={() => setRefreshKey((k) => k + 1)}
            />
          </aside>
          <section className="center">
            <nav className="tabs">
              {tabs.map((t) => (
                <div key={t} className={`tab${active === t ? " active" : ""}`} onClick={() => setActive(t)} title={t}>
                  {t === CALC_TAB ? "🧮 Calculators" : t.split("/").pop()}
                  {t !== CALC_TAB && (
                    <button className="icon" onClick={(e) => (e.stopPropagation(), closeTab(t))}>✕</button>
                  )}
                </div>
              ))}
            </nav>
            <div className="tab-body">
              {active === CALC_TAB ? (
                <Calculators />
              ) : (
                <FileViewer key={active} companyId={company.id} path={active} onAsk={ask} onChanged={() => setRefreshKey((k) => k + 1)} />
              )}
            </div>
          </section>
          <aside className="right">
            <Chat companyId={company.id} fy={fy} draft={draft} onFilesChanged={() => setRefreshKey((k) => k + 1)} onOpenFile={openFile} />
          </aside>
        </main>
      ) : (
        <div className="empty">Create a company to get started.</div>
      )}
      {showModel && <ModelSettings onClose={() => setShowModel(false)} />}
      {showNew && (
        <NewCompany
          onClose={() => setShowNew(false)}
          onCreated={async (c) => {
            setShowNew(false);
            await loadCompanies(c.id);
          }}
        />
      )}
    </div>
  );
}

function NewCompany({ onClose, onCreated }: { onClose: () => void; onCreated: (c: Company) => void }) {
  const [f, setF] = useState({
    name: "", entity_type: "company", pan: "", gstins: "", state: "", gst_filing: "monthly", tax_regime: "new",
    books_software: "Tally Prime", contact_name: "", contact_email: "", contact_phone: "", fy: currentFY(),
  });
  const [err, setErr] = useState<string | null>(null);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      const c = await api.createCompany({
        ...f,
        pan: f.pan || null,
        gstins: f.gstins.split(/[\s,]+/).filter(Boolean).map((g) => g.toUpperCase()),
      } as never);
      onCreated(c);
    } catch (ex) {
      setErr((ex as Error).message);
    }
  }
  return (
    <div className="modal-bg" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>New client</h3>
        <p className="muted small">Creates the standard folder structure (inbox, permanent file, and one tree per FY) and a context profile the agent reads first.</p>
        <div className="grid2">
          <label className="field">Name<input required value={f.name} onChange={set("name")} /></label>
          <label className="field">Entity type
            <select value={f.entity_type} onChange={set("entity_type")}>
              {["individual", "huf", "firm", "llp", "company", "trust", "aop"].map((x) => <option key={x}>{x}</option>)}
            </select>
          </label>
          <label className="field">PAN<input value={f.pan} onChange={set("pan")} maxLength={10} /></label>
          <label className="field">GSTIN(s)<input value={f.gstins} onChange={set("gstins")} placeholder="comma separated" /></label>
          <label className="field">State<input value={f.state} onChange={set("state")} /></label>
          <label className="field">GST filing
            <select value={f.gst_filing} onChange={set("gst_filing")}>
              {["monthly", "qrmp", "composition", "none"].map((x) => <option key={x}>{x}</option>)}
            </select>
          </label>
          <label className="field">Tax regime
            <select value={f.tax_regime} onChange={set("tax_regime")}><option>new</option><option>old</option></select>
          </label>
          <label className="field">Books software<input value={f.books_software} onChange={set("books_software")} /></label>
          <label className="field">Contact name<input value={f.contact_name} onChange={set("contact_name")} /></label>
          <label className="field">Contact email<input type="email" value={f.contact_email} onChange={set("contact_email")} /></label>
          <label className="field">Contact phone<input value={f.contact_phone} onChange={set("contact_phone")} /></label>
          <label className="field">Financial year<input value={f.fy} onChange={set("fy")} pattern="FY\d{4}-\d{2}" /></label>
        </div>
        {err && <pre className="error">{err}</pre>}
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={onClose}>Cancel</button>
          <button type="submit">Create</button>
        </div>
      </form>
    </div>
  );
}

function TokenGate({ onSaved }: { onSaved: () => void }) {
  const [t, setT] = useState(getToken());
  return (
    <div className="modal-bg">
      <form className="modal" onSubmit={(e) => (e.preventDefault(), setToken(t), onSaved())}>
        <h3>Access token</h3>
        <p className="muted small">This deployment is protected. Enter the APP_TOKEN configured on the server.</p>
        <input value={t} onChange={(e) => setT(e.target.value)} type="password" autoFocus />
        <div className="modal-actions"><button type="submit">Continue</button></div>
      </form>
    </div>
  );
}
