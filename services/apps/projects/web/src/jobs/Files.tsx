import { useRef, useState } from "react";
import { FileText, Image, Trash2, Upload } from "lucide-react";
import { jobs, type FileMeta } from "./api";
import { Ghost } from "./ui";

const size = (n: number) => (n < 1024 ? `${n} Б` : n < 1048576 ? `${Math.round(n / 1024)} КБ` : `${(n / 1048576).toFixed(1)} МБ`);
export const ACCEPT = ".pdf,.docx,.txt,.md,.html,.png,.jpg,.jpeg,.webp";

/** Drop zone + file list. `upload` lets the new-application form queue files before the application exists. */
export function DropZone({ onFiles, compact }: { onFiles: (f: File[]) => void; compact?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); onFiles([...e.dataTransfer.files]); }}
      onClick={() => input.current?.click()} role="button" tabIndex={0}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
      className={`flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-dashed text-sm transition ${compact ? "px-3 py-2.5" : "px-4 py-6"} ${over ? "border-accent bg-accent/5 text-accent" : "border-line text-muted hover:border-accent/60 hover:text-fg"}`}>
      <Upload size={15} />Перетащи файл или нажми · PDF, DOCX, скриншот
      <input ref={input} type="file" multiple accept={ACCEPT} className="hidden"
        onChange={(e) => { onFiles([...(e.target.files ?? [])]); e.target.value = ""; }} />
    </div>
  );
}

export function FileRow({ f, onRemove, href }: { f: Pick<FileMeta, "name" | "size" | "mime">; onRemove: () => void; href?: string }) {
  const Icon = f.mime.startsWith("image/") ? Image : FileText;
  const name = <span className="truncate">{f.name}</span>;
  return (
    <div className="group flex items-center gap-2 rounded-lg px-1.5 py-1 text-sm hover:bg-hover">
      <Icon size={15} className="shrink-0 text-muted" />
      {href ? <a href={href} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate hover:text-accent">{name}</a> : <span className="min-w-0 flex-1 truncate">{name}</span>}
      <span className="shrink-0 text-xs text-muted">{size(f.size)}</span>
      <Ghost className="px-1 opacity-60 group-hover:opacity-100" title="Удалить файл" onClick={onRemove}><Trash2 size={13} /></Ghost>
    </div>
  );
}

export default function Files({ appId, files, onChange }: { appId: number; files: FileMeta[]; onChange: () => void }) {
  const [busy, setBusy] = useState(0);
  const [error, setError] = useState("");
  async function add(list: File[]) {
    setError("");
    for (const f of list) {
      setBusy((n) => n + 1);
      try { await jobs.upload(appId, f); } catch (e) { setError(`${f.name}: ${e}`); } finally { setBusy((n) => n - 1); }
    }
    onChange();
  }
  return (
    <div className="space-y-2">
      {files.map((f) => (
        <FileRow key={f.id} f={f} href={`/api/jobs/files/${f.id}`}
          onRemove={() => confirm(`Удалить «${f.name}»?`) && jobs.removeFile(f.id).then(onChange)} />
      ))}
      <DropZone onFiles={add} compact={files.length > 0} />
      {busy > 0 && <p className="text-xs text-accent">Загружаю…</p>}
      {error && <p className="text-xs text-amber-fg">{error}</p>}
    </div>
  );
}
