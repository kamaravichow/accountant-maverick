import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { TreeList } from "@astryxdesign/core/TreeList";
import type { TreeListItemData } from "@astryxdesign/core/TreeList";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Button } from "@astryxdesign/core/Button";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { Text } from "@astryxdesign/core/Text";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Toolbar } from "@astryxdesign/core/Toolbar";
import {
  File, FileImage, FileJson, FileSpreadsheet, FileText, Folder, FolderOpen, FolderPlus, Inbox, Pencil, Sparkles, Trash2, Upload, Wand2,
} from "lucide-react";
import { api, type Entry, fmtSize } from "../lib/api";
import { useDialogs } from "./dialogs";

type Props = {
  companyId: string;
  refreshKey: number;
  selected: string | null;
  onOpen: (path: string) => void;
  onAsk: (q: string) => void;
  onChanged: () => void;
};

const ext = (name: string) => name.toLowerCase().split(".").pop() ?? "";

export function fileIcon(name: string, size = 16): ReactNode {
  const e = ext(name);
  if (["xlsx", "xlsm", "csv"].includes(e)) return <FileSpreadsheet size={size} className="ico-sheet" />;
  if (["png", "jpg", "jpeg", "webp", "gif"].includes(e)) return <FileImage size={size} className="ico-image" />;
  if (e === "json") return <FileJson size={size} className="ico-muted" />;
  if (["pdf", "md", "txt"].includes(e)) return <FileText size={size} className={e === "pdf" ? "ico-pdf" : "ico-muted"} />;
  return <File size={size} className="ico-muted" />;
}

const parentOf = (p: string) => p.split("/").slice(0, -1).join("/");

// Rendered as the only child of a folder whose contents haven't been fetched yet. TreeList
// only mounts children of expanded rows, so mounting this is the signal to load the folder.
function LazyLoad({ onMount }: { onMount: () => void }) {
  useEffect(onMount, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <span className="tree-loading">
      <Spinner size="sm" /> <Text type="supporting">Loading…</Text>
    </span>
  );
}

