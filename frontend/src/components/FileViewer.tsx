import { lazy, Suspense, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Toolbar } from "@astryxdesign/core/Toolbar";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { Download, FileSearch, Receipt } from "lucide-react";
import { api } from "../lib/api";
import { Loading } from "./Loading";
// FortuneSheet + ExcelJS are large; load them only when a spreadsheet is opened.
const SpreadsheetEditor = lazy(() => import("./SpreadsheetEditor"));

type Props = { companyId: string; path: string; onAsk: (q: string) => void; onChanged: () => void };

const ext = (p: string) => p.toLowerCase().split(".").pop() ?? "";

export default function FileViewer({ companyId, path, onAsk, onChanged }: Props) {
  const e = ext(path);
  if (["xlsx", "xlsm", "csv"].includes(e))
    return (
      <Suspense fallback={<Loading text="Loading spreadsheet editor…" />}>
        <SpreadsheetEditor companyId={companyId} path={path} onSaved={onChanged} onAsk={onAsk} />
      </Suspense>
    );
  const url = api.fileUrl(companyId, path);
  const actions = (
    <Toolbar
      label="Document actions"
      size="sm"
      dividers={["bottom"]}
      startContent={<Text type="label" weight="semibold" maxLines={1}>{path.split("/").pop()}</Text>}
      endContent={
        <>
          {["pdf", "png", "jpg", "jpeg", "webp"].includes(e) && (
            <>
              <Button label="Extract invoice" icon={<Receipt size={16} />} variant="ghost" onClick={() => onAsk(`Extract this invoice into the purchase register: ${path}`)} />
              <Button label="Summarise" icon={<FileSearch size={16} />} variant="ghost" onClick={() => onAsk(`Read ${path} and summarise what it is and what I need to do.`)} />
            </>
          )}
          <Button label="Download" icon={<Download size={16} />} variant="secondary" href={api.fileUrl(companyId, path, true)} />
        </>
      }
    />
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
  if (text === null) return <Loading text="Loading…" />;
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

