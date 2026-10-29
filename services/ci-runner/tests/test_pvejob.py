"""pvejob against a fake Proxmox API: no network, no Proxmox.

Run: python -m pytest services/ci-runner/tests
"""
import json
import os
import sys
import urllib.parse

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "executor"))
import pvejob  # noqa: E402

SECRET = "fake-test-secret-not-real"
TOKEN = f"ci@pve!runner={SECRET}"
NOW = 1_800_000_000
POOL = "ci-jobs"


class FakePVE:
    """Just enough of the Proxmox API for pvejob, with the token's real view of the cluster:
    it sees only the pool members, the template, and global VMID usage through /cluster/nextid."""

    def __init__(self):
        # vmid -> dict(name, status, pool, template, description, config)
        self.vms = {
            9100: dict(name="ci-template", status="stopped", pool=None, template=1, description="", config={}),
            220: dict(name="agent", status="running", pool=None, template=0, description="", config={}),
        }
        self.calls = []
        self.fail = {}  # (method, path) -> (status, message)

    # helpers -----------------------------------------------------------------
    def add(self, vmid, name, *, pool=POOL, status="stopped", created=None, description=None, template=0):
        if description is None:
            description = "" if created is None else f"ci-job=1 ci-created={created}"
        self.vms[vmid] = dict(name=name, status=status, pool=pool, template=template,
                              description=description, config={})

    def _task(self, kind):
        return f"UPID:pve:0000ABCD:00000001:6800000{len(self.calls)}:{kind}:9200:ci@pve!runner:"

    # transport -----------------------------------------------------------------
    def __call__(self, method, path, params):
        self.calls.append((method, path, dict(params or {})))
        if (method, path) in self.fail:
            code, msg = self.fail[(method, path)]
            raise pvejob.HTTPFailure(code, msg)
        parts = [p for p in path.split("/") if p]

        if path == "/cluster/nextid":
            vmid = int(params["vmid"])
            if vmid in self.vms:
                raise pvejob.HTTPFailure(400, f"VM {vmid} already exists")
            return vmid
        if path == "/pools" and method == "GET":
            members = [
                {"id": f"qemu/{v}", "vmid": v, "name": vm["name"], "type": "qemu", "status": vm["status"],
                 "node": "pve", "template": vm["template"]}
                for v, vm in sorted(self.vms.items()) if vm["pool"] == params.get("poolid")
            ]
            return [{"poolid": params.get("poolid"), "members": members}]
        if parts[:2] == ["nodes", "pve"] and parts[2] == "tasks":
            return {"status": "stopped", "exitstatus": "OK"}
        if parts[:3] == ["nodes", "pve", "qemu"]:
            vmid = int(parts[3])
            rest = parts[4:]
            vm = self.vms.get(vmid)
            visible = vm is not None and (vm["pool"] == POOL or vmid == 9100)
            if not visible:
                raise pvejob.HTTPFailure(403, "Permission check failed (/vms/%d, VM.Audit)" % vmid)
            if rest == ["clone"] and method == "POST":
                newid = int(params["newid"])
                if newid in self.vms:
                    raise pvejob.HTTPFailure(500, f"unable to create VM {newid}: config file already exists")
                self.vms[newid] = dict(name=params["name"], status="stopped", pool=params.get("pool"),
                                       template=0, description=params.get("description", ""),
                                       config={"cicustom": "user=local:snippets/ci-template.yaml"})
                return self._task("qmclone")
            if rest == ["config"] and method == "GET":
                return {"name": vm["name"], "description": vm["description"], "template": vm["template"],
                        **vm["config"]}
            if rest == ["config"] and method in ("POST", "PUT"):
                for k, v in params.items():
                    if k == "delete":
                        for d in v.split(","):
                            vm["config"].pop(d, None)
                    else:
                        vm["config"][k] = v
                return self._task("qmconfig")
            if rest == ["status", "current"]:
                return {"status": vm["status"], "name": vm["name"], "vmid": vmid}
            if rest == ["status", "start"]:
                vm["status"] = "running"
                return self._task("qmstart")
            if rest == ["status", "stop"]:
                vm["status"] = "stopped"
                return self._task("qmstop")
            if rest == [] and method == "DELETE":
                del self.vms[vmid]
                return self._task("qmdestroy")
            if rest == ["agent", "ping"]:
                return None
            if rest == ["agent", "file-read"]:
                return {"content": f"ssh-ed25519 AAAAC3NzaFAKEHOSTKEY{vmid} root@ci-{vmid}\n"}
        raise AssertionError(f"unexpected call {method} {path} {params}")


@pytest.fixture
def api():
    return FakePVE()


@pytest.fixture
def job(api, tmp_path):
    pub = tmp_path / "id_ed25519.pub"
    pub.write_text("ssh-ed25519 AAAAC3NzaMANAGERKEY ci-runner\n")
    cfg = pvejob.Config(url="https://192.168.1.52:8006", token=TOKEN, ca_file=None, node="pve",
                        ssh_pubkey_file=str(pub))
    return pvejob.Jobs(pvejob.Client(cfg, transport=api), cfg, now=lambda: NOW, sleep=lambda s: None)