export default function FileExplorer({ companyId, refreshKey, selected, onOpen, onAsk, onChanged }: Props) {
  const dialogs = useDialogs();
  const [tree, setTree] = useState<Record<string, Entry[]>>({});
  const [folder, setFolder] = useState<string>("_inbox");
  const [busy, setBusy] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const loaded = useRef(new Set<string>());

  const load = useCallback(
    async (path: string) => {
      loaded.current.add(path);
      const entries = await api.list(companyId, path);
      setTree((t) => ({ ...t, [path]: entries }));
    },
    [companyId],
  );

  useEffect(() => {
    setTree({});
    loaded.current = new Set();
    load("").catch(() => undefined);
  }, [companyId, load]);

  useEffect(() => {
    if (refreshKey) loaded.current.forEach((p) => load(p).catch(() => undefined));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  async function upload(files: FileList | File[], target: string) {
    const list = Array.from(files);
    if (!list.length) return;
    setBusy(`Uploading ${list.length} file${list.length > 1 ? "s" : ""} to ${target || "/"}…`);
    try {
      await api.upload(companyId, target, list);
      await load(target);
      onChanged();
      dialogs.notify(`Uploaded ${list.length} file${list.length > 1 ? "s" : ""} to ${target || "/"}`);
    } catch (e) {
      dialogs.notify((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function newFolder() {
    const name = await dialogs.prompt({ title: "New folder", label: "Folder name", description: `Inside ${folder || "/"}`, actionLabel: "Create folder" });
    if (!name) return;
    try {
      await api.mkdir(companyId, folder ? `${folder}/${name}` : name);
      await load(folder);
    } catch (e) {
      dialogs.notify((e as Error).message, "error");
    }
  }

  async function rename(e: Entry) {
    const dest = await dialogs.prompt({ title: `Move or rename`, label: "New path", initial: e.path, actionLabel: "Move" });
    if (!dest || dest === e.path) return;
    try {
      await api.move(companyId, e.path, dest);
      await Promise.all([load(parentOf(e.path)), load(parentOf(dest))]);
      onChanged();
    } catch (err) {
      dialogs.notify((err as Error).message, "error");
    }
  }

  async function remove(e: Entry) {
    const ok = await dialogs.confirm({
      title: `Delete ${e.name}?`,
      description: `${e.path}${e.is_dir ? " and everything inside it" : ""} will be permanently deleted. This cannot be undone.`,
      actionLabel: e.is_dir ? "Delete folder" : "Delete file",
    });
    if (!ok) return;
    try {
      await api.remove(companyId, e.path);
      await load(parentOf(e.path));
      onChanged();
    } catch (err) {
      dialogs.notify((err as Error).message, "error");
    }
  }

  const dropProps = (target: string) => ({
    onDragOver: (ev: React.DragEvent) => {
      if (!ev.dataTransfer.types.includes("Files")) return;
      ev.preventDefault();
      ev.stopPropagation();
      setDragOver(target);
    },
    onDragLeave: () => setDragOver((d) => (d === target ? null : d)),
    onDrop: (ev: React.DragEvent) => {
      ev.preventDefault();
      ev.stopPropagation();
      setDragOver(null);
      upload(ev.dataTransfer.files, target);
    },
  });

  function toItems(path: string): TreeListItemData[] {
    const entries = tree[path];
    if (!entries) return [{ id: `${path}/__loading`, label: <LazyLoad onMount={() => load(path).catch(() => undefined)} />, isDisabled: true }];
    if (!entries.length) return [{ id: `${path}/__empty`, label: <Text type="supporting">Empty — drop files here</Text>, isDisabled: true }];
    return entries.map((e) => {
      const menu = (
        <span className="row-menu" onClick={(ev) => ev.stopPropagation()}>
          <MoreMenu
            label={`Actions for ${e.name}`}
            size="sm"
            alignment="end"
            items={[
              ...(!e.is_dir ? [{ label: "Ask assistant about this", icon: <Sparkles size={16} />, onClick: () => onAsk(`Look at ${e.path} and `) }] : []),
              ...(e.is_dir ? [{ label: "Upload here", icon: <Upload size={16} />, onClick: () => (setFolder(e.path), inputRef.current?.click()) }] : []),
              { label: "Move or rename", icon: <Pencil size={16} />, onClick: () => rename(e) },
              ...(!e.path.startsWith("_context")
                ? [{ type: "divider" as const }, { label: "Delete", icon: <Trash2 size={16} />, variant: "destructive" as const, onClick: () => remove(e) }]
                : []),
            ]}
          />
        </span>
      );
      const label = (
        <span
          className={`tree-label${dragOver === e.path ? " drop" : ""}${e.name.startsWith("_") ? " system" : ""}`}
          title={e.path}
          {...(e.is_dir ? dropProps(e.path) : {})}
        >
          {e.name}
        </span>
      );
      if (e.is_dir)
        return {
          id: e.path,
          label,
          startContent: e.path === "_inbox" ? <Inbox size={16} className="ico-folder" /> : folder === e.path ? <FolderOpen size={16} className="ico-folder" /> : <Folder size={16} className="ico-folder" />,
          endContent: menu,
          isSelected: folder === e.path && !selected?.startsWith(e.path + "/"),
          children: toItems(e.path),
          className: "tree-row",
        };
      return {
        id: e.path,
        label,
        startContent: fileIcon(e.name),
        endContent: (
          <span className="tree-end">
            <Text type="supporting" size="xsm" hasTabularNumbers>{fmtSize(e.size)}</Text>
            {menu}
          </span>
        ),
        isSelected: selected === e.path,
        onClick: () => {
          setFolder(parentOf(e.path));
          onOpen(e.path);
        },
        className: "tree-row",
      };
    });
  }

  // Folder rows toggle on click (TreeList default); track the last-clicked folder as the upload target.
  const onTreeClick = (ev: React.MouseEvent) => {
    const row = (ev.target as HTMLElement).closest("[role=treeitem]");
    const label = row?.querySelector(".tree-label") as HTMLElement | null;
    const path = label?.title;
    if (path && tree[parentOf(path)]?.find((x) => x.path === path)?.is_dir) setFolder(path);
  };

  return (
    <div className={`explorer${dragOver === "__root" ? " drop" : ""}`} {...dropProps(folder)} onDragEnter={() => setDragOver((d) => d ?? "__root")}>
      <Toolbar
        label="File actions"
        size="sm"
        dividers={["bottom"]}
        startContent={<Text type="label" weight="semibold">Files</Text>}
        endContent={
          <>
            <IconButton label="New folder" tooltip={`New folder in ${folder || "/"}`} icon={<FolderPlus size={16} />} variant="ghost" onClick={newFolder} />
            <Button label="Upload" icon={<Upload size={16} />} variant="secondary" onClick={() => inputRef.current?.click()} tooltip={`Upload to ${folder || "/"}`} />
          </>
        }
      />
      <input ref={inputRef} type="file" multiple hidden onChange={(e) => (e.target.files && upload(e.target.files, folder), (e.target.value = ""))} />
      <div className="explorer-target">
        <Text type="supporting" size="xsm">Uploads go to</Text> <code title={folder || "/"}>{folder || "/"}</code>
      </div>
      {busy && (
        <div className="explorer-busy">
          <Spinner size="sm" /> <Text type="supporting">{busy}</Text>
        </div>
      )}
      <div className="tree-scroll" onClick={onTreeClick}>
        {tree[""] ? (
          <TreeList key={companyId} items={toItems("")} density="compact" aria-label="Client files" />
        ) : (
          <div className="tree-loading"><Spinner size="sm" /> <Text type="supporting">Loading files…</Text></div>
        )}
      </div>
      <div className="explorer-foot">
        <Text type="supporting">Drop client documents anywhere here, or into a folder.</Text>
        <Button
          label="Organise inbox"
          icon={<Wand2 size={16} />}
          variant="secondary"
          size="sm"
          width="100%"
          onClick={() => onAsk("Classify and file everything in _inbox. Show me the plan first.")}
        />
      </div>
    </div>
  );
}
