#!/usr/bin/env python3
"""Deploy the farm landing Worker (KV for pages, D1 for metrics) to the farm Cloudflare account. Idempotent.

Reads CF_ACCOUNT_ID / CF_API_TOKEN from /home/kalikys/prj/farm/.env; creates LANDING_STATS_TOKEN there on first run.
"""
import json
import secrets
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = Path("/home/kalikys/prj/farm/.env")
env = dict(l.split("=", 1) for l in ENV_FILE.read_text().splitlines() if "=" in l and not l.startswith("#"))
ACC, TOKEN = env["CF_ACCOUNT_ID"], env["CF_API_TOKEN"]
API = f"https://api.cloudflare.com/client/v4/accounts/{ACC}"
NAME = "farm-landing"


def cf(method, path, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path}: {e.code} {e.read()[:400]!r}")


def remember(key, value):
    text = ENV_FILE.read_text()
    if f"\n{key}=" not in "\n" + text:
        ENV_FILE.write_text(text.rstrip("\n") + f"\n{key}={value}\n")
    env[key] = value


kv = next((n for n in cf("GET", "/storage/kv/namespaces?per_page=100")["result"] if n["title"] == "farm-sites"), None) \
    or cf("POST", "/storage/kv/namespaces", {"title": "farm-sites"})["result"]
remember("CF_KV_SITES_ID", kv["id"])
db = next((d for d in cf("GET", "/d1/database?per_page=100")["result"] if d["name"] == "farm-landing"), None) \
    or cf("POST", "/d1/database", {"name": "farm-landing"})["result"]
db_id = db.get("uuid") or db.get("id")
cf("POST", f"/d1/database/{db_id}/query", {"sql": (HERE / "schema.sql").read_text()})
if "LANDING_STATS_TOKEN" not in env:
    remember("LANDING_STATS_TOKEN", secrets.token_urlsafe(32))

meta = {"main_module": "worker.js", "compatibility_date": "2026-09-01",
        "bindings": [{"type": "kv_namespace", "name": "SITES", "namespace_id": kv["id"]},
                     {"type": "d1", "name": "DB", "id": db_id},
                     {"type": "secret_text", "name": "STATS_TOKEN", "text": env["LANDING_STATS_TOKEN"]}]}
b = uuid.uuid4().hex
parts = [
    f'--{b}\r\nContent-Disposition: form-data; name="metadata"\r\nContent-Type: application/json\r\n\r\n{json.dumps(meta)}\r\n'.encode(),
    f'--{b}\r\nContent-Disposition: form-data; name="worker.js"; filename="worker.js"\r\nContent-Type: application/javascript+module\r\n\r\n'.encode()
    + (HERE / "worker.js").read_bytes() + b"\r\n",
    f"--{b}--\r\n".encode(),
]
cf("PUT", f"/workers/scripts/{NAME}", raw=b"".join(parts), ctype=f"multipart/form-data; boundary={b}")
cf("POST", f"/workers/scripts/{NAME}/subdomain", {"enabled": True, "previews_enabled": False})
sub = cf("GET", "/workers/subdomain")["result"]["subdomain"]
remember("LANDING_BASE_URL", f"https://{NAME}.{sub}.workers.dev")
print("deployed", env["LANDING_BASE_URL"], "kv", kv["id"][:6] + "…", "d1", db_id[:6] + "…")
