#!/usr/bin/env python3
"""pj: client for the projects dashboard (https://projects.home.kalik8s.ru). Standard library only.

Every write carries the current Claude session id, so the dashboard knows which chat touched what.
Writes never fail a Claude session: when the server is unreachable they are queued in
~/.config/pj/outbox.jsonl and replayed, in order, before the next request.
"""
import argparse
import json
import os
import re
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DEFAULT_URL = "https://projects.home.kalik8s.ru"
AREAS = ["youtube", "sites", "infra", "jobs", "crypto", "research", "other"]
TYPES = ["feature", "milestone", "plan", "todo", "artifact", "decision", "finding", "note"]
RELATIONS = ["implements", "produced", "depends_on", "relates"]
STATUSES = ["active", "paused", "done", "dropped"]


class Offline(Exception):
    pass


class ApiError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(f"{code}: {msg}")
        self.code = code


class Die(Exception):
    pass


def home() -> Path:
    return Path(os.environ.get("PJ_HOME", Path.home() / ".config" / "pj"))


def load_config() -> dict:
    cfg = {"url": DEFAULT_URL, "token": ""}
    f = home() / "config.toml"
    if f.exists():
        cfg.update(tomllib.loads(f.read_text()))
    if os.environ.get("PJ_URL"):
        cfg["url"] = os.environ["PJ_URL"]
    return cfg


