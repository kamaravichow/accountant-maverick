import { useEffect, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Selector } from "@astryxdesign/core/Selector";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Grid } from "@astryxdesign/core/Grid";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Banner } from "@astryxdesign/core/Banner";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { ResizeHandle, useResizable } from "@astryxdesign/core/Resizable";
import { Building2, Calculator, CalendarPlus, Files, MessagesSquare, PanelLeft, PanelRight, Plus, Settings2, X } from "lucide-react";
import { api, getLLM, getToken, setToken, type Company, type Health } from "./lib/api";
import FileExplorer, { fileIcon } from "./components/FileExplorer";
import FileViewer from "./components/FileViewer";
import Chat from "./components/Chat";
import Calculators from "./components/Calculators";
import ModelSettings from "./components/ModelSettings";
import { DialogProvider, useDialogs } from "./components/dialogs";

const CALC_TAB = "__calculators__";
const LAST_KEY = "maverick.company";
type MobilePane = "files" | "work" | "chat";

function currentFY() {
  const d = new Date();
  const y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
  return `FY${y}-${String(y + 1).slice(-2)}`;
}

function useMediaQuery(q: string) {
  const [match, setMatch] = useState(() => window.matchMedia(q).matches);
  useEffect(() => {
    const m = window.matchMedia(q);
    const on = () => setMatch(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [q]);
  return match;
}

export default function App() {
  return (
    <DialogProvider>
      <Workspace />
    </DialogProvider>
  );
}

function Workspace() {
  const dialogs = useDialogs();
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
  const [pane, setPane] = useState<MobilePane>("work");
  const isMobile = useMediaQuery("(max-width: 899px)");

  // Resizable, collapsible side panels. Widths and collapse state persist in localStorage.
  const files = useResizable({ defaultSize: 280, minSize: 200, maxSize: 520, collapsible: true, snaps: [280], autoSaveId: "maverick.files" });
  const chat = useResizable({ defaultSize: 420, minSize: 320, maxSize: 900, collapsible: true, snaps: [420], autoSaveId: "maverick.chat" });
  const toggle = (r: typeof files) => (r.isCollapsed ? r.expand() : r.collapse());

  useEffect(() => {
    const sync = () => setLlmState(getLLM());
    window.addEventListener("maverick-llm", sync);
    return () => window.removeEventListener("maverick-llm", sync);
  }, []);

  // Ctrl/⌘+B toggles the file panel, Ctrl/⌘+J the assistant (VS Code conventions).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "b") {
        e.preventDefault();
        if (isMobile) setPane((p) => (p === "files" ? "work" : "files"));
        else toggle(files);
      } else if (k === "j") {
        e.preventDefault();
        if (isMobile) setPane((p) => (p === "chat" ? "work" : "chat"));
        else toggle(chat);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

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
    setPane("work");
  }
  function closeTab(path: string) {
    setTabs((t) => {
      const next = t.filter((x) => x !== path);
      if (active === path) setActive(next[next.length - 1] ?? CALC_TAB);
      return next;
    });
  }
  const ask = (text: string) => {
    setDraft({ text, n: Date.now() });
    if (isMobile) setPane("chat");
    else if (chat.isCollapsed) chat.expand();
  };

  async function addFY() {
    if (!company) return;
    const y = await dialogs.prompt({
      title: "Add financial year",
      label: "Financial year",
      description: "Creates the standard folder tree for the year.",
      initial: currentFY(),
      actionLabel: "Add year",
    });
    if (!y) return;
    try {
      await api.addFY(company.id, y);
      await loadCompanies(company.id);
      setFy(y);
      setRefreshKey((k) => k + 1);
    } catch (e) {
      dialogs.notify((e as Error).message, "error");
    }
  }

  if (authError) return <TokenGate onSaved={() => loadCompanies()} />;

  const modelReady = !!llm || !!health?.agent;
  const filesPanel = company && (
    <FileExplorer
      companyId={company.id}
      refreshKey={refreshKey}
      selected={active}
      onOpen={openFile}
      onAsk={ask}
      onChanged={() => setRefreshKey((k) => k + 1)}
    />
  );
  const workPanel = company && (
    <section className="work" aria-label="Documents">
      <div className="doc-tabs" role="tablist" aria-label="Open documents">
        {tabs.map((t) => {
          const isCalc = t === CALC_TAB;
          const name = isCalc ? "Calculators" : t.split("/").pop()!;
          return (
            <div
              key={t}
              role="tab"
              tabIndex={0}
              aria-selected={active === t}
              className={`doc-tab${active === t ? " active" : ""}`}
              onClick={() => setActive(t)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setActive(t))}
              onAuxClick={(e) => e.button === 1 && !isCalc && closeTab(t)}
              title={isCalc ? "Tax & compliance calculators" : t}
            >
              <span className="doc-tab-icon">{isCalc ? <Calculator size={14} /> : fileIcon(t, 14)}</span>
              <span className="doc-tab-name">{name}</span>
              {!isCalc && (
                <button className="doc-tab-close" aria-label={`Close ${name}`} onClick={(e) => (e.stopPropagation(), closeTab(t))}>
                  <X size={13} />
                </button>
              )}
            </div>
          );
        })}
      </div>
      <div className="work-body">
        {active === CALC_TAB ? (
          <Calculators />
        ) : (
          <FileViewer key={active} companyId={company.id} path={active} onAsk={ask} onChanged={() => setRefreshKey((k) => k + 1)} />
        )}
      </div>
    </section>
  );
  const chatPanel = company && (
    <Chat
      companyId={company.id}
      fy={fy}
      draft={draft}
      modelReady={modelReady}
      onOpenModel={() => setShowModel(true)}
      onFilesChanged={() => setRefreshKey((k) => k + 1)}
      onOpenFile={openFile}
    />
  );

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand" aria-label="Accountant Maverick">
          <span className="logo">₹</span>
          <span className="brand-name">Maverick</span>
        </div>
        <span className="topbar-sep" />
        <div className="topbar-context">
          <Selector
            label="Client"
            isLabelHidden
            variant="ghost"
            size="sm"
            hasSearch={companies.length > 6}
            searchPlaceholder="Find a client…"
            startIcon={<Building2 size={16} />}
            placeholder="Choose a client"
            options={companies.map((c) => ({ value: c.id, label: c.name }))}
            value={companyId ?? undefined}
            onChange={(v) => setCompanyId(v)}
          />
          <IconButton label="New client" tooltip="New client" icon={<Plus size={16} />} variant="ghost" size="sm" onClick={() => setShowNew(true)} />
          {company && (
            <>
              <Selector
                label="Financial year"
                isLabelHidden
                variant="ghost"
                size="sm"
                options={company.financial_years}
                value={fy ?? undefined}
                onChange={(v) => setFy(v)}
              />
              <IconButton label="Add financial year" tooltip="Add financial year" icon={<CalendarPlus size={16} />} variant="ghost" size="sm" onClick={addFY} />
            </>
          )}
        </div>
        <span className="spacer" />
        {health && (
          <HStack gap={3} align="center">
            <span className="status-item hide-sm" title={health.web_search ? "The agent can search the web for current law" : "Web search is not configured on the server"}>
              <StatusDot variant={health.web_search ? "success" : "neutral"} label={health.web_search ? "Web search on" : "Web search off"} />
              <Text type="supporting">{health.web_search ? "Web search" : "No web search"}</Text>
            </span>
            <span className="status-item hide-sm" title="Where client files are stored">
              <StatusDot variant="neutral" label="Storage" />
              <Text type="supporting">{health.storage === "s3" ? "S3" : "Local storage"}</Text>
            </span>
          </HStack>
        )}
        <Button
          label={llm ? llm.model : modelReady ? "Server model" : "Set up model"}
          tooltip={llm ? `Your endpoint: ${llm.baseUrl}` : health ? `Server model: ${health.model}` : undefined}
          variant={modelReady ? "ghost" : "primary"}
          size="sm"
          icon={<Settings2 size={16} />}
          onClick={() => setShowModel(true)}
        />
        {!isMobile && company && (
          <>
            <IconButton
              label={files.isCollapsed ? "Show files" : "Hide files"}
              tooltip={`${files.isCollapsed ? "Show" : "Hide"} files (Ctrl/⌘ B)`}
              icon={<PanelLeft size={16} />}
              variant="ghost"
              size="sm"
              onClick={() => toggle(files)}
            />
            <IconButton
              label={chat.isCollapsed ? "Show assistant" : "Hide assistant"}
              tooltip={`${chat.isCollapsed ? "Show" : "Hide"} assistant (Ctrl/⌘ J)`}
              icon={<PanelRight size={16} />}
              variant="ghost"
              size="sm"
              onClick={() => toggle(chat)}
            />
          </>
        )}
      </header>

      {!company ? (
        <div className="center-fill">
          <EmptyState
            title="Add your first client"
            description="Each client gets a standard folder structure (inbox, permanent file, one tree per financial year) and a profile the assistant reads first."
            icon={<Building2 size={32} />}
            actions={<Button label="New client" variant="primary" icon={<Plus size={16} />} onClick={() => setShowNew(true)} />}
          />
        </div>
      ) : isMobile ? (
        <div className="mobile">
          <div className="mobile-pane">
            <div hidden={pane !== "files"} className="pane-fill">{filesPanel}</div>
            <div hidden={pane !== "work"} className="pane-fill">{workPanel}</div>
            <div hidden={pane !== "chat"} className="pane-fill">{chatPanel}</div>
          </div>
          <nav className="mobile-nav" aria-label="Panels">
            <SegmentedControl label="Panel" value={pane} onChange={(v) => setPane(v as MobilePane)} layout="fill">
              <SegmentedControlItem value="files" label="Files" icon={<Files size={16} />} />
              <SegmentedControlItem value="work" label="Workspace" icon={<Calculator size={16} />} />
              <SegmentedControlItem value="chat" label="Assistant" icon={<MessagesSquare size={16} />} />
            </SegmentedControl>
          </nav>
        </div>
      ) : (
        <main className="panes">
          <aside className="pane side" style={{ width: files.isCollapsed ? 0 : files.size }} aria-label="Files" hidden={files.isCollapsed}>
            {filesPanel}
          </aside>
          <ResizeHandle direction="horizontal" resizable={files.props} label="Resize file panel" hasDivider />
          <div className="pane main">{workPanel}</div>
          <ResizeHandle direction="horizontal" resizable={chat.props} label="Resize assistant panel" isReversed hasDivider />
          <aside className="pane side" style={{ width: chat.isCollapsed ? 0 : chat.size }} aria-label="Assistant" hidden={chat.isCollapsed}>
            {chatPanel}
          </aside>
        </main>
      )}
      {showModel && <ModelSettings onClose={() => setShowModel(false)} />}
      <NewCompany
        isOpen={showNew}
        onClose={() => setShowNew(false)}
        onCreated={async (c) => {
          setShowNew(false);
          await loadCompanies(c.id);
        }}
      />
    </div>
  );
}