# clone ---------------------------------------------------------------------------


def test_clone_picks_first_free_vmid_in_range(api, job):
    api.add(9200, "ci-41")
    api.add(9201, "someone-else", pool=None)  # outside the pool: invisible except through nextid
    vmid, ip = job.clone("42")
    assert vmid == 9202
    assert ip == "10.99.0.102"
    vm = api.vms[9202]
    assert vm["name"] == "ci-42"
    assert vm["pool"] == POOL
    assert vm["status"] == "running"
    clone = next(c for c in api.calls if c[1].endswith("/clone"))
    assert clone[1] == "/nodes/pve/qemu/9100/clone"
    assert clone[2]["full"] == 0 or clone[2]["full"] == "0"
    assert f"ci-created={NOW}" in clone[2]["description"]


def test_clone_sets_cloud_init_for_the_job(api, job):
    job.clone("42")
    cfg = api.vms[9200]["config"]
    assert "cicustom" not in cfg  # the template's build user-data must not run again
    assert cfg["ipconfig0"] == "ip=10.99.0.100/24,gw=10.99.0.1"
    assert cfg["ciuser"] == "ci"
    assert str(cfg["ciupgrade"]) == "0"
    assert urllib.parse.unquote(cfg["sshkeys"]).strip() == "ssh-ed25519 AAAAC3NzaMANAGERKEY ci-runner"


def test_clone_skips_vmid_taken_between_nextid_and_clone(api, job):
    real = api.__call__

    def racing(method, path, params):
        if path == "/nodes/pve/qemu/9100/clone" and int(params["newid"]) == 9200 and 9200 not in api.vms:
            api.add(9200, "ci-other")
        return real(method, path, params)

    job.client.transport = racing
    vmid, _ = job.clone("7")
    assert vmid == 9201


def test_clone_fails_when_range_is_full(api, job):
    for v in range(9200, 9300):
        api.add(v, f"ci-{v}")
    with pytest.raises(pvejob.PVEError, match="no free VMID"):
        job.clone("42")


def test_clone_rejects_bad_job_id(job):
    with pytest.raises(pvejob.PVEError):
        job.clone("42; rm -rf /")


def test_clone_failure_after_create_destroys_vm(api, job):
    api.fail[("POST", "/nodes/pve/qemu/9200/status/start")] = (500, "start failed")
    with pytest.raises(pvejob.PVEError):
        job.clone("42")
    assert 9200 not in api.vms


# wait ----------------------------------------------------------------------------


def test_wait_pins_host_key_from_guest_agent(api, job, tmp_path):
    api.add(9203, "ci-42", status="running", created=NOW)
    kh = tmp_path / "known_hosts"
    job.wait(9203, str(kh), timeout=5)
    assert kh.read_text() == "10.99.0.103 ssh-ed25519 AAAAC3NzaFAKEHOSTKEY9203\n"


def test_wait_times_out(api, job, tmp_path):
    api.add(9203, "ci-42", status="running", created=NOW)
    api.fail[("POST", "/nodes/pve/qemu/9203/agent/ping")] = (500, "QEMU guest agent is not running")
    clock = iter(range(NOW, NOW + 10_000, 10))
    job.now = lambda: next(clock)
    with pytest.raises(pvejob.PVEError, match="timed out"):
        job.wait(9203, str(tmp_path / "kh"), timeout=60)


# destroy -------------------------------------------------------------------------


def test_destroy_running_vm(api, job):
    api.add(9205, "ci-42", status="running", created=NOW)
    assert job.destroy(vmid=9205) == "destroyed"
    assert 9205 not in api.vms
    methods = [(m, p) for m, p, _ in api.calls]
    assert ("POST", "/nodes/pve/qemu/9205/status/stop") in methods
    delete = next(c for c in api.calls if c[0] == "DELETE")
    assert str(delete[2]["purge"]) == "1"


def test_destroy_is_idempotent(api, job):
    api.add(9205, "ci-42", created=NOW)
    assert job.destroy(vmid=9205) == "destroyed"
    assert job.destroy(vmid=9205) == "absent"
    assert job.destroy(job_id="42") == "absent"


def test_destroy_by_job_id(api, job):
    api.add(9207, "ci-77", status="running", created=NOW)
    api.add(9208, "ci-78", created=NOW)
    assert job.destroy(job_id="77") == "destroyed"
    assert 9207 not in api.vms and 9208 in api.vms


@pytest.mark.parametrize("vmid", [9100, 9199, 9300, 220, 290])
def test_destroy_refuses_outside_range(api, job, vmid):
    with pytest.raises(pvejob.PVEError, match="outside"):
        job.destroy(vmid=vmid)
    assert not any(m == "DELETE" for m, _, _ in api.calls)


