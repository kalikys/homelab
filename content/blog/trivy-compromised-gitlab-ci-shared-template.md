---
title: Trivy was compromised twice in 2026. How a shared GitLab CI template for 90+ teams should run security scanners
description: Trivy compromised in 2026 shows why a shared GitLab CI template must pin scanners by digest, mirror images and DBs into Nexus, and verify signatures.
date: 2026-10-21
tags: [trivy, gitlab-ci, supply-chain, devsecops, gitleaks]
lang: en
---

In March 2026 the Trivy supply chain attack turned the scanner itself into the payload: a malicious Trivy release, poisoned GitHub Action tags and three bad Docker Hub images, including `latest`, shipped a credential stealer into CI pipelines. Almost every write-up covers GitHub Actions. I run security scanners from shared GitLab CI templates, and in a setup where one template feeds 90+ teams the question is different: how do you make sure that a compromised `aquasec/trivy:latest` never reaches a single pipeline, and that if it does, it finds nothing worth stealing?

## TL;DR checklist

- Never run `aquasec/trivy:latest` or any floating tag in a shared template. Pin the scanner image by `@sha256:` digest.
- Mirror the scanner image and its vulnerability databases into your own registry or Nexus. Pipelines pull from the mirror, never from Docker Hub or ghcr.io.
- Verify the Trivy image signature with cosign before a new digest is allowed into the mirror.
- Give scanner jobs a read-only job token and nothing else: no deploy keys, no cloud credentials, no registry push rights.
- Separate "scanner failed" from "scanner found something" and decide in advance what each one does to the pipeline.
- Treat Gitleaks and every other scanner image the same way, and roll out changes with one merge request in the template repository.

## What actually happened to Trivy in 2026

