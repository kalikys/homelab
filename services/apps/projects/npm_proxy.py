"""Create the NPM proxy host projects.home.kalik8s.ru -> 192.168.1.10:8790 (idempotent).

Credentials: services/apps/projects/.secrets/npm.env with NPM_EMAIL=... and NPM_PASSWORD=...
Without the file it prints what to add by hand and exits 0.
"""
import json
import sys
import urllib.request
from pathlib import Path

API = "http://192.168.1.4:81/api"
DOMAIN = "projects.home.kalik8s.ru"
SECRETS = Path(__file__).parent / ".secrets" / "npm.env"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main():
    if not SECRETS.exists():
        print(f"No {SECRETS}. Add a Proxy Host in https://npm.home.kalik8s.ru: domain {DOMAIN}, "
              "forward http://192.168.1.10:8790, SSL: the *.home.kalik8s.ru certificate, Force SSL on.")
        return 0
    env = dict(l.split("=", 1) for l in SECRETS.read_text().split() if "=" in l)
    token = call("POST", "/tokens", {"identity": env["NPM_EMAIL"], "secret": env["NPM_PASSWORD"]})["token"]
    hosts = call("GET", "/nginx/proxy-hosts", token=token)
    if any(DOMAIN in h["domain_names"] for h in hosts):
        print(f"{DOMAIN}: already there")
        return 0
    certs = call("GET", "/nginx/certificates", token=token)
    cert = next(c["id"] for c in certs if "*.home.kalik8s.ru" in c["domain_names"])
    call("POST", "/nginx/proxy-hosts", {
        "domain_names": [DOMAIN], "forward_scheme": "http", "forward_host": "192.168.1.10", "forward_port": 8790,
        "certificate_id": cert, "ssl_forced": True, "http2_support": True, "block_exploits": True,
        "allow_websocket_upgrade": False, "caching_enabled": False, "hsts_enabled": False, "hsts_subdomains": False,
        "access_list_id": 0, "advanced_config": "", "meta": {}, "locations": [],
    }, token=token)
    print(f"{DOMAIN}: created")
    return 0


if __name__ == "__main__":
    sys.exit(main())
