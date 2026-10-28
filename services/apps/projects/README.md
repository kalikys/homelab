# projects

Дашборд долгосрочных проектов: https://projects.home.kalik8s.ru (LAN и Tailscale, без авторизации).
Спек: `docs/superpowers/specs/2026-10-12-projects-dashboard-design.md`.

- API + фронт в одном контейнере на LXC 103, порт 8790, база `/opt/projects/data/projects.db`, бэкапы в `data/backups` (03:30, 14 штук).
- Деплой: `./deploy.sh` (нужен `ssh homeserver`). Proxy host в NPM создаёт `npm_proxy.py`, если есть `.secrets/npm.env`.
- Тесты: `uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements-dev.txt && .venv/bin/pytest -q`.
- Клиент: `client/pj.py` → `ln -s $PWD/client/pj.py ~/.local/bin/pj`; конфиг `~/.config/pj/config.toml` (`url`, `token`).
  Хук `SessionEnd` вызывает `pj session-end`, скилл `project-log` — копия `client/SKILL.md`.
- Включить авторизацию: `AUTH_MODE: token` и `AUTH_TOKEN` в compose, тот же `token` в `config.toml`.
