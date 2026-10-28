#!/usr/bin/env python3
"""Collects read-only homelab status for the Hermes morning summary.

Runs on VM 220 from Hermes cron (`--script homelab_collect.py`); its stdout is given to the model,
which only writes the summary. Installed by a human to ~/.hermes/scripts/ (the agent cannot write there).
Source of truth: homelab/services/agent/scripts/homelab_collect.py.
"""
import json
import os
import ssl
import time
import urllib.request

PVE = "https://192.168.1.52:8006/api2/json"
TOKEN_FILE = os.path.expanduser("~/.hermes/secrets/pve-token")
# Lab VMs are off unless Kalik is practising; the sandbox is rolled back every 30 minutes.
OFF_BY_DESIGN = {"k8s-cp", "k8s-w1", "k8s-w2"}

# The Proxmox certificate is signed by the cluster's own CA (/etc/pve/pve-root-ca.pem, copied next to the token);
# its SAN includes 192.168.1.52, so full verification works.
PVE_CA = os.path.expanduser("~/.hermes/secrets/pve-root-ca.pem")
pve_tls = ssl.create_default_context(cafile=PVE_CA)


def get(url, headers=None, context=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15, context=context) as resp:
        return json.load(resp)


def section(name, fn):
    try:
        return fn()
    except Exception as exc:  # report the source as unavailable instead of failing the whole run
        return {"error": f"{name} unavailable: {type(exc).__name__}: {exc}"}


def pve(path):
    with open(TOKEN_FILE) as f:
        token = f.read().strip()
    return get(PVE + path, {"Authorization": f"PVEAPIToken={token}"}, pve_tls)["data"]


def proxmox():
    node = pve("/nodes/pve/status")
    guests = []
    for kind in ("lxc", "qemu"):
        for g in pve(f"/nodes/pve/{kind}"):
            guests.append({"id": g["vmid"], "name": g.get("name"), "kind": kind, "status": g.get("status")})
    down = [g for g in guests if g["status"] != "running" and g["name"] not in OFF_BY_DESIGN]
    pools = pve("/nodes/pve/disks/zfs")
    rpool = pve("/nodes/pve/disks/zfs/rpool")
    # Listing pending apt updates needs Sys.Modify, which this read-only token does not get.
    try:
        updates = pve("/nodes/pve/apt/update")
    except Exception as exc:
        updates = None
        updates_error = f"{type(exc).__name__}: {exc}"
    day_ago = time.time() - 86400
    failed = [t for t in pve("/nodes/pve/tasks?errors=1&limit=50") if t.get("starttime", 0) >= day_ago]
    return {
        "uptime_days": round(node["uptime"] / 86400, 1),
        "load": node.get("loadavg"),
        "memory_used_pct": round(100 * node["memory"]["used"] / node["memory"]["total"]),
        "guests_total": len(guests),
        "guests_not_running_unexpected": down,
        "lab_vms_running": [g["name"] for g in guests if g["name"] in OFF_BY_DESIGN and g["status"] == "running"],
        "zfs": [{"name": p["name"], "health": p["health"], "alloc_pct": round(100 * p["alloc"] / p["size"])} for p in pools],
        "rpool_scan": rpool.get("scan"),
        "updates_count": len(updates) if updates is not None else f"unavailable ({updates_error}); read-only token by design",
        "updates_pve_or_kernel": sorted(u["Package"] for u in updates if u["Package"].startswith(("pve", "proxmox", "linux-image"))) if updates else [],
        "failed_tasks_24h": [{"type": t.get("type"), "id": t.get("id"), "status": t.get("status")} for t in failed],
    }


def gatus():
    data = get("http://192.168.1.11:8082/api/v1/endpoints/statuses")
    failing = []
    for ep in data:
        last = (ep.get("results") or [{}])[-1]
        if not last.get("success", False):
            failing.append({"group": ep.get("group"), "name": ep.get("name"), "errors": last.get("errors")})
    return {"checks": len(data), "failing": failing}


def kuma():
    data = get("https://uptime.home.kalik8s.ru/api/status-page/heartbeat/home")
    down = []
    for monitor_id, beats in data.get("heartbeatList", {}).items():
        if beats and beats[-1].get("status") != 1:
            down.append({"monitor": monitor_id, "msg": beats[-1].get("msg")})
    return {"monitors": len(data.get("heartbeatList", {})), "down": down}


print(json.dumps({
    "collected_at": time.strftime("%Y-%m-%d %H:%M %Z"),
    "proxmox": section("proxmox", proxmox),
    "gatus": section("gatus", gatus),
    "uptime_kuma": section("uptime kuma", kuma),
}, ensure_ascii=False, indent=1))
