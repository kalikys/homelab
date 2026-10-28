const rtf = new Intl.RelativeTimeFormat("ru", { numeric: "auto" });
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31557600], ["month", 2629800], ["week", 604800], ["day", 86400], ["hour", 3600], ["minute", 60], ["second", 1],
];

export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const s = (new Date(iso).getTime() - Date.now()) / 1000;
  const [unit, size] = UNITS.find(([, size]) => Math.abs(s) >= size) ?? ["second", 1];
  return rtf.format(Math.round(s / size), unit);
}

/** Compact "how long ago" for list rows: 5 мин, 3 ч, вчера, 4 дн, 12 окт. */
export function agoShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "сейчас";
  if (s < 3600) return `${Math.floor(s / 60)} мин`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч`;
  if (s < 172800) return "вчера";
  if (s < 604800) return `${Math.floor(s / 86400)} дн`;
  return new Date(iso).toLocaleDateString("ru", { day: "numeric", month: "short" });
}

export function day(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString("ru", { day: "numeric", month: "short" }) : "—";
}

export const isStale = (p: { status: string; updated_at: string }) =>
  p.status === "active" && Date.now() - new Date(p.updated_at).getTime() > 7 * 86400_000;

export const AREAS: Record<string, string> = {
  youtube: "YouTube", sites: "Сайты", infra: "Инфра", jobs: "Работа", crypto: "Крипто", research: "Исследования", other: "Другое",
};

// The user pastes this into a terminal: quote everything that comes from the API.
const sq = (s: string) => `'${s.replace(/'/g, `'\\''`)}'`;

export const resume = (s: { id: string; cwd: string }) => (s.cwd ? `cd ${sq(s.cwd)} && ` : "") + `claude --resume ${sq(s.id)}`;
