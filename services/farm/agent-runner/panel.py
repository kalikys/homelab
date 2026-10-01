"""Judges panel summary shared by the runner (qualification) and the deck renderer."""


def summarise_panel(raw):
    judges = [j for j in (raw.get("judges") or []) if isinstance(j.get("score_0_10"), (int, float))]
    if len(judges) < 3:
        return None
    scores = sorted(float(j["score_0_10"]) for j in judges)
    median = scores[len(scores) // 2] if len(scores) % 2 else (scores[len(scores) // 2 - 1] + scores[len(scores) // 2]) / 2
    recs = [str(j.get("recommendation", "pass")).lower() for j in judges]
    rec = max(set(recs), key=lambda r: (recs.count(r), {"pass": 2, "maybe": 1, "invest": 0}.get(r, 2)))
    return {"judges": judges, "median": round(median, 1), "spread": round(scores[-1] - scores[0], 1), "recommendation": rec}
