#!/usr/bin/env python3
"""Throwaway CI VMs on Proxmox for the GitLab custom executor. Standard library only.

  pvejob.py clone --job-id ID                  linked clone of template 9100 -> prints "VMID IP"
  pvejob.py wait --vmid V --known-hosts FILE   wait for the guest agent, pin the VM's SSH host key
  pvejob.py destroy (--vmid V | --job-id ID)   stop + purge; "absent" when already gone
  pvejob.py reap [--max-age 7200] [--dry-run]  destroy ci-* VMs in pool ci-jobs older than max-age

Safety rails, independent of the token's Proxmox permissions:
  * only VMIDs 9200-9299 are ever cloned to, stopped or destroyed;
  * only members of pool ci-jobs whose name starts with "ci-" and that are not templates;
  * the API token comes from a root-only file and is scrubbed from every error message;
  * TLS is always verified against a CA file (the Proxmox host's own root CA by default).

Environment (defaults in brackets):
  PVE_URL [https://192.168.1.52:8006]  PVE_NODE [pve]
  PVE_TOKEN_FILE [/etc/ci-runner/pve-token]     contents: ci@pve!runner=<secret>
  PVE_CA_FILE [/etc/ci-runner/pve-root-ca.pem]  copy of /etc/pve/pve-root-ca.pem from the host
  CI_SSH_PUBKEY [/etc/ci-runner/ssh/id_ed25519.pub]
"""
import argparse
import dataclasses
import ipaddress
import json
import os
import re
import ssl
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TEMPLATE_VMID = 9100
VMID_MIN, VMID_MAX = 9200, 9299
POOL = "ci-jobs"
NAME_PREFIX = "ci-"
NET = ipaddress.ip_network("10.99.0.0/24")
GATEWAY = "10.99.0.1"
IP_OFFSET = 100  # 9200 -> 10.99.0.100 ... 9299 -> 10.99.0.199
NAMESERVERS = "1.1.1.1 9.9.9.9"  # public resolvers: the LAN DNS (AdGuard) is out of reach on purpose
JOB_USER = "ci"
HOST_KEY_PATH = "/etc/ssh/ssh_host_ed25519_key.pub"
DEFAULT_MAX_AGE = 2 * 3600

TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+![A-Za-z0-9._-]+=[A-Za-z0-9-]{8,}$")
JOB_ID_RE = re.compile(r"^[0-9]{1,20}$")
HOST_KEY_RE = re.compile(r"^(ssh-ed25519) ([A-Za-z0-9+/=]{20,})(?: .*)?$")
CREATED_RE = re.compile(r"\bci-created=([0-9]{9,12})\b")
CTIME_RE = re.compile(r"\bctime=([0-9]{9,12})\b")


class PVEError(Exception):
    """Any failure. Messages are already scrubbed of the API token."""


class HTTPFailure(Exception):
    """Raised by a transport for a non-2xx answer."""

    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


@dataclasses.dataclass
class Config:
    url: str = "https://192.168.1.52:8006"
    token: str = ""
    ca_file: str | None = "/etc/ci-runner/pve-root-ca.pem"
    node: str = "pve"
    ssh_pubkey_file: str = "/etc/ci-runner/ssh/id_ed25519.pub"

    def scrub(self, text):
        text = str(text)
        if self.token:
            text = text.replace(self.token, "***")
            secret = self.token.split("=", 1)[-1]
            if secret:
                text = text.replace(secret, "***")
        return text


def read_token(path):
    try:
        st = os.stat(path)
    except OSError as e:
        raise PVEError(f"token file {path}: {e.strerror}") from None
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise PVEError(f"token file {path} is readable by others; chmod 600 it")
    with open(path, encoding="utf-8") as f:
        token = f.read().strip()
    if not TOKEN_RE.match(token):
        raise PVEError(f"token file {path} must hold one line: user@realm!tokenid=secret")
    return token


def ip_for(vmid):
    vmid = int(vmid)
    if not VMID_MIN <= vmid <= VMID_MAX:
        raise PVEError(f"VMID {vmid} is outside {VMID_MIN}-{VMID_MAX}")
    return str(NET.network_address + IP_OFFSET + (vmid - VMID_MIN))


def default_transport(cfg):
    """HTTPS transport with certificate verification. There is deliberately no way to turn it off."""
    if not cfg.ca_file or not os.path.isfile(cfg.ca_file):
        raise PVEError(f"CA file {cfg.ca_file!r} not found (copy /etc/pve/pve-root-ca.pem from the host)")
    ctx = ssl.create_default_context(cafile=cfg.ca_file)
    base = cfg.url.rstrip("/") + "/api2/json"
    header = f"PVEAPIToken={cfg.token}"

    def call(method, path, params):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        url = base + path
        data = None
        if method in ("GET", "DELETE"):
            if params:
                url += "?" + urllib.parse.urlencode(params)
        else:
            data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(url, data=data, method=method, headers={"Authorization": header})
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.reason
            try:
                errs = json.loads(e.read() or b"{}").get("errors")
                if errs:
                    detail = f"{detail} {errs}"
            except ValueError:
                pass
            raise HTTPFailure(e.code, detail) from None
        except urllib.error.URLError as e:
            raise HTTPFailure(0, f"connection failed: {e.reason}") from None
        return json.loads(body or b"{}").get("data")

    return call