def http(cfg: dict, method: str, path: str, body=None, timeout: float = 5):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(cfg["url"].rstrip("/") + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if cfg.get("token"):
        req.add_header("Authorization", f"Bearer {cfg['token']}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", e.reason)
        except Exception:
            msg = str(e.reason)
        raise ApiError(e.code, msg)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise Offline(str(e))


def _outbox() -> Path:
    return home() / "outbox.jsonl"


def flush(cfg: dict) -> int:
    box = _outbox()
    if not box.exists():
        return 0
    lines = [l for l in box.read_text().splitlines() if l.strip()]
    done = 0
    for i, line in enumerate(lines):
        item = json.loads(line)
        try:
            http(cfg, item["method"], item["path"], item.get("body"))
        except Offline:
            box.write_text("\n".join(lines[i:]) + "\n")
            return done
        except ApiError as e:
            print(f"pj: dropped queued {item['method']} {item['path']}: {e}", file=sys.stderr)
        done += 1
    box.unlink()
    return done


def send(cfg: dict, method: str, path: str, body=None):
    try:
        flush(cfg)
        return http(cfg, method, path, body)
    except Offline as e:
        home().mkdir(parents=True, exist_ok=True)
        with _outbox().open("a") as f:
            f.write(json.dumps({"method": method, "path": path, "body": body}, ensure_ascii=False) + "\n")
        print(f"pj: dashboard unreachable ({e}); queued, will retry on the next call", file=sys.stderr)
        return None


def read(cfg: dict, path: str):
    flush(cfg)
    return http(cfg, "GET", path)


def loc(s: str) -> str:
    return s if re.match(r"https?://", s) else str(Path(s).expanduser().resolve())


def encode_dir(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def claude_projects() -> Path:
    return Path(os.environ.get("PJ_CLAUDE_PROJECTS", Path.home() / ".claude" / "projects"))


def guess_session(cwd: str) -> str | None:
    """Best effort: the newest transcript of this folder or a parent, touched in the last 15 minutes."""
    p = Path(cwd).resolve()
    for d in [p, *p.parents]:
        tdir = claude_projects() / encode_dir(str(d))
        if tdir.is_dir():
            files = sorted(tdir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
            if files and time.time() - files[0].stat().st_mtime < 900:
                return files[0].stem
    return None


def current_session() -> str | None:
    return os.environ.get("PJ_SESSION") or guess_session(os.getcwd())


def project_slug(cfg: dict, args) -> str:
    if getattr(args, "project", None):
        return args.project
    cwd = os.getcwd()
    try:
        slug = read(cfg, "/api/resolve?cwd=" + urllib.parse.quote(cwd))["project"]
    except Offline:
        raise Die("dashboard unreachable and no -p given; pass -p <slug>")
    if not slug:
        raise Die(f"no project mapped to {cwd}; pass -p <slug>, or create one: pj new <slug> \"<title>\" --path {cwd}")
    return slug


def rel_spec(s: str) -> tuple[str, int]:
    kind, _, to = s.partition(":")
    if kind not in RELATIONS or not to.isdigit():
        raise argparse.ArgumentTypeError(f"expected <{'|'.join(RELATIONS)}>:<item id>, got {s!r}")
    return kind, int(to)


def fmt(i: dict) -> str:
    s = f"#{i['id']} {i['title']}"
    if i["status"] != "logged":
        s += f" [{i['status']}]"
    if i.get("progress") is not None:
        s += f" {i['progress']}%"
    if i.get("location"):
        s += f" — {i['location']}"
    return s


# --- commands -------------------------------------------------------------

def cmd_new(cfg, a):
    send(cfg, "POST", "/api/projects", {"slug": a.slug, "title": a.title, "area": a.area,
                                        "summary": a.summary or "", "milestones": a.milestone or []})
    for p in a.path or []:
        send(cfg, "POST", "/api/path-map", {"prefix": loc(p), "project": a.slug})
    print(f"created {a.slug}")


def cmd_add(cfg, a):
    slug = project_slug(cfg, a)
    body = {"type": a.type, "title": a.title, "body": a.body or "", "uid": str(uuid.uuid4()),
            "session_id": current_session()}
    if a.status:
        body["status"] = a.status
    if a.owner:
        body["owner"] = a.owner
    if a.loc:
        body["location"] = loc(a.loc)
    if a.parent is not None:
        body["parent_id"] = a.parent
    res = send(cfg, "POST", f"/api/projects/{slug}/items", body)
    if res is None:
        if a.rel:
            print("pj: --rel skipped (offline, the new item's id is unknown); add it later with pj rel", file=sys.stderr)
        return
    for kind, to in a.rel or []:
        send(cfg, "POST", f"/api/items/{res['id']}/relations", {"to_id": to, "kind": kind})
    print(f"#{res['id']} {res['type']} {res['title']}")


def cmd_set(cfg, a):
    body = {"session_id": current_session()}
    for key, val in (("title", a.title), ("body", a.body), ("status", a.status), ("owner", a.owner),
                     ("parent_id", a.parent)):
        if val is not None:
            body[key] = val
    if a.loc is not None:
        body["location"] = loc(a.loc)
    send(cfg, "PATCH", f"/api/items/{a.id}", body)


def cmd_done(cfg, a):
    send(cfg, "POST", f"/api/items/{a.id}/done", {"session_id": current_session()})


def cmd_rel(cfg, a):
    send(cfg, "POST", f"/api/items/{a.from_id}/relations", {"to_id": a.to_id, "kind": a.kind})


def cmd_next(cfg, a):
    send(cfg, "PATCH", f"/api/projects/{project_slug(cfg, a)}", {"next_step": a.text})


def cmd_status(cfg, a):
    send(cfg, "PATCH", f"/api/projects/{project_slug(cfg, a)}", {"status": a.value})


def cmd_map(cfg, a):
    send(cfg, "POST", "/api/path-map", {"prefix": loc(a.dir), "project": project_slug(cfg, a)})


def cmd_list(cfg, a):
    for p in read(cfg, "/api/projects"):
        prog = f"{p['progress']:>3}%" if p["progress"] is not None else "   -"
        print(f"{p['slug']:<24} {prog}  {p['status']:<7} {p['updated_at'][:10]}  {p['next_step'][:60]}")


def cmd_item(cfg, a):
    i = read(cfg, f"/api/items/{a.id}")
    out = [f"#{i['id']} {i['type']} [{i['status']}] {i['title']}  (project {i['project']})"]
    if i["owner"]:
        out.append(f"owner: {i['owner']}")
    if i["location"]:
        out.append(f"location: {i['location']}")
    if i["body"]:
        out.append(i["body"])
    if i["parent"]:
        out.append(f"parent: #{i['parent']['id']} {i['parent']['title']}")
    if i["children"]:
        out.append("children:")
        out += [f"  {fmt(c)}" for c in i["children"]]
    if i["relations"]:
        out.append("relations:")
        out += [f"  {r['direction']} {r['kind']} #{r['item']['id']} {r['item']['title']}" for r in i["relations"]]
    if i["sessions"]:
        out.append("chats:")
        out += [f"  {s['id']} {s['title'] or s['first_prompt'][:60]} ({', '.join(s['roles'])})" for s in i["sessions"]]
    print("\n".join(out))


def cmd_show(cfg, a):
    slug = project_slug(cfg, a)
    p = read(cfg, f"/api/projects/{slug}")
    items = p["items"]
    of = lambda t: [i for i in items if i["type"] == t]
    is_open = lambda i: i["status"] not in ("done", "dropped")
    prog = f", {p['progress']}%" if p["progress"] is not None else ""
    out = [f"# {p['title']} [{p['slug']}] — {p['status']}{prog}, updated {p['updated_at'][:16]}"]
    if p["summary"]:
        out.append(p["summary"])
    if p["next_step"]:
        out.append(f"Next: {p['next_step']}")
    todos = of("todo")
    sections = [
        ("Waiting on the user", [i for i in todos if i["owner"] == "user" and is_open(i)]),
        ("Features", of("feature")),
        ("Plans", of("plan")),
        ("Open todos (claude)", [i for i in todos if i["owner"] == "claude" and is_open(i)]),
        ("Artifacts", of("artifact")),
    ]
    if of("milestone"):
        out.append("Milestones:")
        out += [f"  [{'x' if m['status'] == 'done' else ' '}] #{m['id']} {m['title']}" for m in of("milestone")]
    for title, rows in sections:
        if rows:
            out.append(f"{title}:")
            out += [f"  {fmt(i)}" + (f" (in #{i['parent_id']})" if i["parent_id"] else "") for i in rows]
    log = sorted(of("decision") + of("finding"), key=lambda i: i["created_at"], reverse=True)[:10]
    if log:
        out.append("Decisions and findings:")
        out += [f"  {i['created_at'][:10]} {i['type']} #{i['id']}: {i['title']}" + (f" — {i['body'][:120]}" if i["body"] else "")
                for i in log]
    if p["events"]:
        out.append("Recent activity:")
        out += [f"  {e['ts'][:10]} {e['text']}" for e in p["events"][:10]]
    if p["sessions"]:
        s = p["sessions"][0]
        out.append(f"Chats: {len(p['sessions'])} (last: {s['title'] or s['id']}, claude --resume {s['id']})")
    print("\n".join(out))


EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
TS_RE = re.compile(r'"timestamp":\s*"([^"]+)"')
CWD_RE = re.compile(r'"cwd":\s*"([^"]+)"')


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def parse_transcript(path: Path) -> dict:
    """One pass, JSON-decoding only lines that can matter (big sessions run to 100+ MB)."""
    res = {"title": "", "first_prompt": "", "started_at": None, "ended_at": None,
           "user_turns": 0, "files_changed": [], "cwd": ""}
    ai_title = custom_title = ""
    files: dict[str, None] = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = TS_RE.search(line)
            if m:
                res["started_at"] = res["started_at"] or m.group(1)
                res["ended_at"] = m.group(1)
            if not res["cwd"]:
                c = CWD_RE.search(line)
                if c:
                    res["cwd"] = c.group(1)
            if not ("turnOrigin" in line or "tool_use" in line or "-title" in line):
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = e.get("type")
            if t == "custom-title":
                custom_title = e.get("customTitle") or custom_title
            elif t == "ai-title":
                ai_title = e.get("aiTitle") or ai_title
            elif t == "user" and e.get("turnOrigin") == "human" and not e.get("isCompactSummary"):
                res["user_turns"] += 1
                text = _text_of(e.get("message", {}).get("content", "")).strip()
                if text and not res["first_prompt"] and not text.startswith("<"):
                    res["first_prompt"] = text[:300]
            elif t == "assistant":
                for b in e.get("message", {}).get("content", []) or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in EDIT_TOOLS:
                        p = (b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("notebook_path")
                        if p:
                            files[p] = None
    res["title"] = custom_title or ai_title
    res["files_changed"] = list(files)[:50]
    return res


def session_payload(session_id: str, cwd: str, transcript_path: str) -> dict | None:
    t = parse_transcript(Path(transcript_path))
    if t["user_turns"] < 3:
        return None
    return {"id": session_id, "title": t["title"], "cwd": cwd or t["cwd"], "first_prompt": t["first_prompt"],
            "started_at": t["started_at"], "ended_at": t["ended_at"], "user_turns": t["user_turns"],
            "files_changed": t["files_changed"], "transcript_path": transcript_path}


def cmd_session_end(cfg, a):
    # Runs as a Claude Code SessionEnd hook: must be quick and must never fail.
    try:
        hook = json.loads(sys.stdin.read())
        body = session_payload(hook["session_id"], hook.get("cwd", ""), hook["transcript_path"])
        if body:
            send(cfg, "POST", "/api/sessions", body)
    except Exception as e:
        print(f"pj session-end: {e}", file=sys.stderr)


def cmd_backfill(cfg, a):
    root = Path(a.root).expanduser() if a.root else claude_projects()
    sent = 0
    for f in sorted(root.glob("*/*.jsonl")):
        body = session_payload(f.stem, "", str(f))
        if body:
            send(cfg, "POST", "/api/sessions", body)
            sent += 1
    print(f"backfilled {sent} sessions")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pj", description="projects dashboard client")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, project=True):
        sp = sub.add_parser(name)
        if project:
            sp.add_argument("-p", "--project")
        sp.set_defaults(fn=fn)
        return sp

    sp = add("new", cmd_new, project=False)
    sp.add_argument("slug"); sp.add_argument("title")
    sp.add_argument("--area", choices=AREAS, default="other"); sp.add_argument("--summary")
    sp.add_argument("-m", "--milestone", action="append"); sp.add_argument("--path", action="append")
    sp = add("add", cmd_add)
    sp.add_argument("type", choices=TYPES); sp.add_argument("title")
    sp.add_argument("-b", "--body"); sp.add_argument("-s", "--status"); sp.add_argument("-o", "--owner", choices=["claude", "user"])
    sp.add_argument("-l", "--loc"); sp.add_argument("--parent", type=int)
    sp.add_argument("--rel", type=rel_spec, action="append", help="kind:item_id, e.g. implements:12")
    sp = add("set", cmd_set, project=False)
    sp.add_argument("id", type=int); sp.add_argument("-t", "--title"); sp.add_argument("-b", "--body")
    sp.add_argument("-s", "--status"); sp.add_argument("-o", "--owner", choices=["claude", "user"])
    sp.add_argument("-l", "--loc"); sp.add_argument("--parent", type=int)
    add("done", cmd_done, project=False).add_argument("id", type=int)
    sp = add("rel", cmd_rel, project=False)
    sp.add_argument("from_id", type=int); sp.add_argument("kind", choices=RELATIONS); sp.add_argument("to_id", type=int)
    add("item", cmd_item, project=False).add_argument("id", type=int)
    add("next", cmd_next).add_argument("text")
    add("status", cmd_status).add_argument("value", choices=STATUSES)
    add("map", cmd_map).add_argument("dir", nargs="?", default=".")
    add("list", cmd_list, project=False)
    add("show", cmd_show)
    add("session-end", cmd_session_end, project=False)
    add("backfill", cmd_backfill, project=False).add_argument("--root")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config()
    try:
        args.fn(cfg, args)
    except Die as e:
        print(f"pj: {e}", file=sys.stderr)
        return 2
    except ApiError as e:
        print(f"pj: {e}", file=sys.stderr)
        return 1
    except Offline as e:
        print(f"pj: dashboard unreachable ({e})", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