const ENTITY_TYPES = ["individual", "huf", "firm", "llp", "company", "trust", "aop"];
const GST_FILING = ["monthly", "qrmp", "composition", "none"];

function NewCompany({ isOpen, onClose, onCreated }: { isOpen: boolean; onClose: () => void; onCreated: (c: Company) => void }) {
  const blank = {
    name: "", entity_type: "company", pan: "", gstins: "", state: "", gst_filing: "monthly", tax_regime: "new",
    books_software: "Tally Prime", contact_name: "", contact_email: "", contact_phone: "", fy: currentFY(),
  };
  const [f, setF] = useState(blank);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof blank) => (v: string) => setF({ ...f, [k]: v });
  const fyValid = /^FY\d{4}-\d{2}$/.test(f.fy);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!f.name.trim() || !fyValid) return;
    setBusy(true);
    setErr(null);
    try {
      const c = await api.createCompany({
        ...f,
        pan: f.pan.toUpperCase() || null,
        gstins: f.gstins.split(/[\s,]+/).filter(Boolean).map((g) => g.toUpperCase()),
      } as never);
      setF(blank);
      onCreated(c);
    } catch (ex) {
      setErr((ex as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog isOpen={isOpen} onOpenChange={(o) => !o && onClose()} purpose="form" width={640} maxHeight="90dvh">
      <form onSubmit={submit}>
        <Layout
          header={<DialogHeader title="New client" subtitle="Creates the folder structure and a profile the assistant reads first." onOpenChange={onClose} />}
          content={
            <LayoutContent>
              <VStack gap={4}>
                <Grid columns={{ minWidth: 220 }} gap={3}>
                  <TextInput label="Name" isRequired value={f.name} onChange={set("name")} hasAutoFocus />
                  <Selector label="Entity type" options={ENTITY_TYPES} value={f.entity_type} onChange={set("entity_type")} />
                  <TextInput label="PAN" isOptional value={f.pan} onChange={set("pan")} placeholder="ABCDE1234F" />
                  <TextInput label="GSTIN(s)" isOptional value={f.gstins} onChange={set("gstins")} placeholder="Comma separated" />
                  <TextInput label="State" isOptional value={f.state} onChange={set("state")} />
                  <Selector label="GST filing" options={GST_FILING} value={f.gst_filing} onChange={set("gst_filing")} />
                  <Selector label="Tax regime" options={["new", "old"]} value={f.tax_regime} onChange={set("tax_regime")} />
                  <TextInput label="Books software" isOptional value={f.books_software} onChange={set("books_software")} />
                  <TextInput label="Contact name" isOptional value={f.contact_name} onChange={set("contact_name")} />
                  <TextInput label="Contact email" isOptional type="email" value={f.contact_email} onChange={set("contact_email")} />
                  <TextInput label="Contact phone" isOptional value={f.contact_phone} onChange={set("contact_phone")} />
                  <TextInput
                    label="Financial year"
                    value={f.fy}
                    onChange={set("fy")}
                    status={fyValid ? undefined : { type: "error", message: "Use the form FY2025-26" }}
                  />
                </Grid>
                {err && <Banner status="error" title="Could not create client" description={err} />}
              </VStack>
            </LayoutContent>
          }
          footer={
            <LayoutFooter>
              <HStack gap={2} justify="end">
                <Button label="Cancel" variant="ghost" onClick={onClose} />
                <Button label="Create client" variant="primary" type="submit" isLoading={busy} isDisabled={!f.name.trim() || !fyValid} />
              </HStack>
            </LayoutFooter>
          }
        />
      </form>
    </Dialog>
  );
}

function TokenGate({ onSaved }: { onSaved: () => void }) {
  const [t, setT] = useState(getToken());
  return (
    <div className="center-fill">
      <form className="gate" onSubmit={(e) => (e.preventDefault(), setToken(t), onSaved())}>
        <VStack gap={4}>
          <VStack gap={1}>
            <span className="logo lg">₹</span>
            <Text type="large" weight="semibold">Access token</Text>
            <Text type="supporting">This deployment is protected. Enter the APP_TOKEN configured on the server.</Text>
          </VStack>
          <TextInput label="Token" type="password" value={t} onChange={setT} hasAutoFocus width="100%" />
          <Button label="Continue" variant="primary" type="submit" isDisabled={!t} />
        </VStack>
      </form>
    </div>
  );
}

