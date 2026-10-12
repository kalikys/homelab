import re

from fastapi import HTTPException

# Statuses per item type; the first one is the default.
TYPES: dict[str, list[str]] = {
    "feature": ["planned", "in_progress", "done", "dropped"],
    "milestone": ["open", "done"],
    "plan": ["draft", "approved", "in_progress", "done", "dropped"],
    "todo": ["open", "doing", "done", "dropped"],
    "artifact": ["draft", "final", "published"],
    "decision": ["logged"],
    "finding": ["logged"],
    "note": ["logged"],
}
LABELS = {"feature": "Фича", "milestone": "Этап", "plan": "План", "todo": "Задача", "artifact": "Артефакт",
          "decision": "Решение", "finding": "Находка", "note": "Заметка"}
STATUS_LABELS = {"planned": "запланировано", "in_progress": "в работе", "done": "готово", "dropped": "отменено",
                 "open": "открыто", "doing": "в работе", "draft": "черновик", "approved": "утверждено",
                 "final": "финал", "published": "опубликовано", "logged": "записано"}
FINISHED = {"done", "final", "published"}


def default_status(t: str) -> str:
    return TYPES[t][0]


def check_status(t: str, s: str | None) -> None:
    if s not in TYPES[t]:
        raise HTTPException(400, f"status for {t} must be one of: {', '.join(TYPES[t])}")


def finished(s: str) -> bool:
    return s in FINISHED


def done_status(t: str) -> str:
    if t == "artifact":
        return "final"
    return "done" if "done" in TYPES[t] else TYPES[t][0]


def location_kind(loc: str | None) -> str | None:
    if not loc:
        return None
    if re.match(r"https?://(www\.)?(github|gitlab)\.com/", loc):
        return "repo"
    if re.match(r"https?://claude\.ai/(code/)?artifact/", loc):
        return "artifact"
    if re.match(r"https?://", loc):
        return "url"
    return "path"