def test_destroy_refuses_non_ci_name(api, job):
    api.add(9210, "important")
    with pytest.raises(pvejob.PVEError, match="ci-"):
        job.destroy(vmid=9210)
    assert 9210 in api.vms


def test_destroy_refuses_template(api, job):
    api.add(9211, "ci-tpl", template=1)
    with pytest.raises(pvejob.PVEError):
        job.destroy(vmid=9211)
    assert 9211 in api.vms


# reap ----------------------------------------------------------------------------


def test_reap_removes_only_old_ci_vms_in_pool_and_range(api, job):
    old = NOW - 3 * 3600
    young = NOW - 30 * 60
    api.add(9200, "ci-1", status="running", created=old)       # old orphan -> reaped
    api.add(9201, "ci-2", created=old)                         # old, stopped -> reaped
    api.add(9202, "ci-3", status="running", created=young)     # running job -> kept
    api.add(9203, "build-box", created=old)                    # not ci-* -> kept
    api.add(9150, "ci-low", created=old)                       # in pool but below range -> kept
    api.add(9300, "ci-high", created=old)                      # in pool but above range -> kept
    api.add(9204, "ci-elsewhere", pool=None, created=old)      # not in pool -> kept
    api.add(9205, "ci-unknown-age", description="")            # age unknown -> kept
    api.add(9206, "ci-tmpl", created=old, template=1)          # template -> kept

    reaped = job.reap(max_age=2 * 3600)

    assert sorted(reaped) == [9200, 9201]
    for v in (9202, 9203, 9150, 9300, 9204, 9205, 9206, 9100, 220):
        assert v in api.vms, v
    deleted = [p for m, p, _ in api.calls if m == "DELETE"]
    assert deleted and all(9200 <= int(p.rsplit("/", 1)[1]) <= 9299 for p in deleted)


def test_reap_uses_meta_ctime_when_description_missing(api, job):
    api.add(9220, "ci-9", description="")
    api.vms[9220]["config"]["meta"] = f"creation-qemu=9.2.0,ctime={NOW - 5 * 3600}"
    assert job.reap(max_age=7200) == [9220]


def test_reap_dry_run_deletes_nothing(api, job):
    api.add(9200, "ci-1", created=NOW - 3 * 3600)
    assert job.reap(max_age=7200, dry_run=True) == [9200]
    assert 9200 in api.vms


def test_reap_keeps_going_after_one_failure(api, job):
    old = NOW - 3 * 3600
    api.add(9200, "ci-1", created=old)
    api.add(9201, "ci-2", created=old)
    api.fail[("DELETE", "/nodes/pve/qemu/9200")] = (500, "zfs busy")
    with pytest.raises(pvejob.PVEError):
        job.reap(max_age=7200)
    assert 9201 not in api.vms


# secrets -------------------------------------------------------------------------


def test_token_never_appears_in_errors(api, job):
    api.fail[("GET", "/pools")] = (401, f"authentication failure for {TOKEN}")
    with pytest.raises(pvejob.PVEError) as exc:
        job.reap(max_age=7200)
    text = str(exc.value) + repr(exc.value)
    assert SECRET not in text
    assert "***" in text


def test_token_never_appears_in_cli_output(api, tmp_path, monkeypatch, capsys):
    token_file = tmp_path / "pve-token"
    token_file.write_text(TOKEN + "\n")
    os.chmod(token_file, 0o600)
    api.fail[("GET", "/pools")] = (401, f"no ticket; header was PVEAPIToken={TOKEN}")
    monkeypatch.setattr(pvejob, "default_transport", lambda cfg: api)
    monkeypatch.setenv("PVE_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("PVE_CA_FILE", str(token_file))  # any existing file; the fake transport ignores it
    rc = pvejob.main(["reap"])
    out = capsys.readouterr()
    assert rc != 0
    assert SECRET not in out.out + out.err


def test_token_file_must_be_private(tmp_path):
    token_file = tmp_path / "pve-token"
    token_file.write_text(TOKEN)
    os.chmod(token_file, 0o644)
    with pytest.raises(pvejob.PVEError, match="readable by others"):
        pvejob.read_token(str(token_file))


def test_token_format_checked(tmp_path):
    token_file = tmp_path / "pve-token"
    token_file.write_text("not-a-token")
    os.chmod(token_file, 0o600)
    with pytest.raises(pvejob.PVEError) as exc:
        pvejob.read_token(str(token_file))
    assert "not-a-token" not in str(exc.value)


def test_ip_for_vmid():
    assert pvejob.ip_for(9200) == "10.99.0.100"
    assert pvejob.ip_for(9299) == "10.99.0.199"
    with pytest.raises(pvejob.PVEError):
        pvejob.ip_for(9300)


def test_fake_pool_json_roundtrip(api):
    # guard: the fake returns JSON-serialisable data like the real API
    json.dumps(api("GET", "/pools", {"poolid": POOL}))
