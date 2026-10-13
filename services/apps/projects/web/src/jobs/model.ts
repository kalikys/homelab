// Must match projects_api/jobs.py STATUS_LABELS.
export type Status = "draft" | "inbound" | "sent" | "replied" | "interview" | "offer" | "rejected" | "declined" | "silent";

export const STATUS: Record<Status, { label: string; color: string; hint: string }> = {
  draft: { label: "Готовлю", color: "var(--s-draft)", hint: "ещё не отправил" },
  inbound: { label: "HR написала", color: "var(--s-inbound)", hint: "пришли сами" },
  sent: { label: "Отправил", color: "var(--s-sent)", hint: "ждём ответа" },
  replied: { label: "Ответили", color: "var(--s-replied)", hint: "идёт переписка" },
  interview: { label: "Интервью", color: "var(--s-interview)", hint: "созвоны" },
  offer: { label: "Оффер", color: "var(--s-offer)", hint: "" },
  rejected: { label: "Отказ", color: "var(--s-closed)", hint: "" },
  declined: { label: "Сам отказался", color: "var(--s-closed)", hint: "" },
  silent: { label: "Тишина", color: "var(--s-closed)", hint: "не ответили" },
};

/** The funnel left to right; finals are shown folded. */
export const STAGES: Status[] = ["draft", "inbound", "sent", "replied", "interview", "offer"];
export const CLOSED: Status[] = ["rejected", "declined", "silent"];
export const ALL: Status[] = [...STAGES, ...CLOSED];

/** The one most likely next status, offered as a single button on the card. */
export const NEXT: Partial<Record<Status, Status>> = {
  draft: "sent", inbound: "replied", sent: "replied", replied: "interview", interview: "offer",
};

export const LANGS = [
  { id: "en", label: "English" }, { id: "ru", label: "Русский" }, { id: "sk", label: "Slovenčina" }, { id: "de", label: "Deutsch" },
];

export const FORMATS = [
  { id: "remote", label: "Удалёнка" }, { id: "hybrid", label: "Гибрид" }, { id: "onsite", label: "Офис" }, { id: "relocation", label: "Релокация" },
];

export const formatLabel = (id: string) => FORMATS.find((f) => f.id === id)?.label ?? id;

export function daysUntil(isoDate: string | null): number | null {
  if (!isoDate) return null;
  const d = new Date(isoDate + "T00:00:00");
  const t = new Date(); t.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - t.getTime()) / 86400_000);
}

/** "сегодня", "завтра", "через 3 дн", "2 дн назад". */
export function dueLabel(isoDate: string | null): string {
  const n = daysUntil(isoDate);
  if (n === null) return "";
  if (n === 0) return "сегодня";
  if (n === 1) return "завтра";
  if (n === -1) return "вчера";
  return n > 0 ? `через ${n} дн` : `${-n} дн назад`;
}

export const plusDays = (n: number) => {
  const d = new Date(); d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