The facts below come from Aqua's own [security advisory GHSA-69fq-xp46-6x23](https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23) (CVE-2026-33634), Aqua's [incident blog post](https://www.aquasec.com/blog/trivy-supply-chain-attack-what-you-need-to-know) and the write-ups by [Docker](https://www.docker.com/blog/trivy-supply-chain-compromise-what-docker-hub-users-should-know/) and [Socket](https://socket.dev/blog/trivy-under-attack-again-github-actions-compromise).

There were two incidents, and the second grew out of the first.

**Incident one, late February 2026.** According to Aqua, attackers exploited a misconfiguration in Trivy's GitHub Actions environment and extracted a privileged access token. Aqua disclosed this on March 1 and rotated credentials. The rotation was not atomic, and the attacker kept residual access through credentials that were still valid.

**Incident two, March 19 to 23, 2026.** With that access, the attacker:

- force-pushed 76 of 77 version tags of `aquasecurity/trivy-action` and all 7 tags of `aquasecurity/setup-trivy` to malicious commits (around 17:43 UTC on March 19);
- used the `aqua-bot` account to trigger release automation and publish a malicious **Trivy v0.69.4** to GitHub Releases, Docker Hub, GHCR and ECR, with `--skip=validate` added to goreleaser to bypass binary validation;
- on March 22 pushed two more malicious images, **0.69.5** and **0.69.6**, straight to Docker Hub with separately stolen credentials, with no matching GitHub tag or release, and re-pointed `latest` at them.

Docker's timeline puts the Docker Hub exposure window at March 19, 18:24 UTC to March 23, 01:36 UTC. Anyone who pulled `aquasec/trivy:latest` in those four days could have received an infostealer. The payload ran before the real scan, so the job output looked normal, while it read secrets from the runner's process memory, collected SSH keys, cloud credentials, Kubernetes tokens, Docker configs and `.env` files, and posted them encrypted to a typosquatted domain, `scan.aquasecurtiy.org`.

Safe versions after the incident: Trivy v0.69.2 or v0.69.3 (newer releases followed; v0.76.0 was published on October 14, 2026), `trivy-action` v0.35.0, `setup-trivy` v0.2.6.

Two details matter for GitLab users. First, this was not a CVE in Trivy's code but stolen publishing credentials, so no vulnerability scanner would have flagged the bad image. Second, the official Trivy [GitLab CI tutorial](https://trivy.dev/docs/dev/tutorials/integrations/gitlab-ci/) still shows the container-scanning job as `name: docker.io/aquasec/trivy:latest`. Copied into a shared template, that is the exact configuration that would have been hit. GitLab's own `Container-Scanning.gitlab-ci.yml` does better: it uses a major-version tag, `$CI_TEMPLATE_REGISTRY_HOST/security-products/container-scanning:8`, and the [documentation](https://docs.gitlab.com/user/application_security/container_scanning/) says "Do not use the `:latest` tag with analyzer images provided by GitLab". A major tag is still mutable though.

## Why a shared template changes the risk

For one year I worked in a team of three engineers on a secure development process for a federal company with 90+ development teams and 200+ software products. We added Gitleaks, Trivy, SCA and OSA checks to the shared GitLab CI templates, put an OSA Firewall into the package supply chain so dependencies were checked before developers got them, and deployed an ASOC platform that collects findings from every scanner in one place. The result was security checks in 100% of pipelines. The details are in the [case studies](https://kalik8s.com/#cases).

Two decisions from that project are relevant here. We ran our own feeds: the vulnerability databases the scanners used were mirrored and served from inside the company, so no pipeline downloaded a database from the internet. And we pinned scanner images by version, never `:latest`. A scanner bump was a merge request in the template repository with the version, a link to the upstream changelog and a note that the feed mirror had been synced for it; it was reviewed and then rolled out to every team at once.

I want to be honest about what that would and would not have done in March 2026. Version pinning and our own feeds would have kept us away from `latest`, and the Docker Hub only images 0.69.5 and 0.69.6 would never have been referenced. But the attacker also published a real-looking `0.69.4` and force-pushed 76 existing `trivy-action` version tags. Anyone who had pinned `0.69.4` by version in good faith would have pulled the infostealer; version pinning alone cannot detect a tag that now points at different bytes. That is the gap between what we did and what I would add today: pin by digest, and verify the signature before a new version enters the mirror.

That "100%" is the point. A shared template is a multiplier: one `image:` line becomes every pipeline run in the company, each with a job token and project variables next to it. If that line says `:latest`, the security team holds the most attractive supply chain target in the company. The same multiplier works in your favour once the template is right: fixing the pin in one repository fixes it for all 90 teams on their next run.

## Pin the scanner image by digest

A tag is a pointer. A digest is content. The digest `sha256:27f4...beef3` that Docker published as an indicator of compromise is the only thing that identifies the bad bytes; `0.69.3` was clean that week, but nothing stops a registry account from re-pointing that tag later.

GitLab CI supports `image: <image-name>@<digest>` natively, see [Run your CI/CD jobs in Docker containers](https://docs.gitlab.com/ci/docker/using_docker_images/). Getting the digest for a tag takes one command:

```bash
# any of these prints the manifest (list) digest of the tag
crane digest registry.internal/mirror/aquasec/trivy:0.76.0
docker buildx imagetools inspect registry.internal/mirror/aquasec/trivy:0.76.0
skopeo inspect docker://registry.internal/mirror/aquasec/trivy:0.76.0 | jq -r .Digest
```

Take the digest of the multi-arch manifest list, not of a single platform image, so the same pin works on amd64 and arm64 runners.

In the template the pin lives in one variable, with the human-readable version next to it as a comment:

```yaml
# .gitlab/ci/security.yml, included by every project
variables:
  # Trivy 0.76.0, verified with cosign on 2026-10-20, see MR !412
  TRIVY_IMAGE: "registry.internal/mirror/aquasec/trivy@sha256:<trivy-digest>"
  # Gitleaks 8.30.1
  GITLEAKS_IMAGE: "registry.internal/mirror/gitleaks/gitleaks@sha256:<gitleaks-digest>"
```

Digests and versions here are placeholders. Resolve your own, and resolve them from the mirror, not from Docker Hub, so the pin and the pull come from the same registry.

### Which approach would have survived March 19

| Reference in the template | Pulled during the exposure window | Protects against a re-pointed tag | Needs a manual bump |
|---|---|---|---|
| `aquasec/trivy:latest` | malicious image | no | no |
| `aquasec/trivy:0.69.4` | malicious image | no | yes |
| `aquasec/trivy:0.69.3` | clean, by luck of timing | no | yes |
| `aquasec/trivy@sha256:<digest>` from Docker Hub | clean | yes | yes |
| `registry.internal/.../trivy@sha256:<digest>` after cosign verify | clean | yes | yes, through a reviewed MR |

Only in the last row does "clean" depend on your process rather than on the attacker's timing. Our federal template sat in the second or third row, and the second row is the uncomfortable one: a version pin looks disciplined and would have pulled the malicious image all the same. The manual bump is the feature, not the cost: a version change is a reviewed merge request in the template repository, with the signature check in its pipeline.

## Mirror the image and the databases into your own registry

Trivy needs three things from the internet: the scanner image, the vulnerability database and the Java index database. In an air-gapped environment all three have to be mirrored anyway. On the federal project we mirrored the feeds on a connected network too, and I would do it again anywhere, for a different reason: the mirror is the one place where you can put a gate.

A mirror also brings its own failure mode, which is worth knowing before you build one. If the feed sync job silently stops, the scanner keeps running against an ageing database and keeps reporting a clean image. The report looks fine and the gate passes; only the `metadata.json` date in the mirrored database says otherwise. The sync job needs its own alert on the database age, separate from the pipelines that consume it.

Trivy's databases are OCI artifacts. The [self-hosting documentation](https://trivy.dev/docs/dev/advanced/self-hosting/) says to copy them with crane, ORAS or regclient, and the [database configuration page](https://trivy.dev/latest/docs/configuration/db/) lists the defaults Trivy tries in order: `mirror.gcr.io/aquasec/trivy-db:2`, then `ghcr.io/aquasecurity/trivy-db:2`, and `trivy-java-db:1` from the same two hosts. The flags that redirect them are `--db-repository` and `--java-db-repository`, and both accept a list in priority order.

A sync job on the connected side, run on a schedule:

```bash
# scanner image: copy by digest, never by tag
crane copy docker.io/aquasec/trivy@sha256:<trivy-digest> \
  registry.internal/mirror/aquasec/trivy:0.76.0

# vulnerability DB and Java DB (schema tags :2 and :1 as of Trivy 0.76)
crane copy ghcr.io/aquasecurity/trivy-db:2       registry.internal/mirror/aquasec/trivy-db:2
crane copy ghcr.io/aquasecurity/trivy-java-db:1  registry.internal/mirror/aquasec/trivy-java-db:1
```

The database copy runs often and is boring. The scanner image copy is rare and must not be automatic: it runs only after the verification step below passes.

On the air-gapped side the artifacts arrive the way everything else arrives. For a major bank I built a Python service on Kubernetes that delivers packages into the bank's air-gapped Nexus. Every package is GPG-signed on the connected side and the signature is checked before it lands in Nexus. A Trivy image or a `trivy-db` tarball is just another package in that flow: it crosses the boundary only with a valid signature from a key the bank controls.

## Verify the signature before the mirror accepts a new version

Digest pinning gives you the same bytes every time. It does not tell you a trusted party built them. For that, Trivy images are signed with Sigstore keyless signing, and the [signature verification page](https://trivy.dev/docs/latest/getting-started/signature-verification/) gives the identity to check:

```bash
cosign verify docker.io/aquasec/trivy:0.76.0 \
  --certificate-identity-regexp 'https://github\.com/aquasecurity/trivy/\.github/workflows/.+' \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"
```

Release binaries are verified with `cosign verify-blob` against the `.sigstore.json` bundle that ships with every asset since v0.68.1, with the identity `https://github.com/aquasecurity/trivy/.github/workflows/reusable-release.yaml@refs/tags/<release tag>`.

One honest caveat. A keyless signature proves the artifact was built by a workflow in `aquasecurity/trivy` through GitHub's OIDC. In March the attacker triggered the real release workflow, so for v0.69.4 the signature check alone would likely have passed. It does defend against the Docker Hub only images 0.69.5 and 0.69.6, pushed with stolen registry credentials and no release workflow behind them, and against any future re-pointing of a tag at the registry level. That is why the gate is signature check plus human review plus a delay: Aqua removed the malicious artifacts within hours, and a mirror that waits a few days before verifying and copying would have skipped the whole episode.

The verification belongs in the pipeline of the template repository, so that bumping `TRIVY_IMAGE` is impossible without it:

```yaml
# pipeline of the template repository, runs on every MR that touches the pin
verify-trivy-image:
  stage: verify
  image: registry.internal/mirror/sigstore/cosign@sha256:<cosign-digest>
  variables:
    NEW_IMAGE: "docker.io/aquasec/trivy:${TRIVY_VERSION}"
  script:
    - cosign verify "$NEW_IMAGE"
        --certificate-identity-regexp 'https://github\.com/aquasecurity/trivy/\.github/workflows/.+'
        --certificate-oidc-issuer https://token.actions.githubusercontent.com
    - test "$(crane digest "$NEW_IMAGE")" = "${TRIVY_IMAGE#*@}"
  rules:
    - changes: [.gitlab/ci/security.yml]
```

The second line of `script` catches the most common mistake: a digest in the variable that does not match the version named in the comment.

## The scanner job itself

This is the shape of the job in the shared template. Projects include the template and get it unchanged; they can only turn severity thresholds up, not off.

```yaml
# .gitlab/ci/security.yml
spec:
  inputs:
    trivy_severity:
      default: "HIGH,CRITICAL"
    trivy_exit_code:
      default: 3                    # findings exit with 3; Trivy's own errors exit with 1
---
trivy-image:
  stage: security
  image:
    name: $TRIVY_IMAGE
    entrypoint: [""]
  variables:
    GIT_STRATEGY: none              # the job does not need the source checkout
    TRIVY_NO_PROGRESS: "true"
    TRIVY_CACHE_DIR: ".trivycache/"
    TRIVY_DB_REPOSITORY: "registry.internal/mirror/aquasec/trivy-db:2"
    TRIVY_JAVA_DB_REPOSITORY: "registry.internal/mirror/aquasec/trivy-java-db:1"
    TRIVY_USERNAME: "$CI_REGISTRY_USER"
    TRIVY_PASSWORD: "$CI_REGISTRY_PASSWORD"   # read-only job token, scoped to this project
  cache:
    key: trivy-db
    paths: [.trivycache/]
  script:
    # 1. report everything, never fail: this is what ASOC collects
    - trivy image --exit-code 0 --format template --template "@/contrib/gitlab.tpl"
        --output gl-container-scanning-report.json
        "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA"
    # 2. gate on the agreed severity
    - trivy image --exit-code $[[ inputs.trivy_exit_code ]]
        --severity $[[ inputs.trivy_severity ]] --ignore-unfixed
        "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA"
  artifacts:
    reports:
      container_scanning: gl-container-scanning-report.json
    expire_in: 1 week
  allow_failure:
    exit_codes: [1]                 # mirror down: warn, do not block developers; findings (3) still fail
  rules:
    - if: $CI_MERGE_REQUEST_IID

trivy-image-release:
  extends: trivy-image
  allow_failure: false              # on release refs an infrastructure error fails the pipeline too
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH || $CI_COMMIT_TAG

gitleaks:
  stage: security
  image:
    name: $GITLEAKS_IMAGE
    entrypoint: [""]
  variables:
    GIT_DEPTH: 0                    # full history, otherwise old leaks are invisible
  script:
    - gitleaks git --redact --exit-code 1
        --report-format sarif --report-path gl-gitleaks.sarif .
  artifacts:
    when: always
    paths: [gl-gitleaks.sarif]
```

Projects consume it with a pinned ref, not with a branch:

```yaml
include:
  - project: platform/ci-templates
    ref: v3.4.0                        # a tag, protected, never "main"
    file: .gitlab/ci/security.yml
    inputs:
      trivy_severity: "CRITICAL"
```

On GitLab 17 or newer the same file works as a [CI/CD component](https://docs.gitlab.com/ci/components/), `component: $CI_SERVER_FQDN/platform/ci-templates/security@3.4.0`. Either way the version is explicit and the template repository's tags are protected.

Notes on what is deliberate here:

- `TRIVY_DB_REPOSITORY` and `TRIVY_JAVA_DB_REPOSITORY` are the environment forms of `--db-repository` and `--java-db-repository` (Trivy maps every flag to `TRIVY_` plus the upper-cased flag name, per its [configuration docs](https://trivy.dev/latest/docs/configuration/)). Setting them replaces the default list, so a pipeline cannot silently fall back to ghcr.io when the mirror is down and quietly undo the mirror.
- `entrypoint: [""]` is required because the image's entrypoint is `trivy` itself. `GIT_STRATEGY: none` means a compromised image scanner would not even see the source tree; Gitleaks of course needs it.
- The cache holds the database only, never the scanner binary, so the digest pin is the single source of the executable.

### Least privilege: what a stolen job gets

Assume the scanner image is malicious anyway and ask what it can reach: `CI_JOB_TOKEN`, every CI/CD variable visible to the job, the checkout, and whatever the runner host exposes. The March payload collected exactly those things. The defence is to make that list short:

- **Variables.** Deploy keys, cloud credentials and registry push credentials are protected and masked, and they are defined only for the deploy stages, by environment scope, not globally for the project. The scanner stage sees the job token and the two Trivy repository variables, nothing else.
- **Job token.** `CI_JOB_TOKEN` is scoped to the project. The template never grants it access to other projects, and the registry login it performs is read-only pull of the image being scanned. Short-lived by design: it dies with the job.
- **Runner.** Scanners run on a dedicated runner pool with no Docker socket mounted and no host network. Docker's advisory says it plainly: if a Trivy container mounted `/var/run/docker.sock`, treat the whole host as compromised.
- **Egress.** The scanner runner can reach the internal registry and the ASOC endpoint, and nothing on the internet. In the air-gapped bank that was simply the network; on a connected network it is an egress allowlist on the runner pool, and the March payload would have failed at its first POST.

The template cannot enforce the runner and network parts itself, but it can select them: `tags: [security-scanners]` on every scanner job, with the runner pool registered only for those tags.

### Fail-safe behaviour: a scanner that is down is not a scan that passed

On the federal project the scanner reports were visible right in the pipeline, and quality gates decided pass or fail: a job went red because the gate said so, and the team could open the report next to it and see why. That only works if the gate can tell two situations apart:

1. **The scanner ran and found something.** The job fails, the report goes to ASOC, and the team sees a red `trivy-image` job with findings they can act on. That is the point of the exercise.
2. **The scanner could not run.** The mirror is down, the digest pull failed, the database is stale. This must not look like a green pipeline, and it must not look like a vulnerability either. A typical rollout conversation: a team writes that the security job broke their pipeline, the engineer on duty opens the job, and the first question is whether there is a report at all. No report means our problem; a report means theirs. The exit codes should answer that before anyone opens the log.

Trivy uses exit code 1 for its own errors and the value of `--exit-code` for findings, so the template gives findings a different code, 3, and GitLab's [`allow_failure: exit_codes`](https://docs.gitlab.com/ci/yaml/#allow_failureexit_codes) can tell the two apart. In merge requests the job is allowed to fail on exit 1 only: the mirror being down shows as a warning, developers are not blocked by the platform team's outage, and the ASOC side alerts on the missing report. Findings still exit with 3 and fail the job. The `trivy-image-release` variant for the default branch and tags has no `allow_failure` at all: a release without a scan is not a release.

Do not confuse fail-safe with `allow_failure: true` on the whole job. That setting is how 100% of pipelines come to run a scanner that nobody looks at.

## Next steps

### Was I affected? A GitLab-specific check

The GitHub Actions indicators do not apply to GitLab pipelines, so the check is different:

1. Search every `.gitlab-ci.yml` and included template for `aquasec/trivy`. A reference to `latest`, `0.69.4`, `0.69.5`, `0.69.6` or no tag at all means exposed if a job ran between March 19, 18:24 UTC and March 23, 01:36 UTC. The GitLab jobs API filtered by date does this across a group.
2. Search your registry mirror, Nexus or Artifactory caches for the three digests Docker published: `sha256:27f446230c60bbf0b70e008db798bd4f33b7826f9f76f756606f5417100beef3`, `sha256:5aaa1d7cfa9ca4649d6ffad165435c519dc836fa6e21b729a2174ad10b057d2b` and `sha256:425cd3e1a2846ac73944e891250377d2b03653e6f028833e30fc00c1abbc6d33`.
3. Check the runner hosts' outbound logs for `scan.aquasecurtiy.org` and `45.148.10.212`.
4. If anything matched, rotate every secret the affected jobs could read, atomically: revoke everything first, then issue replacements. Aqua's incomplete rotation on March 1 is why there was a March 19.

### What to change in your template, in order

If you own a shared GitLab CI template, this is the order I would do it in. The first two we had on the federal project in the version-pinned form; the rest is what I would add today:

1. Replace every floating tag on a scanner image with a digest. Today. It is one merge request and it removes the `latest` problem for good; if you are already pinned by version, this is the step that closes the March 2026 gap.
2. Set up the mirror for the scanner images and the Trivy databases, point `TRIVY_DB_REPOSITORY` and `TRIVY_JAVA_DB_REPOSITORY` at it, block the public registries from the scanner runner pool, and alert on the database age.
3. Put the cosign verification and the digest consistency check into the template repository's own pipeline, so no pin can change without it.
4. Move the scanner jobs onto a tagged runner pool without a Docker socket and with an egress allowlist.
5. Write down the fail-safe rules per branch type as a one-page instruction for the teams. In the federal project the process documents were as much of the work as the YAML, and they were what made the 100% stick.

Pinning by digest is cheap. Mirroring and verification are a few days of platform work. Both are far cheaper than rotating every secret in 90 teams' pipelines after a four-day window you did not know you were in.
