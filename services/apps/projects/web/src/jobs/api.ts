import type { Status } from "./model";

export type Platform = {
  slug: string; name: string; url: string; kind: string; notes: string; created_at: string;
  stats: { sent: number; inbound: number; replied: number; interviews: number; offers: number; reply_rate: number | null; median_reply_days: number | null };
};
export type Contact = {
  id: number; name: string; company: string; role: string; email: string; phone: string; telegram: string;
  linkedin: string; notes: string; created_at: string; updated_at: string; applications_count?: number;
};
export type Application = {
  id: number; company: string; title: string; url: string; platform: string | null; platform_name: string | null;
  origin: "outbound" | "inbound"; contact_id: number | null; contact_name: string | null;
  location: string; work_format: string; salary: string; fit: number | null; vacancy_text: string; vacancy_id: string | null;
  notes: string; status: Status; applied_at: string | null; next_action_at: string | null; next_action: string;
  replied_at: string | null; interview_at: string | null; created_at: string; updated_at: string;
  letters_count: number; letter_sent: number; files_count: number;
};
export type Letter = {
  id: number; application_id: number; lang: string; body: string; status: "pending" | "ready" | "failed"; wish: string;
  error: string | null; sent: boolean; source: "generated" | "manual" | "imported"; created_at: string; updated_at: string;
};
export type FileMeta = { id: number; name: string; mime: string; size: number; created_at: string };
export type JobEvent = { id: number; kind: string; text: string; at: string };
export type ApplicationDetail = Application & { contact: Contact | null; letters: Letter[]; attachments: FileMeta[]; events: JobEvent[] };
export type Summary = { due: Application[]; silent: Application[]; counts: Record<Status, number>; sent_this_week: number; letters_pending: number };

export type ContactIn = Partial<Omit<Contact, "id" | "created_at" | "updated_at" | "applications_count">> & { name: string };
export type ApplicationIn = Partial<Omit<Application, "id" | "platform_name" | "contact_name" | "letters_count" | "letter_sent" | "files_count">> & {
  company: string; title: string; contact?: ContactIn; generate?: { lang: string; wish: string };
};

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method, headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error ?? r.statusText);
  return r.status === 204 ? (undefined as T) : r.json();
}

const qs = (p: Record<string, string | undefined>) => {
  const s = new URLSearchParams(Object.entries(p).filter(([, v]) => v) as [string, string][]).toString();
  return s ? `?${s}` : "";
};

export const jobs = {
  summary: () => call<Summary>("GET", "/api/jobs/summary"),
  list: (f: { status?: string; platform?: string; origin?: string; q?: string } = {}) =>
    call<Application[]>("GET", `/api/jobs/applications${qs(f)}`),
  get: (id: number) => call<ApplicationDetail>("GET", `/api/jobs/applications/${id}`),
  create: (body: ApplicationIn) => call<Application>("POST", "/api/jobs/applications", body),
  patch: (id: number, body: Partial<ApplicationIn> & { note?: string }) => call<Application>("PATCH", `/api/jobs/applications/${id}`, body),
  remove: (id: number) => call<void>("DELETE", `/api/jobs/applications/${id}`),

  addLetter: (id: number, body: { lang: string; body: string }) => call<Letter>("POST", `/api/jobs/applications/${id}/letters`, body),
  generate: (id: number, body: { lang: string; wish: string }) => call<Letter>("POST", `/api/jobs/applications/${id}/letters/generate`, body),
  letter: (id: number) => call<Letter & { versions: { id: number; body: string; created_at: string }[] }>("GET", `/api/jobs/letters/${id}`),
  patchLetter: (id: number, body: { body?: string; lang?: string; sent?: boolean }) => call<Letter>("PATCH", `/api/jobs/letters/${id}`, body),
  removeLetter: (id: number) => call<void>("DELETE", `/api/jobs/letters/${id}`),
  retry: (id: number) => call<Letter>("POST", `/api/jobs/letters/${id}/retry`),

  upload: async (id: number, file: File) => {
    const r = await fetch(`/api/jobs/applications/${id}/files?name=${encodeURIComponent(file.name)}`, { method: "PUT", body: file });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error ?? r.statusText);
    return r.json() as Promise<FileMeta>;
  },
  removeFile: (id: number) => call<void>("DELETE", `/api/jobs/files/${id}`),

  contacts: () => call<Contact[]>("GET", "/api/jobs/contacts"),
  contact: (id: number) => call<Contact & { applications: Application[] }>("GET", `/api/jobs/contacts/${id}`),
  createContact: (body: ContactIn) => call<Contact>("POST", "/api/jobs/contacts", body),
  patchContact: (id: number, body: Partial<ContactIn>) => call<Contact>("PATCH", `/api/jobs/contacts/${id}`, body),
  removeContact: (id: number) => call<void>("DELETE", `/api/jobs/contacts/${id}`),

  platforms: () => call<Platform[]>("GET", "/api/jobs/platforms"),
  createPlatform: (body: { slug: string; name: string; url?: string; kind?: string; notes?: string }) => call<Platform>("POST", "/api/jobs/platforms", body),
  patchPlatform: (slug: string, body: { name?: string; url?: string; notes?: string; kind?: string }) => call<Platform>("PATCH", `/api/jobs/platforms/${slug}`, body),
};
