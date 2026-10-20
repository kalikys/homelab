---
title: "Air-gapped Nexus: delivering GPG-signed packages into a bank's closed network"
description: How packages get into an air gapped Nexus repository: sign on the connected side, verify before upload, keep an audit trail. Pattern, Python gate, Nexus API.
date: 2026-10-21
tags: [nexus, air-gapped, gpg, supply-chain, kubernetes]
lang: en
---

A bank's Nexus repository with no internet access does not solve supply-chain security. It moves the problem to the door. Every artifact that crosses into the closed network still comes from somewhere, and if nobody can prove where, the air gap is a formality. This post describes the pattern I use for that door: sign on the connected side, stage in a DMZ, verify at a gate on the closed side, and only then let the internal Nexus see the file. It applies to any artifact type, from `.deb` and `.whl` files to Docker images.

## TL;DR

- Nexus Repository does not sign or verify individual packages. Sonatype's docs say so for both [Yum](https://help.sonatype.com/en/gpg-signatures-for-yum-proxy-group.html) and [APT](https://help.sonatype.com/en/apt-repositories.html): it signs repository metadata only. Package signing and verification have to happen upstream of Nexus.
- The pattern: a connected zone that fetches, scans and signs; a staging Nexus in a DMZ; a verification gate inside the closed zone that pulls from the DMZ; the internal Nexus behind the gate. Nothing writes to the internal Nexus except the gate.
- Signing happens on the connected side after scanning and allowlist checks, with GPG detached signatures per artifact plus a signed manifest.
- The gate on the closed side verifies against a pinned keyring of a few known fingerprints, not against "any good signature", then uploads through the Nexus REST API and records what it did.
- In my case at a major bank, that gate was a Python service on Kubernetes. Every artifact was signed with GPG, the signing key was kept in HashiCorp Vault, and the signature was checked before the artifact landed in the internal Nexus. The delivery was format-agnostic: Docker images, apt packages and other formats went through the same channel.

## The constraints an air-gapped bank actually has

Air-gapped environments in banking and government share constraints that are well known there and rarely written down:

1. **No outbound connectivity from the closed zone.** Not "restricted egress", none. Nexus in that zone cannot proxy anything. Every proxy repository you are used to becomes a hosted repository that somebody has to fill.
2. **Every incoming file needs a trusted origin.** The security policy will say something like "software enters only from approved sources through an approved channel". The policy does not say how. That is the engineer's job.
3. **Traceability.** When an auditor asks "who put this version of this library in the repository, and on what grounds", there must be an answer that does not depend on anybody's memory.
4. **Developers still need packages.** If the channel is slow or painful, people build private workarounds, and the air gap becomes theatre.

