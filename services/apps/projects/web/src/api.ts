import type { ItemType } from "./types";

export type Project = {
  slug: string; title: string; area: string; status: string; summary: string; next_step: string;
  progress: number | null; progress_override: number | null; created_at: string; updated_at: string;
  open_user_todos: number; open_todos: number;
};
export type Item = {
  id: number; project: string; type: ItemType; title: string; body: string; status: string; owner: string | null;
  location: string | null; location_kind: string | null; parent_id: number | null; position: number;
  created_at: string; updated_at: string; done_at: string | null; progress: number | null; session_count: number;
  project_title?: string;
};
export type Small = { id: number; type: ItemType; title: string; status: string; project: string };
export type Ev = { id: number; item_id: number | null; item_type: string | null; session_id: string | null; ts: string; kind: string; text: string };
export type Session = {
  id: string; project: string | null; title: string; cwd: string; first_prompt: string;
  started_at: string | null; ended_at: string | null; user_turns: number; files_changed: string[];
};
export type Card = Project & { items: Item[]; events: Ev[]; sessions: (Session & { items: (Small & { roles: string[] })[] })[] };
export type ItemDetail = Item & {
  parent: Small | null; children: Item[];
  relations: { direction: "out" | "in"; kind: string; item: Small }[];
  sessions: (Pick<Session, "id" | "title" | "first_prompt" | "cwd" | "started_at" | "ended_at"> & { roles: string[] })[];
  events: Ev[];
};
export type SessionDetail = Session & { items: (Small & { roles: string[] })[] };
export type SearchGroup = { project: string; title: string; hits: { type: string; id: number | string; text: string; ts: string }[] };

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method, headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error ?? r.statusText);
  return r.status === 204 ? (undefined as T) : r.json();
}

export const api = {
  projects: () => call<Project[]>("GET", "/api/projects"),
  project: (slug: string) => call<Card>("GET", `/api/projects/${slug}`),
  item: (id: number) => call<ItemDetail>("GET", `/api/items/${id}`),
  patchItem: (id: number, body: { status?: string; owner?: string }) => call<Item>("PATCH", `/api/items/${id}`, body),
  userTodos: () => call<Item[]>("GET", "/api/todos?owner=user"),
  unsorted: () => call<Session[]>("GET", "/api/sessions?unsorted=1"),
  session: (id: string) => call<SessionDetail>("GET", `/api/sessions/${id}`),
  attach: (id: string, project: string) => call<Session>("PATCH", `/api/sessions/${id}`, { project }),
  addPathMap: (prefix: string, project: string) => call("POST", "/api/path-map", { prefix, project }),
  search: (q: string) => call<SearchGroup[]>("GET", `/api/search?q=${encodeURIComponent(q)}`),
};
