"""Add one HTTP monitor to Uptime Kuma if it is missing. Leaves other monitors and the status page alone.

Run on LXC 103 (asks for the Kuma admin password):
  docker run --rm -it --network host -v /opt/uptime-kuma:/k python:3.12-slim \
    sh -c 'pip -q install "python-socketio[client]==5.13.0" websocket-client==1.8.0 && python /k/add_monitor.py "Проекты" http://192.168.1.10:8790/api/health'
"""
import getpass
import sys
import time

import socketio

URL = "http://127.0.0.1:3001"
name, target = sys.argv[1], sys.argv[2]

sio = socketio.Client(reconnection=False)
monitors = {}


@sio.on("monitorList")
def _on_list(data):
    monitors.clear()
    monitors.update(data)


sio.connect(URL, transports=["websocket"], wait_timeout=15)
user = input("Uptime Kuma username [kalikys]: ").strip() or "kalikys"
res = sio.call("login", {"username": user, "password": getpass.getpass("Password: "), "token": ""}, timeout=30)
if not res.get("ok"):
    sys.exit(f"login failed: {res.get('msg')}")
time.sleep(2)
if any(m["name"] == name for m in monitors.values()):
    print(f"exists: {name}")
else:
    m = {"type": "http", "name": name, "url": target, "method": "GET", "interval": 60, "retryInterval": 60,
         "resendInterval": 0, "maxretries": 2, "timeout": 30, "accepted_statuscodes": ["200-299"],
         "notificationIDList": {}, "ignoreTls": False, "upsideDown": False, "expiryNotification": False,
         "maxredirects": 10, "kafkaProducerBrokers": [], "kafkaProducerSaslOptions": {}, "conditions": []}
    r = sio.call("add", m, timeout=30)
    print(f"added: {name} (id {r.get('monitorID')})" if r.get("ok") else f"FAILED: {r.get('msg')}")
sio.disconnect()