Nexus itself offers two blunt tools here. In the Pro edition there are [Repository Export](https://help.sonatype.com/en/repository-export.html) and [Repository Import](https://help.sonatype.com/en/repository-import.html) tasks, "only available in Sonatype Nexus Repository Pro", which move content between instances as directories. That is how Sonatype staff answered a 2021 [community question about air-gapped Nexus](https://community.sonatype.com/t/nexus-repository-in-an-air-gapped-environment/7539): "This is something you could do with Nexus Pro through the Export and the Import tasks." It works, but it is a bulk copy. It does not verify provenance, it does not enforce an allowlist, and it leaves no per-package audit trail.

### What Nexus does and does not sign

This is the point that catches teams off guard, so I will quote Sonatype directly.

For Yum: "Nexus Repository uses GPG signatures to sign the metadata files that the Yum proxy and group repositories generate" and "Nexus Repository does not sign the actual RPM packages themselves" ([GPG signatures for Yum](https://help.sonatype.com/en/gpg-signatures-for-yum-proxy-group.html)).

For APT hosted repositories: "Hosted APT repositories only sign the metadata" and "Nexus Repository does not sign packages" ([APT Repositories](https://help.sonatype.com/en/apt-repositories.html)). You give the hosted repo a GPG private key and passphrase, and it signs the `Release` file, which is what `apt` expects anyway.

So Nexus will happily serve `apt` and `yum` clients a correctly signed index of whatever you uploaded. Whether what you uploaded is genuine is not its concern. For raw, PyPI, npm or Helm hosted repositories there is not even metadata signing to lean on. That is why the verification gate has to sit in front of Nexus, not inside it.

## The two-zone pattern

```
 CONNECTED ZONE                        |      DMZ        |   CLOSED ZONE (bank network)
                                       |                 |
 request (ticket / allowlist entry)    |                 |
        |                              |                 |
        v                              |                 |
 fetch from upstream (pinned version)  |                 |
 any format: deb, rpm, whl, npm,       |                 |
 Helm chart, Docker image ...          |                 |
        |                              |                 |
        v                              |                 |
 scan + SBOM + policy check            |                 |
 (OSA Firewall / SCA / Trivy)          |                 |
        |                              |                 |
        v                              |                 |
 GPG sign: artifact.sig + manifest.sig |                 |
 (signing key in Vault,                |                 |
  never leaves this zone)              |                 |
        |                              |                 |
        v        push                  |                 |      pull
 upload to DMZ Nexus  ===============> |  DMZ Nexus      | <==============  verification gate (service)
                                       |  (staging only, |                    - fingerprint pinned?
                                       |   untrusted)    |                    - signature valid, not expired?
                                       |                 |                    - sha256 matches manifest?
                                       |                 |                    - in allowlist?
                                       |                 |                         |  yes            no
                                       |                 |                         v                 v
                                       |                 |                 upload to internal   quarantine + alert
                                       |                 |                 Nexus via REST API        |
                                       |                 |                         |                 |
                                       |                 |                         v                 v
                                       |                 |                   audit log (who/what/sig/when)
```

The important properties:

- **Signing and verification happen in different zones with different keys.** The private signing key lives only on the connected side, in a secrets manager or on a hardware token. The closed side holds only public keys.
- **The gate is the only writer to the internal Nexus.** Upload credentials for it exist in one place: the gate's service account. Developers get read access. Humans with admin rights upload nothing by hand except in a documented break-glass procedure.
- **The DMZ Nexus is a staging area, not a source of truth.** In my case the connected side pushed signed artifacts into a Nexus instance in the DMZ, and the gate inside the closed network pulled from there. Nothing in the closed zone trusts the DMZ instance: the design assumes files on it can be altered or substituted, and the signatures make that irrelevant.
- **Pull, not push.** The closed zone initiates the connection to the DMZ. Nothing on the connected side can open a connection into the bank network.
- **Rejection is a first-class outcome.** A package that fails any check goes to quarantine with the reason attached. It does not get retried silently.

In our case the gate was a Python service on Kubernetes, and GPG signatures were verified before upload. The channel carried any package format: Docker images, apt packages and others went through the same signing and verification steps. The reasons for that stack are mundane and I would pick it again: GPG tooling exists on every Linux host a bank already runs, Python with [python-gnupg](https://github.com/vsajip/python-gnupg) (a wrapper that spawns the `gpg` binary, so you depend on GnuPG itself rather than a reimplementation) needs no exotic dependencies, and Kubernetes gives the service a restart policy, secrets handling for the Nexus token, and a place to ship logs from.

### What goes into the bundle

Signing "the package" is not enough on its own. A detached signature over a `.whl` file proves the file was signed; it does not prove this file was supposed to arrive today, for this request, in this repository. The bundle that goes through the DMZ should carry:

- the artifacts themselves, unchanged from upstream so that upstream checksums still match; for a container image that means the saved image archive or its OCI layout, treated as one more file to sign, so the gate does not need to understand any format
- one detached signature per artifact (`gpg --detach-sign`, documented in the [GnuPG manual](https://www.gnupg.org/documentation/manuals/gnupg/Operational-GPG-Commands.html) as "Make a detached signature")
- a manifest listing every artifact with its SHA-256, target repository, target path, requester, ticket reference, and the scan verdict
- a detached signature over the manifest

The manifest is what turns a bag of signed files into a delivery. Verify it first; then verify each artifact against both its own signature and the hash in the manifest. If somebody removes one file from the bundle or swaps an old signed version in, the manifest check catches it even though every individual signature is "good".

## The verification gate, illustrated

The code below is a simplified illustration of the gate's core, not the bank's code. It uses `python-gnupg` for verification and the Nexus Components API for upload. Error handling, retries, the quarantine path and the audit sink are left out to keep it readable.

Two details matter more than the rest. First, the gate verifies against its own dedicated keyring under a dedicated `gnupghome` that contains only the delivery keys. Second, it compares the signing key's full fingerprint with a pinned set. A signature from any other key in the world is a rejection, even if it is cryptographically valid.

```python
# gate.py - simplified illustration, not the bank's code
import hashlib
import json
import os
import pathlib
import gnupg          # pip install python-gnupg; needs the gpg binary
import requests

GNUPGHOME = "/var/lib/gate/gnupg"             # contains only delivery public keys
ALLOWED_FPRS = set(os.environ["ALLOWED_FPRS"].split(","))
NEXUS = os.environ["NEXUS_URL"]               # the internal Nexus, e.g. https://nexus.internal
NEXUS_AUTH = (os.environ["NEXUS_USER"], os.environ["NEXUS_TOKEN"])

gpg = gnupg.GPG(gnupghome=GNUPGHOME)


def verify_detached(sig_path: pathlib.Path, data_path: pathlib.Path) -> str:
    """Return the signer fingerprint, or raise."""
    with open(sig_path, "rb") as sig:
        result = gpg.verify_file(sig, str(data_path))
    if not result:                                  # bad sig, no key, expired key...
        raise ValueError(f"{data_path.name}: signature invalid ({result.status})")
    if result.fingerprint not in ALLOWED_FPRS:
        raise ValueError(f"{data_path.name}: signed by unexpected key {result.fingerprint}")
    return result.fingerprint


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_raw(repo: str, directory: str, path: pathlib.Path) -> None:
    # POST /service/rest/v1/components?repository=<repo>  (multipart form)
    r = requests.post(
        f"{NEXUS}/service/rest/v1/components",
        params={"repository": repo},
        auth=NEXUS_AUTH,
        files={
            "raw.directory": (None, directory),
            "raw.asset1": (path.name, open(path, "rb")),
            "raw.asset1.filename": (None, path.name),
        },
        timeout=120,
    )
    r.raise_for_status()


def process_bundle(bundle: pathlib.Path) -> None:
    # `bundle` is a directory already pulled from the DMZ staging Nexus
    manifest_path = bundle / "manifest.json"
    manifest_fpr = verify_detached(bundle / "manifest.json.sig", manifest_path)
    manifest = json.loads(manifest_path.read_text())

    for item in manifest["artifacts"]:
        artifact = bundle / item["file"]
        fpr = verify_detached(bundle / (item["file"] + ".sig"), artifact)
        digest = sha256(artifact)
        if digest != item["sha256"]:
            raise ValueError(f"{artifact.name}: sha256 mismatch")
        upload_raw(item["repository"], item["directory"], artifact)
        print(json.dumps({
            "event": "delivered", "file": artifact.name, "sha256": digest,
            "signer": fpr, "manifest_signer": manifest_fpr,
            "ticket": manifest["ticket"], "repository": item["repository"],
        }))
```

Notes on the pieces you would verify yourself before trusting this:

- `python-gnupg`'s `verify_file(stream, data_filename)` is the documented call for detached signatures; the returned object is falsy on failure and exposes `fingerprint`, `key_id`, `trust_level` and `trust_text` ([python-gnupg docs](https://gnupg.readthedocs.io/en/latest/)). If you prefer no library, run `gpg --batch --status-fd 1 --verify file.sig file` as a subprocess and parse the `VALIDSIG` line, which GnuPG's [DETAILS](https://raw.githubusercontent.com/gpg/gnupg/master/doc/DETAILS) file describes as "cryptographically valid" with the fingerprint as its first argument. `gpgv` is a third option: a verification-only binary that "assumes that all keys in the keyring are trustworthy" ([gpgv manual](https://www.gnupg.org/documentation/manuals/gnupg/gpgv.html)), which is what you want when the keyring is pinned.
- The Nexus upload endpoint is `POST /service/rest/v1/components` with a `repository` query parameter and format-specific multipart fields: `raw.directory`, `raw.assetN`, `raw.assetN.filename` for raw; `apt.asset`, `pypi.asset`, `npm.asset` and so on for those formats ([Components API](https://help.sonatype.com/en/components-api.html)). The Components API page lists upload fields for Maven, APT, Composer, Helm, npm, NuGet, PyPI, R, Raw and RubyGems. Yum is not on that list; hosted Yum repositories take a plain HTTP `PUT` to `/repository/<repo>/<path>/<file>.rpm`, and Nexus regenerates repodata about 60 seconds later ([Yum Repositories](https://help.sonatype.com/en/yum-repositories.html)). Raw hosted repositories accept the same `PUT` form ([Raw Repositories](https://help.sonatype.com/en/raw-repositories.html)).
- After upload, the [Search API](https://help.sonatype.com/en/search-api.html) (`GET /service/rest/v1/search/assets`) returns each asset's `checksum` object. Reading it back and comparing with the manifest closes the loop: what Nexus stores is what was signed.

## Key management and the audit trail

The signature is only as meaningful as the key behind it.

- **One key per purpose, with a short list of fingerprints pinned in the gate.** Rotating a key means adding the new fingerprint to the gate's allowlist through a reviewed change, not importing whatever public key rides along in the bundle. Public keys never travel with the packages they vouch for.
- **Expiry dates on signing keys.** GnuPG distinguishes `GOODSIG` from `EXPKEYSIG`, "good, but the signature was made by an expired key". The gate should treat the second as a rejection and page somebody, because it means the rotation calendar slipped.
- **Private key on the connected side only.** In my case the signing key was kept in HashiCorp Vault. As general advice, independent of that setup: give the signing job a short-lived Vault token through its platform identity (a Kubernetes service account, for example), let it read or use the key only for the duration of a signing run, and keep the key out of container images, CI variables and developer laptops. Vault's audit log then shows every time the key was touched.
- **Structured audit events.** Each delivery produces one record: file, SHA-256, signer fingerprint, manifest fingerprint, ticket, target repository, timestamp, outcome. Ship it somewhere append-only inside the closed zone. This is the record that lets you answer "where did this come from" months later, and it is what the result in my case came down to: developers in the closed network got the packages they needed, and each one could be traced to a signature.

## Scan and allowlist before you sign

A signature says "the connected side approved this". It should not be the first thing the connected side does. The order that makes a signature mean something:

1. The request names a package, a version and a reason, and lands on an allowlist (or in a ticket) that someone other than the requester approves.
2. The connected side fetches exactly that version from the upstream registry and checks the upstream's own integrity data where it exists: RPMs carry embedded OpenPGP signatures that `rpmkeys --checksig` verifies "to ensure the integrity and origin of the package" ([rpmkeys(8)](https://rpm-software-management.github.io/rpm/man/rpmkeys.8.html)); `apt` repositories sign the `Release` file and chain checksums down to each `.deb`, and "apt-secure does not review signatures at a package level" ([apt-secure(8)](https://manpages.debian.org/trixie/apt/apt-secure.8.en.html)); the npm registry signs tarballs with ECDSA keys served from `/-/npm/v1/keys` ([npm docs](https://docs.npmjs.com/about-registry-signatures)); PyPI removed PGP signature uploads in 2023 because "the continued support of uploading PGP signatures to PyPI is no longer defensible" ([PyPI blog](https://blog.pypi.org/posts/2023-05-23-removing-pgp/)), so for Python you rely on hashes pinned at request time.
3. SCA and vulnerability scanning run on the fetched files, with an SBOM produced and stored next to the manifest. At another client I deployed OSA Firewall into the package supply chain for exactly this step: open-source dependencies are checked before developers get them.
4. Only artifacts that pass get signed. The signature then encodes "fetched the pinned version, upstream checks passed, scanned, approved".

Put differently: upstream ecosystems sign the repository or the registry, not the file you hold. Your own signature is the one that is uniform across ecosystems and that your closed-side gate can verify without any of their infrastructure.

## GPG detached signatures vs repo-native signing vs cosign

| | GPG detached signatures (your key) | Repo-native signing (apt Release, Yum repodata, npm registry) | Sigstore cosign |
|---|---|---|---|
| What is signed | The exact file you transfer, plus a manifest | Repository metadata (apt, Yum) or registry-side tarball record (npm); Nexus signs only metadata | Container images, or any blob via `sign-blob` |
| Who signs | Your connected-side process | Upstream distro or registry; Nexus for its own hosted metadata | Your process, with a key pair or keyless via Fulcio |
| Works for raw / PyPI / Helm / internal builds | Yes, format-agnostic | No; only where the format defines it | Yes, blobs and OCI artifacts |
| Verification offline | Yes: `gpg`, `gpgv` or `python-gnupg` with a local keyring, no network needed | Yes for clients once keys are installed, but proves the metadata, not your provenance | Yes with a key pair: `cosign verify --key cosign.pub --offline --local-image ./dir` ([cosign README](https://raw.githubusercontent.com/sigstore/cosign/main/README.md)); keyless needs a TUF trusted root fetched in advance, and the README marks its air-gap section "out of date" |
| Audit trail | You build it (manifest + log) | None at package level | Rekor transparency log by default, which the closed zone cannot reach; bundles carry inclusion proofs |
| Fits a bank's existing tooling | GnuPG is already on every Linux host; auditors know it | Already there, but insufficient alone | Newer; needs policy sign-off for a new trust root |

I would still choose GPG detached signatures for the channel into a closed network today, for one reason: the closed side needs nothing but `gpg` and a keyring to check them. Cosign with a self-managed key pair is a credible second option if the organisation already runs it for container images and wants one tool. Repo-native signing is not an alternative; it is what Nexus does for `apt` and `yum` clients after your gate has already done its work.

### Failure cases the gate must handle on purpose

- **Bad signature.** Reject, quarantine, alert. Never upload.
- **Good signature from an unknown key.** Reject. This is the case that distinguishes a gate from a demo.
- **Expired or revoked signing key.** Reject and page the key owner. `python-gnupg` surfaces this through `key_status` and `problems`.
- **Manifest and artifact disagree.** Reject the whole bundle, not just the file. Something changed between signing and arrival.
- **Already present in Nexus with a different checksum.** Reject and raise a ticket. Overwriting a release artifact silently is how "the build was green yesterday" happens.
- **Upload succeeded but readback differs.** Treat as a failed delivery and investigate the Nexus side.
- **Gate itself unavailable.** Packages wait in the DMZ Nexus. Nothing bypasses the gate.

In practice the gate never had to reject a package. That is not a sign that it was unnecessary. It means the scan, the allowlist and the signing step on the connected side did their job, and the gate stood there as the proof that nothing else could get through. A control that never fires is still the control an auditor asks about.

## Practical next steps

1. Read Sonatype's [Yum](https://help.sonatype.com/en/gpg-signatures-for-yum-proxy-group.html) and [APT](https://help.sonatype.com/en/apt-repositories.html) signing pages with your security team, so that nobody expects Nexus to verify packages for you.
2. Decide how artifacts cross the boundary (a DMZ staging Nexus that the closed side pulls from worked for me; others use media or a diode) and get it approved in writing before you build anything around it.
3. Generate a dedicated signing key with an expiry date, keep the private half on the connected side only, and pin its fingerprint in the gate's configuration.
4. Build the gate as the only writer to the internal Nexus: a small service with a service-account token, a dedicated `gnupghome`, structured logs, and a quarantine directory. Start with raw repositories through the Components API, then add formats; container images and apt packages fit the same flow because the gate signs and verifies files, not formats.
5. Define the manifest format and make the signing side produce it after scanning, never before.
6. Run a tampered bundle through the gate before go-live: a flipped byte, a swapped signature, a removed file. Keep the rejection logs as evidence for the auditors.

If you are hiring for exactly this kind of work in banking or government, the signed-delivery case and the rest of my platform work are summarised at [kalik8s.com/#cases](https://kalik8s.com/#cases).
