import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { AutoTextarea } from "./jobs/ui";

// The answer lives in the item body after this marker, so pj and the API need no new field.
export const MARK = "\n\n— Ответ —\n";

export function splitBody(body: string) {
  const cut = body.indexOf(MARK);
  return cut < 0 ? { context: body, answer: "" } : { context: body.slice(0, cut), answer: body.slice(cut + MARK.length) };
}

/** Autosaving answer field; for a question it also flips the status between open and answered. */
export function AnswerBox({ id, body, question = false, label = "Ответ / заметки", onSaved }:
  { id: number; body: string; question?: boolean; label?: string; onSaved?: () => void }) {
  const { context, answer: initial } = splitBody(body);
  const [answer, setAnswer] = useState(initial);
  const [saved, setSaved] = useState(initial);
  const [state, setState] = useState("");
  const save = useCallback((text: string) => {
    if (text === saved) return;
    setState("сохраняю…");
    const patch: { body: string; status?: string } = { body: text.trim() ? context + MARK + text : context };
    if (question) patch.status = text.trim() ? "answered" : "open";
    api.patchItem(id, patch)
      .then(() => { setSaved(text); setState("сохранено"); onSaved?.(); })
      .catch((e) => setState(`не сохранилось: ${e}`));
  }, [id, context, saved, question, onSaved]);
  useEffect(() => {
    const t = setTimeout(() => save(answer), 1200);
    return () => clearTimeout(t);
  }, [answer, save]);
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-xs text-muted">{state}</span>
      </div>
      <AutoTextarea value={answer} placeholder="Что решили, кто, к какому сроку…"
        onChange={(e) => setAnswer(e.target.value)} onBlur={() => save(answer)} />
    </div>
  );
}