class Client:
    def __init__(self, cfg, transport):
        self.cfg = cfg
        self.transport = transport

    def request(self, method, path, params=None):
        try:
            return self.transport(method, path, params or {})
        except HTTPFailure as e:
            raise PVEError(self.cfg.scrub(f"{method} {path}: HTTP {e.status}: {e.message}")) from None
        except PVEError as e:
            raise PVEError(self.cfg.scrub(e)) from None
        except Exception as e:  # noqa: BLE001 - anything else still must not leak the token
            raise PVEError(self.cfg.scrub(f"{method} {path}: {type(e).__name__}: {e}")) from None


def log(msg):
    print(f"pvejob: {msg}", file=sys.stderr, flush=True)


class Jobs:
    def __init__(self, client, cfg, now=time.time, sleep=time.sleep):
        self.client = client
        self.cfg = cfg
        self.now = now
        self.sleep = sleep

    # plumbing ------------------------------------------------------------------------
    def _qemu(self, vmid, suffix=""):
        return f"/nodes/{self.cfg.node}/qemu/{int(vmid)}{suffix}"

    def _wait_task(self, upid, timeout=600):
        if not isinstance(upid, str) or not upid.startswith("UPID:"):
            return  # synchronous call
        path = f"/nodes/{self.cfg.node}/tasks/{urllib.parse.quote(upid, safe='')}/status"
        deadline = self.now() + timeout
        while True:
            st = self.client.request("GET", path) or {}
            if st.get("status") == "stopped":
                if st.get("exitstatus") != "OK":
                    raise PVEError(f"task {upid.split(':')[5]} failed: {st.get('exitstatus')}")
                return
            if self.now() > deadline:
                raise PVEError(f"task {upid.split(':')[5]} timed out")
            self.sleep(1)

    def _members(self):
        data = self.client.request("GET", "/pools", {"poolid": POOL})
        if isinstance(data, list):
            data = next((p for p in data if p.get("poolid") == POOL), {})
        return [m for m in (data or {}).get("members", []) if m.get("type") == "qemu"]

    @staticmethod
    def _check_range(vmid):
        if not VMID_MIN <= int(vmid) <= VMID_MAX:
            raise PVEError(f"refusing VMID {vmid}: outside {VMID_MIN}-{VMID_MAX}")

    # clone ---------------------------------------------------------------------------
    def clone(self, job_id):
        job_id = str(job_id)
        if not JOB_ID_RE.match(job_id):
            raise PVEError("job id must be numeric")
        with open(self.cfg.ssh_pubkey_file, encoding="utf-8") as f:
            pubkey = f.read().strip()
        name = f"{NAME_PREFIX}{job_id}"
        for vmid in range(VMID_MIN, VMID_MAX + 1):
            try:
                self.client.request("GET", "/cluster/nextid", {"vmid": vmid})
            except PVEError:
                continue  # taken (by anyone, visible to us or not)
            try:
                upid = self.client.request("POST", self._qemu(TEMPLATE_VMID, "/clone"), {
                    "newid": vmid, "name": name, "pool": POOL, "full": 0,
                    "description": f"ci-job={job_id} ci-created={int(self.now())}",
                })
            except PVEError as e:
                if "exists" in str(e):
                    continue  # lost a race for this VMID
                raise
            try:
                self._wait_task(upid)
                ip = ip_for(vmid)
                self._wait_task(self.client.request("PUT", self._qemu(vmid, "/config"), {
                    "delete": "cicustom",  # the template's build user-data must not run again
                    "ciuser": JOB_USER,
                    "sshkeys": urllib.parse.quote(pubkey, safe=""),
                    "ipconfig0": f"ip={ip}/{NET.prefixlen},gw={GATEWAY}",
                    "nameserver": NAMESERVERS,
                    "ciupgrade": 0,
                }))
                self._wait_task(self.client.request("POST", self._qemu(vmid, "/status/start")))
            except PVEError:
                try:
                    self.destroy(vmid=vmid)
                except PVEError as e2:
                    log(f"cleanup of {vmid} after failed clone also failed: {e2}")
                raise
            log(f"cloned {name} as {vmid} ({ip})")
            return vmid, ip
        raise PVEError(f"no free VMID in {VMID_MIN}-{VMID_MAX}")

    # wait ----------------------------------------------------------------------------
    def wait(self, vmid, known_hosts, timeout=300):
        """Read the SSH host key through the guest agent (a hypervisor channel the job cannot
        touch yet: the VM is a pristine clone) and write it as the only known_hosts entry."""
        ip = ip_for(vmid)
        deadline = self.now() + timeout
        last = "no answer"
        while self.now() < deadline:
            try:
                self.client.request("POST", self._qemu(vmid, "/agent/ping"))
                res = self.client.request("GET", self._qemu(vmid, "/agent/file-read"), {"file": HOST_KEY_PATH})
                m = HOST_KEY_RE.match(((res or {}).get("content") or "").strip())
                if m:
                    tmp = f"{known_hosts}.tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.write(f"{ip} {m.group(1)} {m.group(2)}\n")
                    os.replace(tmp, known_hosts)
                    log(f"pinned host key of {vmid}")
                    return
                last = "host key not generated yet"
            except PVEError as e:
                last = str(e)
            self.sleep(3)
        raise PVEError(f"timed out after {timeout}s waiting for VM {vmid}: {last}")

    # destroy -------------------------------------------------------------------------
    def destroy(self, vmid=None, job_id=None):
        members = self._members()
        if vmid is None:
            name = f"{NAME_PREFIX}{job_id}"
            hits = [m for m in members if m.get("name") == name]
            if not hits:
                return "absent"
            results = [self.destroy(vmid=m["vmid"]) for m in hits]
            return "destroyed" if "destroyed" in results else "absent"
        vmid = int(vmid)
        self._check_range(vmid)
        member = next((m for m in members if int(m.get("vmid", -1)) == vmid), None)
        if member is None:
            return "absent"
        if not str(member.get("name", "")).startswith(NAME_PREFIX):
            raise PVEError(f"refusing VMID {vmid}: name {member.get('name')!r} does not start with ci-")
        if int(member.get("template") or 0):
            raise PVEError(f"refusing VMID {vmid}: it is a template")
        status = (self.client.request("GET", self._qemu(vmid, "/status/current")) or {}).get("status")
        if status != "stopped":
            self._wait_task(self.client.request("POST", self._qemu(vmid, "/status/stop"), {"timeout": 30}))
        self._wait_task(self.client.request("DELETE", self._qemu(vmid), {
            "purge": 1, "destroy-unreferenced-disks": 1,
        }))
        log(f"destroyed {vmid}")
        return "destroyed"

    # reap ----------------------------------------------------------------------------
    def _created(self, vmid):
        cfg = self.client.request("GET", self._qemu(vmid, "/config")) or {}
        for field, rx in (("description", CREATED_RE), ("meta", CTIME_RE)):
            m = rx.search(urllib.parse.unquote(str(cfg.get(field) or "")))
            if m:
                return int(m.group(1))
        return None

    def reap(self, max_age=DEFAULT_MAX_AGE, dry_run=False):
        now = self.now()
        reaped, errors = [], []
        for m in self._members():
            vmid = int(m.get("vmid", -1))
            name = str(m.get("name", ""))
            if not (VMID_MIN <= vmid <= VMID_MAX and name.startswith(NAME_PREFIX)) or int(m.get("template") or 0):
                continue
            try:
                created = self._created(vmid)
                if created is None:
                    log(f"skip {vmid} {name}: creation time unknown")
                    continue
                if now - created <= max_age:
                    continue
                log(f"{'would reap' if dry_run else 'reaping'} {vmid} {name}, age {int(now - created)}s")
                if not dry_run:
                    self.destroy(vmid=vmid)
                reaped.append(vmid)
            except PVEError as e:
                errors.append(f"{vmid}: {e}")
        if errors:
            raise PVEError("reap failed for " + "; ".join(errors))
        return reaped


