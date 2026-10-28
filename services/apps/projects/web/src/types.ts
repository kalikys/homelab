import { Box, FileText, Flag, Lightbulb, ListChecks, Puzzle, Scale, StickyNote, type LucideIcon } from "lucide-react";

export type ItemType = "feature" | "milestone" | "plan" | "todo" | "artifact" | "decision" | "finding" | "note";

export const TYPE: Record<ItemType, { label: string; icon: LucideIcon }> = {
  feature: { label: "Фича", icon: Puzzle },
  milestone: { label: "Этап", icon: Flag },
  plan: { label: "План", icon: FileText },
  todo: { label: "Задача", icon: ListChecks },
  artifact: { label: "Артефакт", icon: Box },
  decision: { label: "Решение", icon: Scale },
  finding: { label: "Находка", icon: Lightbulb },
  note: { label: "Заметка", icon: StickyNote },
};

// Must match projects_api/model.py TYPES.
export const STATUSES: Record<ItemType, string[]> = {
  feature: ["planned", "in_progress", "done", "dropped"],
  milestone: ["open", "done"],
  plan: ["draft", "approved", "in_progress", "done", "dropped"],
  todo: ["open", "doing", "done", "dropped"],
  artifact: ["draft", "final", "published"],
  decision: ["logged"], finding: ["logged"], note: ["logged"],
};

export const STATUS: Record<string, string> = {
  planned: "запланировано", in_progress: "в работе", done: "готово", dropped: "отменено", open: "открыто",
  doing: "в работе", draft: "черновик", approved: "утверждено", final: "финал", published: "опубликовано", logged: "записано",
};

export const REL: Record<"out" | "in", Record<string, string>> = {
  out: { implements: "реализует", produced: "создала", depends_on: "зависит от", relates: "связано с" },
  in: { implements: "реализуется в", produced: "создан в", depends_on: "нужен для", relates: "связано с" },
};

export const ROLE: Record<string, string> = { created: "создан", updated: "изменён" };

export const isOpen = (s: string) => !["done", "dropped", "final", "published", "logged"].includes(s);

export const tone = (s: string): "ok" | "accent" | "muted" =>
  ["done", "final", "published"].includes(s) ? "ok" : ["in_progress", "doing", "approved"].includes(s) ? "accent" : "muted";
