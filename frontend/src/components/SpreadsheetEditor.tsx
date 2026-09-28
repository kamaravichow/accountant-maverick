import { useEffect, useRef, useState } from "react";
import { Workbook, type WorkbookInstance } from "@fortune-sheet/react";
import "@fortune-sheet/react/dist/index.css";
import type { Sheet } from "@fortune-sheet/core";
import { api } from "../lib/api";
import { type LoadedBook, loadCsv, loadXlsx, saveXlsx, toCsv } from "../lib/xlsx";

type Props = { companyId: string; path: string; onSaved?: () => void; onAsk?: (q: string) => void };

export default function SpreadsheetEditor({ companyId, path, onSaved, onAsk }: Props) {
  const [book, setBook] = useState<LoadedBook | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");
  const [dirty, setDirty] = useState(false);
  const [version, setVersion] = useState(0);
  const ref = useRef<WorkbookInstance>(null);
  const isCsv = path.toLowerCase().endsWith(".csv");

  async function load() {
    setError(null);
    setBook(null);
    try {
      const buf = await api.fetchBytes(companyId, path);
      setBook(isCsv ? loadCsv(new TextDecoder().decode(buf)) : await loadXlsx(buf));
      setDirty(false);
      setVersion((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, path]);

  async function save() {
    if (!book || !ref.current) return;
    setStatus("Saving…");
    try {
      const sheets = ref.current.getAllSheets() as Sheet[];
      if (isCsv) {
        await api.saveBytes(companyId, path, new Blob([toCsv(sheets[0])]), "text/csv");
      } else {
        const buf = await saveXlsx(sheets, book.workbook);
        await api.saveBytes(companyId, path, buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
      }
      setDirty(false);
      setStatus(`Saved ${new Date().toLocaleTimeString()}`);
      onSaved?.();
    } catch (e) {
      setStatus(`Save failed: ${(e as Error).message}`);
    }
  }

  function askAboutSelection() {
    const coords = ref.current?.getSelectionCoordinates?.() ?? [];
    const sheet = ref.current?.getSheet?.()?.name;
    onAsk?.(`In ${path}${sheet ? ` [${sheet}]` : ""}${coords.length ? ` range ${coords.join(", ")}` : ""}: `);
  }

  if (error) return <div className="empty">Could not open spreadsheet: {error}</div>;
  if (!book) return <div className="empty">Loading spreadsheet…</div>;
  return (
    <div className="sheet-wrap">
      <div className="toolbar">
        <strong className="path" title={path}>{path.split("/").pop()}</strong>
        <span className="muted small">Live formulas • edits stay local until saved</span>
        <span className="spacer" />
        {status && <span className="muted small">{status}</span>}
        {onAsk && <button className="ghost" onClick={askAboutSelection}>Ask agent about selection</button>}
        <button className="ghost" onClick={load} title="Reload from storage (e.g. after the agent edited it)">Reload</button>
        <a className="button ghost" href={api.fileUrl(companyId, path, true)}>Download</a>
        <button onClick={save} disabled={!dirty}>Save</button>
      </div>
      <div className="sheet-host">
        <Workbook
          key={`${path}:${version}`}
          ref={ref}
          data={book.sheets}
          onChange={() => setDirty(true)}
          showFormulaBar
          allowEdit
        />
      </div>
    </div>
  );
}
