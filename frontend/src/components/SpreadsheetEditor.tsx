import { useEffect, useRef, useState } from "react";
import { Workbook, type WorkbookInstance } from "@fortune-sheet/react";
import "@fortune-sheet/react/dist/index.css";
import type { Sheet } from "@fortune-sheet/core";
import { Toolbar } from "@astryxdesign/core/Toolbar";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Download, RefreshCw, Save, Sparkles } from "lucide-react";
import { api } from "../lib/api";
import { Loading } from "./Loading";
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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (dirty) save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  function askAboutSelection() {
    const coords = ref.current?.getSelectionCoordinates?.() ?? [];
    const sheet = ref.current?.getSheet?.()?.name;
    onAsk?.(`In ${path}${sheet ? ` [${sheet}]` : ""}${coords.length ? ` range ${coords.join(", ")}` : ""}: `);
  }

  if (error)
    return (
      <div className="center-fill">
        <EmptyState title="Could not open spreadsheet" description={error} actions={<Button label="Try again" onClick={load} />} />
      </div>
    );
  if (!book) return <Loading text="Loading spreadsheet…" />;
  return (
    <div className="sheet-wrap">
      <Toolbar
        label="Spreadsheet actions"
        size="sm"
        dividers={["bottom"]}
        startContent={
          <span className="sheet-title">
            <Text type="label" weight="semibold" maxLines={1}>{path.split("/").pop()}</Text>
            <Text type="supporting" size="xsm">{status || (dirty ? "Unsaved changes" : "Live formulas · edits stay local until saved")}</Text>
          </span>
        }
        endContent={
          <>
            {onAsk && <Button label="Ask about selection" icon={<Sparkles size={16} />} variant="ghost" onClick={askAboutSelection} />}
            <IconButton label="Reload" tooltip="Reload from storage (e.g. after the assistant edited it)" icon={<RefreshCw size={16} />} variant="ghost" onClick={load} />
            <IconButton label="Download" tooltip="Download" icon={<Download size={16} />} variant="ghost" onClick={() => window.open(api.fileUrl(companyId, path, true), "_self")} />
            <Button label="Save" icon={<Save size={16} />} variant="primary" onClick={save} isDisabled={!dirty} tooltip="Save (Ctrl/⌘ S)" />
          </>
        }
      />
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
