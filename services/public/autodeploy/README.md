# Autodeploy of kalik8s.com (GitOps pull)

The `public` container (LXC 104) deploys the site itself: every 5 minutes `public-site-deploy.timer`
checks `origin/main`, and on a new commit `public-site-deploy` rebuilds the CVs in the `cvgen`
container and syncs `services/public/site/` to `/opt/public/site` with `--delete`. Nothing is pushed
in from outside, no deploy keys or secrets: the repo is public and the container only pulls.

What it covers: everything under `services/public/site/` and the CVs built by `cvgen/`.
What it does not: `nginx/`, `docker-compose.yml` and the other apps in `/opt/public` — change those by hand.
`/opt/public/site/data/` is written live by the stats service and is never touched.

## Install (once, from the Mac)

```sh
scp services/public/autodeploy/public-site-deploy.{sh,service,timer} homeserver:/tmp/
ssh homeserver 'sudo pct push 104 /tmp/public-site-deploy.sh /usr/local/sbin/public-site-deploy --perms 0755 \
  && sudo pct push 104 /tmp/public-site-deploy.service /etc/systemd/system/public-site-deploy.service \
  && sudo pct push 104 /tmp/public-site-deploy.timer /etc/systemd/system/public-site-deploy.timer \
  && sudo pct exec 104 -- systemctl daemon-reload \
  && sudo pct exec 104 -- systemctl enable --now public-site-deploy.timer'
```

The script reinstalls itself from the repo after every deploy, so later changes to it ship by merge.

## Operate

```sh
services/public/deploy.sh                       # deploy origin/main right now (FORCE=1)
ssh homeserver 'sudo pct exec 104 -- journalctl -u public-site-deploy -n 30'   # last runs
ssh homeserver 'sudo pct exec 104 -- cat /opt/public/.deployed-sha'             # live commit
```
