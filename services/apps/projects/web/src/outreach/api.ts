// Must match projects_api/outreach.py STATE_LABELS.
export type OutState = "idea" | "prepared" | "opened" | "merged" | "closed";

export const OUT_STATE: Record<OutState, { label: string; color: string; hint: string }> = {
  idea: { label: "Идея", color: "var(--s-draft)", hint: "нашли, что чинить" },
  prepared: { label: "PR готов", color: "var(--s-inbound)", hint: "ждёт твоего ок" },
  opened: { label: "PR открыт", color: "var(--s-sent)", hint: "ждём ревью" },
  merged: { label: "PR принят", color: "var(--s-offer)", hint: "можно писать руководителю" },
  closed: { label: "Закрыт", color: "var(--s-closed)", hint: "" },
};
export const OUT_ORDER: OutState[] = ["idea", "prepared", "opened", "merged", "closed"];

// Must match projects_api/outreach.py STEP_ORDER / StepStatus.
export type StepStatus = "running" | "ok" | "fail" | "skip";
export const STEP_ORDER = ["clone", "reproduce", "fix", "test", "policy-check", "pr-text", "ready"] as const;
export const STEP_LABEL: Record<string, string> = {
  clone: "клон", reproduce: "воспроизвели", fix: "фикс", test: "тесты", docs: "доки", "policy-check": "политика",
  "pr-text": "текст PR", ready: "готово", blocked: "стоп",
};
export const STATUS_STYLE: Record<StepStatus, { color: string; label: string }> = {
  running: { color: "var(--s-sent)", label: "идёт" },
  ok: { color: "var(--s-offer)", label: "готово" },
  fail: { color: "#e5484d", label: "ошибка" },
  skip: { color: "var(--s-draft)", label: "пропуск" },
};
export type StepRef = { id: number; target_id: number; step: string; status: StepStatus; text: string; url: string; at: string };
export type FeedEvent = {
  id: number; target_id: number; company: string; kind: string; text: string; step: string | null;
  status: StepStatus | null; status_label: string; url: string; log: string; created_at: string;
};

export type Target = {
  id: number; company: string; url: string; careers_url: string; remote: "yes" | "no" | "unknown"; why: string;
  repos: string; finding: string; pr_url: string; pr_state: OutState; state_label: string; contact_role: string;
  contacted_at: string | null; reply: string; next_step: string; notes: string; created_at: string; updated_at: string;
  steps?: Record<string, StepStatus>; last_step?: StepRef | null;
};
export type TargetEvent = { id: number; kind: string; text: string; at: string; step?: string | null; status?: StepStatus | null; url?: string; log?: string };
export type TargetDetail = Target & { events: TargetEvent[] };
export type OutSummary = { counts: Record<OutState, number>; contacted: number; replied: number };
export type TargetIn = Partial<Omit<Target, "id" | "state_label" | "created_at" | "updated_at">> & { note?: string };

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method, headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error ?? r.statusText);
  return r.status === 204 ? (undefined as T) : r.json();
}

export const outreach = {
  summary: () => call<OutSummary>("GET", "/api/outreach/summary"),
  list: (state?: OutState, q?: string) => {
    const p = new URLSearchParams();
    if (state) p.set("state", state);
    if (q) p.set("q", q);
    const s = p.toString();
    return call<Target[]>("GET", `/api/outreach/targets${s ? `?${s}` : ""}`);
  },
  get: (id: number) => call<TargetDetail>("GET", `/api/outreach/targets/${id}`),
  create: (body: TargetIn & { company: string }) => call<Target>("POST", "/api/outreach/targets", body),
  patch: (id: number, body: TargetIn) => call<Target>("PATCH", `/api/outreach/targets/${id}`, body),
  remove: (id: number) => call<void>("DELETE", `/api/outreach/targets/${id}`),
  events: (since?: number, limit = 60) =>
    call<FeedEvent[]>("GET", `/api/outreach/events?limit=${limit}${since ? `&since=${since}` : ""}`),
};
