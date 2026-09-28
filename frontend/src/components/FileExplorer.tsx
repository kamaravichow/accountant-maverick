import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Entry, fmtSize } from "../lib/api";

type Props = {
  companyId: string;
  refreshKey: number;
  selected: string | null;
  onOpen: (path: string) => void;
  onAsk: (q: string) => void;
  onChanged: () => void;
};

const ICON: Record<string, string> = { pdf: "📄", xlsx: "📊", xlsm: "📊", csv: "📊", json: "🧾", png: "🖼", jpg: "🖼", jpeg: "🖼", md: "📝", txt: "📝" };
const icon = (e: Entry) => (e.is_dir ? "📁" : ICON[e.name.toLowerCase().split(".").pop() ?? ""] ?? "📎");

export default function FileExplorer({ companyId, refreshKey, selected, onOpen, onAsk, onChanged }: Props) {
  const [tree, setTree] = useState<Record<string, Entry[]>>({});
  const [open, setOpen] = useState<Set<string>>(new Set([""]));
  const [folder, setFolder] = useState<string>("_inbox");
  const [busy, setBusy] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(
    async (path: string) => {
      const entries = await api.list(companyId, path);
      setTree((t) => ({ ...t, [path]: entries }));
    },
    [companyId],
  );

  useEffect(() => {
    setTree({});
    setOpen(new Set([""]));
    load("").catch(() => undefined);
  }, [companyId, load]);

  useEffect(() => {
    open.forEach((p) => load(p).catch(() => undefined));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  function toggle(path: string) {
    const next = new Set(open);
    if (next.has(path)) next.delete(path);
    else {
      next.add(path);
      if (!tree[path]) load(path).catch(() => undefined);
    }
    setOpen(next);
    setFolder(path);
  }

  async function upload(files: FileList | File[], target: string) {
    const list = Array.from(files);
    if (!list.length) return;
    setBusy(`Uploading ${list.length} file(s) to ${target || "/"}…`);
    try {
      await api.upload(companyId, target, list);
      await load(target);
      setOpen((o) => new Set(o).add(target));
      onChanged();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function newFolder() {
    const name = prompt(`New folder inside ${folder || "/"}`);
    if (!name) return;
    await api.mkdir(companyId, folder ? `${folder}/${name}` : name);
    await load(folder);
  }

  async function rename(e: Entry) {
    const dest = prompt("Move / rename to (full path):", e.path);
    if (!dest || dest === e.path) return;
    try {
      await api.move(companyId, e.path, dest);
      const parent = (p: string) => p.split("/").slice(0, -1).join("/");
      await Promise.all([load(parent(e.path)), load(parent(dest))]);
      onChanged();
    } catch (err) {
      alert((err as Error).message);
    }
  }

  async function remove(e: Entry) {
    if (!confirm(`Delete ${e.path}${e.is_dir ? " and everything inside it" : ""}? This cannot be undone.`)) return;
    try {
      await api.remove(companyId, e.path);
      await load(e.path.split("/").slice(0, -1).join("/"));
      onChanged();
    } catch (err) {
      alert((err as Error).message);
    }
  }

  function renderLevel(path: string, depth: number) {
    const entries = tree[path];
    if (!entries) return <div className="tree-row muted" style={{ paddingLeft: 12 + depth * 14 }}>…</div>;
    if (!entries.length) return <div className="tree-row muted small" style={{ paddingLeft: 12 + depth * 14 }}>empty — drop files here</div>;
    return entries.map((e) => (
      <div key={e.path}>
        <div
          className={`tree-row${selected === e.path ? " active" : ""}${dragOver === e.path ? " drop" : ""}${folder === e.path ? " folder-active" : ""}`}
          style={{ paddingLeft: 8 + depth * 14 }}
          onClick={() => (e.is_dir ? toggle(e.path) : onOpen(e.path))}
          onDragOver={(ev) => {
            if (!e.is_dir) return;
            ev.preventDefault();
            setDragOver(e.path);
          }}
          onDragLeave={() => setDragOver(null)}
          onDrop={(ev) => {
            if (!e.is_dir) return;
            ev.preventDefault();
            ev.stopPropagation();
            setDragOver(null);
            upload(ev.dataTransfer.files, e.path);
          }}
          title={e.path}
        >
          <span className="caret">{e.is_dir ? (open.has(e.path) ? "▾" : "▸") : ""}</span>
          <span className="ico">{icon(e)}</span>
          <span className={`name${e.name.startsWith("_") ? " system" : ""}`}>{e.name}</span>
          {!e.is_dir && <span className="size">{fmtSize(e.size)}</span>}
          <span className="row-actions" onClick={(ev) => ev.stopPropagation()}>
            {!e.is_dir && <button className="icon" title="Ask the agent about this file" onClick={() => onAsk(`Look at ${e.path} and `)}>✦</button>}
            <button className="icon" title="Move / rename" onClick={() => rename(e)}>✎</button>
            {!e.path.startsWith("_context") && <button className="icon" title="Delete" onClick={() => remove(e)}>✕</button>}
          </span>
        </div>
        {e.is_dir && open.has(e.path) && renderLevel(e.path, depth + 1)}
      </div>
    ));
  }

  return (
    <div
      className="explorer"
      onDragOver={(ev) => ev.preventDefault()}
      onDrop={(ev) => {
        ev.preventDefault();
        upload(ev.dataTransfer.files, folder);
      }}
    >
      <div className="explorer-head">
        <span className="muted small" title="Uploads go to this folder">Target: <code>{folder || "/"}</code></span>
        <span className="spacer" />
        <button className="ghost small" onClick={newFolder}>+ Folder</button>
        <button className="small" onClick={() => inputRef.current?.click()}>Upload</button>
        <input ref={inputRef} type="file" multiple hidden onChange={(e) => e.target.files && upload(e.target.files, folder)} />
      </div>
      {busy && <div className="banner">{busy}</div>}
      <div className="tree">{renderLevel("", 0)}</div>
      <div className="explorer-foot muted small">
        Drop client documents into <code>_inbox</code> and ask the agent to file them.
        <button className="link" onClick={() => onAsk("Classify and file everything in _inbox. Show me the plan first.")}>Organise inbox</button>
      </div>
    </div>
  );
}
