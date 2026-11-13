# Autodeploy of the projects dashboard (GitOps pull)

LXC 103: every 5 minutes `projects-deploy.timer` fetches `main` of this public repo into `/opt/projects-repo`;
on a new commit `projects-deploy` copies `services/apps/projects/` into `/opt/projects` (never `data/`,
`ts-state/`, `.env`; `tests/` and `client/` are not shipped), runs `docker compose up -d --build`, checks
`/api/health` and restores the previous code if the check fails. No keys: the repo is public, the container only pulls.

Change the dashboard only through a PR to `main`; hand edits in `/opt/projects` are overwritten.

## Install (once)

```sh
scp services/apps/projects/autodeploy/projects-deploy.{sh,service,timer} homeserver:/tmp/
ssh homeserver 'sudo pct push 103 /tmp/projects-deploy.sh /usr/local/sbin/projects-deploy --perms 0755 \
  && sudo pct push 103 /tmp/projects-deploy.service /etc/systemd/system/projects-deploy.service \
  && sudo pct push 103 /tmp/projects-deploy.timer /etc/systemd/system/projects-deploy.timer \
  && sudo pct exec 103 -- systemctl daemon-reload && sudo pct exec 103 -- systemctl enable --now projects-deploy.timer'
```

## Operate

```sh
ssh homeserver 'sudo pct exec 103 -- bash -c "FORCE=1 projects-deploy"'        # deploy main now
ssh homeserver 'sudo pct exec 103 -- journalctl -u projects-deploy -n 30'       # last runs
ssh homeserver 'sudo pct exec 103 -- cat /opt/.projects-deployed-sha'           # live commit
```