def load_config():
    cfg = Config(
        url=os.environ.get("PVE_URL", Config.url),
        ca_file=os.environ.get("PVE_CA_FILE", Config.ca_file),
        node=os.environ.get("PVE_NODE", Config.node),
        ssh_pubkey_file=os.environ.get("CI_SSH_PUBKEY", Config.ssh_pubkey_file),
    )
    cfg.token = read_token(os.environ.get("PVE_TOKEN_FILE", "/etc/ci-runner/pve-token"))
    return cfg


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pvejob.py", description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("clone")
    p.add_argument("--job-id", required=True)
    p = sub.add_parser("wait")
    p.add_argument("--vmid", type=int, required=True)
    p.add_argument("--known-hosts", required=True)
    p.add_argument("--timeout", type=int, default=300)
    p = sub.add_parser("destroy")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--vmid", type=int)
    g.add_argument("--job-id")
    p = sub.add_parser("reap")
    p.add_argument("--max-age", type=int, default=DEFAULT_MAX_AGE)
    p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    cfg = None
    try:
        cfg = load_config()
        jobs = Jobs(Client(cfg, default_transport(cfg)), cfg)
        if args.cmd == "clone":
            vmid, ip = jobs.clone(args.job_id)
            print(f"{vmid} {ip}")
        elif args.cmd == "wait":
            jobs.wait(args.vmid, args.known_hosts, args.timeout)
        elif args.cmd == "destroy":
            if args.job_id is not None and not JOB_ID_RE.match(args.job_id):
                raise PVEError("job id must be numeric")
            print(jobs.destroy(vmid=args.vmid, job_id=args.job_id))
        elif args.cmd == "reap":
            reaped = jobs.reap(args.max_age, args.dry_run)
            print(" ".join(map(str, reaped)) or "nothing to reap")
        return 0
    except Exception as e:  # noqa: BLE001
        msg = cfg.scrub(e) if cfg else str(e)
        print(f"pvejob: error: {msg}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
