# Project Digest

## When to use
Automatically via cron at **8:00 UTC** (morning) and **20:00 UTC** (evening).
Manually via Telegram: `/skill project-digest-morning`, `/skill project-digest-evening`, or `/skill project-digest` (defaults to morning).

## Flow
1. Acquire singleton lock (`_pd_digest_lock`) — skip if other digest still running
2. Aggregate data per mode:
   - **morning** (24h window): costs, health (docker + HTTP), review-learn queue, extras
   - **evening** (12h window): costs, git activity, review-learn highlights, research log, extras
3. Format ≤3800 chars output with graceful section truncation
4. Sanitize secrets (sk-, Bearer, JWT, api_key=, hex≥40, env-var names)
5. Send to Telegram via outbox

## Projects scanned (git activity)
- RAG (`/workspace/ro/RAG`)
- Selfmadeagent (`/workspace/ro/Selfmadeagent`)
- VINhunter (`/workspace/ro/VIN OSINT/vinhunter`)
- trading-app (`/workspace/ro/trading-app`)
- hermes (`/workspace/ro/hermes`)

Soft-fail: missing repo → `⚠️ <name>: repo missing`, rest of digest continues.

## HTTP endpoints probed
- RAG: `http://rag-backend:8000/health`
- Selfmadeagent: `http://selfmadeagent:8080/health`

## Extras gate
- Allowlist patterns: `*.log`, `*.jsonl` in `/audit/`
- Denylist: `auth.log`, `secrets.json`, `.env`, `cdp.log`, `cdp_readonly.log`, `llm-proxy.jsonl`, `costs.jsonl`, `review-learn.log`, `cron.log`, `research.log`, `watcher-heartbeat.txt`, `self-learn.log`
- Cap: 10 entries, 1 per file, 180 chars per entry, 16KB line max
- JSONL: pretty-extract `message`/`event`/`type` if present

## Security boundary
Treat all digest output as leaving the system (Telegram = cloud, mobile, screenshots, forwarding). `_pd_sanitize()` masks common secret patterns. Endpoints + project paths are hardcoded — never accept paths/URLs from Telegram input.

## Watch out for
- UTC timezone everywhere (cron `run_at_hour: 8` = 8:00 UTC ≈ 10:00 CEST)
- Mode detection is via `skill_name` substring (`morning`/`evening`) — not via `datetime.now().hour`, which would misbehave under lock delay
- Docker.sock is mounted into hermes container — compromise = root host (known, out of scope to harden in this skill)
- If `costs.jsonl` grows beyond 5000 lines/day, switch to byte-offset checkpointing (currently tail-only via `deque(f, maxlen=5000)`)
