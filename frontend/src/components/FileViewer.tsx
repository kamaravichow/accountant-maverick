import { lazy, Suspense, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../lib/api";
// FortuneSheet + ExcelJS are large; load them only when a spreadsheet is opened.
const SpreadsheetEditor = lazy(() => import("./SpreadsheetEditor"));

type Props = { companyId: string; path: string; onAsk: (q: string) => void; onChanged: () => void };

const ext = (p: string) => p.toLowerCase().split(".").pop() ?? "";

export default function FileViewer({ companyId, path, onAsk, onChanged }: Props) {
  const e = ext(path);
  if (["xlsx", "xlsm", "csv"].includes(e))
    return (
      <Suspense fallback={<div className="empty">Loading spreadsheet editor…</div>}>
        <SpreadsheetEditor companyId={companyId} path={path} onSaved={onChanged} onAsk={onAsk} />
      </Suspense>
    );
  const url = api.fileUrl(companyId, path);
  const actions = (
    <div className="toolbar">
      <strong className="path" title={path}>{path.split("/").pop()}</strong>
      <span className="spacer" />
      {["pdf", "png", "jpg", "jpeg", "webp"].includes(e) && (
        <>
          <button className="ghost" onClick={() => onAsk(`Extract this invoice into the purchase register: ${path}`)}>Extract invoice</button>
          <button className="ghost" onClick={() => onAsk(`Read ${path} and summarise what it is and what I need to do.`)}>Summarise</button>
        </>
      )}
      <a className="button ghost" href={api.fileUrl(companyId, path, true)}>Download</a>
    </div>
  );
  if (e === "pdf")
    return (
      <div className="viewer">
        {actions}
        <iframe title={path} src={url} className="frame" />
      </div>
    );
  if (["png", "jpg", "jpeg", "webp", "gif"].includes(e))
    return (
      <div className="viewer">
        {actions}
        <div className="image-host"><img src={url} alt={path} /></div>
      </div>
    );
  return (
    <div className="viewer">
      {actions}
      <TextFile companyId={companyId} path={path} markdown={e === "md"} />
    </div>
  );
}

function TextFile({ companyId, path, markdown }: { companyId: string; path: string; markdown: boolean }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    api
      .fetchBytes(companyId, path)
      .then((b) => setText(new TextDecoder().decode(b.slice(0, 2_000_000))))
      .catch((err) => setText(`Error: ${err.message}`));
  }, [companyId, path]);
  if (text === null) return <div className="empty">Loading…</div>;
  if (markdown)
    return (
      <div className="doc md">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
    );
  let pretty = text;
  if (path.endsWith(".json")) {
    try {
      pretty = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      /* raw */
    }
  }
  return <pre className="doc">{pretty}</pre>;
}
