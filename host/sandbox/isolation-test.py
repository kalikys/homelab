"""Runs shell commands in the sandbox through its public entry point (the ttyd websocket) and prints the output.

Usage (from a host that can reach the terminal): python isolation-test.py ws://10.66.0.10:7681/ws
"""
import asyncio
import json
import sys

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://10.66.0.10:7681/ws"

CHECKS = [
    "id",
    "ip -4 route",
    "timeout 3 ping -c1 -W2 192.168.1.1 >/dev/null 2>&1 && echo 'router: REACHABLE' || echo 'router: blocked'",
    "timeout 3 ping -c1 -W2 192.168.1.52 >/dev/null 2>&1 && echo 'proxmox host: REACHABLE' || echo 'proxmox host: blocked'",
    "timeout 3 ping -c1 -W2 1.1.1.1 >/dev/null 2>&1 && echo 'internet: REACHABLE' || echo 'internet: blocked'",
    "timeout 3 bash -c 'echo > /dev/tcp/10.66.0.2/8080' 2>/dev/null && echo 'LXC 104 tcp/8080: REACHABLE' || echo 'LXC 104 tcp/8080: blocked'",
    "timeout 3 bash -c 'echo > /dev/tcp/10.66.0.2/22' 2>/dev/null && echo 'LXC 104 tcp/22: REACHABLE' || echo 'LXC 104 tcp/22: blocked'",
    "sudo -n true 2>/dev/null && echo 'sudo: WORKS' || echo 'sudo: denied'",
    "touch /etc/probe 2>/dev/null && echo '/etc writable: YES' || echo '/etc writable: no'",
    "touch /usr/local/probe 2>/dev/null && echo '/usr writable: YES' || echo '/usr writable: no'",
    "cat /proc/self/status | grep -E '^NoNewPrivs'",
]


async def main() -> None:
    async with websockets.connect(URL, subprotocols=["tty"], open_timeout=10) as ws:
        await ws.send(json.dumps({"AuthToken": "", "columns": 200, "rows": 50}))
        out = []

        async def reader() -> None:
            async for msg in ws:
                data = msg if isinstance(msg, bytes) else msg.encode()
                if data[:1] == b"0":
                    out.append(data[1:].decode(errors="replace"))

        task = asyncio.create_task(reader())
        await asyncio.sleep(1.5)
        marker = "__DONE__"
        script = "; ".join(CHECKS) + f"; echo {marker}"
        await ws.send(b"0" + (script + "\r").encode())
        for _ in range(60):
            await asyncio.sleep(0.5)
            if marker in "".join(out).split(script)[-1]:
                break
        task.cancel()
        text = "".join(out)
        print(text.split(script)[-1].replace(marker, "").strip())


asyncio.run(main())
