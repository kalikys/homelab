import os
import secrets
import string
import sys
import time

import socketio

URL = "http://127.0.0.1:3001"
USERNAME = "kalikys"
CRED_FILE = "/data/admin-credentials.txt"

sio = socketio.Client(reconnection=False)
sio_monitors = {}


@sio.on("monitorList")
def _on_list(data):
    sio_monitors.clear()
    sio_monitors.update(data)


sio.connect(URL, transports=["websocket"], wait_timeout=15)
time.sleep(3)


def emit(event, *args, timeout=30):
    return sio.call(event, data=tuple(args) if len(args) > 1 else (args[0] if args else None), timeout=timeout)


need_setup = sio.call("needSetup", timeout=15)
if need_setup:
    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for _ in range(28))
    res = emit("setup", USERNAME, password)
    if not res.get("ok"):
        sys.exit(f"setup failed: {res}")
    old = os.umask(0o077)
    with open(CRED_FILE, "w") as f:
        f.write(f"Uptime Kuma admin\nurl: https://uptime.home.kalik8s.ru\nusername: {USERNAME}\npassword: {password}\n")
    os.umask(old)
    print("admin created, credentials saved to /opt/uptime-kuma/admin-credentials.txt")
else:
    USER_CRED_FILE = "/creds/uptime"
    if not os.path.exists(USER_CRED_FILE):
        sys.exit("admin already exists and no credentials file: cannot continue")
    lines = [l.rstrip("\r\n") for l in open(USER_CRED_FILE)]
    USERNAME, password = lines[0].strip(), lines[1]

res = emit("login", {"username": USERNAME, "password": password, "token": ""})
if not res.get("ok"):
    sys.exit(f"login failed: {res.get('msg')}")
print("logged in")

BASE = {
    "interval": 60,
    "retryInterval": 60,
    "resendInterval": 0,
    "maxretries": 2,
    "timeout": 48,
    "active": True,
    "upsideDown": False,
    "ignoreTls": False,
    "expiryNotification": False,
    "maxredirects": 10,
    "method": "GET",
    "accepted_statuscodes": ["200-299"],
    "notificationIDList": {},
    "parent": None,
    "description": "",
    "conditions": [],
    "kafkaProducerBrokers": [],
    "kafkaProducerSaslOptions": {"mechanism": "None"},
    "rabbitmqNodes": [],
}


def http(name, url, **kw):
    return {**BASE, "type": "http", "name": name, "url": url, **kw}


def ping(name, host):
    return {**BASE, "type": "ping", "name": name, "hostname": host}


def dns(name, server, query):
    return {**BASE, "type": "dns", "name": name, "hostname": query,
            "dns_resolve_server": server, "dns_resolve_type": "A", "port": 53}


GROUPS = [
    ("Сеть", [
        dns("AdGuard DNS", "192.168.1.2", "google.com"),
        http("AdGuard веб", "http://192.168.1.2"),
        ping("Keenetic", "192.168.1.1"),
        ping("Tailscale", "192.168.1.3"),
        ping("Интернет (1.1.1.1)", "1.1.1.1"),
    ]),
    ("Сервер", [
        http("Proxmox", "https://192.168.1.52:8006", ignoreTls=True),
        http("Glances API", "http://192.168.1.52:61208/api/4/status"),
    ]),
    ("Прокси и HTTPS", [
        http("Nginx Proxy Manager", "http://192.168.1.4:81"),
        http("HTTPS home.kalik8s.ru", "https://home.kalik8s.ru", expiryNotification=True),
    ]),
    ("Сервисы", [
        http("Документы (Paperless)", "http://192.168.1.10:8000"),
        http("Homepage", "http://192.168.1.10:3000"),
        http("Speedtest Tracker", "http://192.168.1.10:8081"),
    ]),
    ("Публичное", [
        http("Визитка cv.kalik8s.ru", "https://cv.kalik8s.ru", expiryNotification=True, interval=300),
        http("Статус status.kalik8s.ru", "https://status.kalik8s.ru", expiryNotification=True, interval=300),
    ]),
]

existing = {}
time.sleep(2)
for m in sio_monitors.values():
    existing[m["name"]] = m["id"]

public_groups = []
for group_name, monitors in GROUPS:
    ids = []
    for m in monitors:
        if m["name"] in existing:
            ids.append(existing[m["name"]])
            print(f"exists: {m['name']}")
            continue
        r = emit("add", m)
        if not r.get("ok"):
            print(f"FAILED {m['name']}: {r.get('msg')}")
            continue
        ids.append(r["monitorID"])
        print(f"added: {m['name']} (id {r['monitorID']})")
    public_groups.append({"name": group_name, "monitorList": [{"id": i} for i in ids]})

SLUG = "home"
r = emit("addStatusPage", "Дом", SLUG)
print("addStatusPage:", r.get("ok"), r.get("msg", ""))

config = {
    "slug": SLUG,
    "title": "Дом",
    "description": "Состояние домашних сервисов",
    "icon": "/icon.svg",
    "theme": "dark",
    "published": True,
    "showTags": False,
    "domainNameList": [],
    "customCSS": "",
    "footerText": None,
    "showPoweredBy": False,
    "googleAnalyticsId": None,
    "analyticsType": None,
    "analyticsId": None,
    "analyticsScriptUrl": None,
    "rssTitle": None,
    "showOnlyLastHeartbeat": False,
    "showCertificateExpiry": True,
    "autoRefreshInterval": 300,
}
r = emit("saveStatusPage", SLUG, config, "/icon.svg", public_groups)
print("saveStatusPage:", r.get("ok"), r.get("msg", ""))

sio.disconnect()
