---
name: farm
description: Read-only status of Kalislav's startup farm (EXP-001 etc.): startups/experiments, stages, briefs (startup ideas), owner gates, guardrails, spend, recent events. Use for ANY question about the farm, startups, ideas, briefs, EXP-xxx, n8n stages, or messages the farm bot sent (🧭 briefs, ⛔ guardrails, 🌱 digest). Not related to the job search.
required_credential_files:
  - path: secrets/farm-ro-token
    description: Read-only token for the farm status endpoint (header X-Farm-Token)
---

# Startup farm (read-only)

The farm is Kalislav's own pipeline that finds startup ideas and tests them: n8n on VM 230 runs the stages,
Claude agents do the work in an isolated container, Postgres keeps the state. It is NOT the job search.
You have READ-ONLY access. Never try to change anything, never open gate links, never print the token.
To act (choose a brief, pause, kill), tell Kalislav which link or command to use; he does it himself.

## Data
```bash
TOKEN=$(cat /root/.hermes/secrets/farm-ro-token)
curl -s -H "X-Farm-Token: $TOKEN" https://n8n.home.kalik8s.ru/webhook/farm-status
```
JSON fields:
- `experiments[]`: `id` (EXP-001…), `stage` 1–8 and `stage_name`, `status` (active = ready for the next run, running = a stage is executing now, waiting_owner = waits for Kalislav's decision, blocked, paused, go, killed), `briefs[]` (startup ideas: `slug`, `title`, `channel`, `cpc` = expected cost per click in USD, `price`, `passed` = passed the code check, `failures`), `chosen_brief`, `spent_usd` (real money), `agent_equiv_usd` (Claude subscription usage, API-equivalent, not real money), `issue_url` (GitHub log).
- `stages[]`: 1 Discovery, 2 Brief choice (gate G1), 3 Pre-registration, 4 Landing, 5 Traffic and metrics, 6 Decision (G2), 7 Build MVP, 8 Active users (G3).
- `recent_events[]` (newest first), `guardrail_failures_24h[]`, `kill_switch`, `month_spend_usd` / `month_cap_usd`.

## How to answer
- Russian, short, facts from the JSON only. Never invent ideas, numbers or evidence that are not in the data.
- "Что на ферме?" → per experiment: stage, status, what it waits for, spend; then the last 3–5 events.
- Questions about ideas/briefs → list briefs with title, channel, CPC, price, whether they passed the check and why not.
- If status is `waiting_owner`: say that the decision links are in the farm's Telegram message (one-time links, 72 h, open at home or via Tailscale).
- If the endpoint does not answer: say so; the n8n UI is https://n8n.home.kalik8s.ru, agent traces in https://phoenix.home.kalik8s.ru.
