# Final whole-branch review fixes — report

Date: 2026-09-09

## Follow-up: item 5 regression (dashboard lost DB access)

The `${TAILSCALE_IP:-127.0.0.1}:5436` datasource host broke on any machine
where `TAILSCALE_IP=127.0.0.1` (dev), since `127.0.0.1` inside the Grafana
container is its own loopback, not the host's. Fixed by:

- `argus/docker-compose.yml`, `grafana` service: added
  `extra_hosts: ["host.docker.internal:host-gateway"]`.
- `llmops/grafana/datasource-llmops.yml`: `url` changed from
  `${TAILSCALE_IP:-127.0.0.1}:5436` to `host.docker.internal:5436`.

No external network reintroduced; `llmops-postgres`'s port binding in
`llmops/docker-compose.yml` (`${TAILSCALE_IP:-127.0.0.1}:5436:5432`)
untouched.

**Verified live, not assumed:** on this dev machine `TAILSCALE_IP=127.0.0.1`
(from `argus/.env`), so `llmops-postgres` is bound only to `127.0.0.1:5436` on
the host. Confirmed `docker exec argus-grafana getent hosts
host.docker.internal` resolves, then hit Grafana's own API (`admin`/
`devpassword` from `argus/.env`):

- `GET /api/datasources/uid/llmops-pg/health` → `{"message":"Database
  Connection OK","status":"OK"}` (previously the reported 500).
- `POST /api/ds/query` (`select project, provider, model, ok,
  pricing_missing, cost_usd from v_llm_calls_costed order by ts desc`) →
  `status:200` with real rows, including `["rag", "openrouter",
  "openai/gpt-4o-mini", true, false, null]` (rag, priced — pricing_missing
  false) and `["hermes","openrouter","nieznany/model",false,true,null]`
  (hermes, `pricing_missing:true` as expected for an unpriced model). Full
  response body captured in this session's tool output.

So on Docker Desktop (this host), `host.docker.internal` does reach a
service bound to the host's `127.0.0.1` — Docker Desktop's gateway forwards
to host loopback-bound ports, unlike native Linux where a `127.0.0.1` bind
would not be reachable from a container. This was verified, not assumed; if
a native-Linux VPS deployment ever shows `host.docker.internal` failing to
reach a `127.0.0.1`-bound `llmops-postgres`, the fix there is to set a real
`TAILSCALE_IP` in that host's `.env` (already the documented production
setup) rather than relying on loopback forwarding.

`cost_usd` returned `null` for every row in the query above (including the
rag rows where `pricing_missing=false`) — this looks like a pre-existing
`v_llm_calls_costed` costing gap unrelated to the network/datasource fix
just made; flagging it, not fixing it, since it's outside this regression's
scope.

## Items fixed

1. **llm-proxy `ask_auto` reports real provider.** `_record_cost` gained an
   optional `provider` kwarg; `ask_auto` now tracks `provider_used` alongside
   `model_used` for every routing branch (openrouter/ollama/gemini/ollama/…)
   and passes it through, so the literal `"auto"` is never recorded.
   `ask_gemini`/`ask_openrouter`/`ask_ollama` unchanged (still derive provider
   from `tool.replace("ask_", "")`).
   Test added: `test_ask_auto_records_real_provider_not_auto` in
   `mcp-servers/llm-proxy/tests/test_server.py` — patches `llmops_client.record`
   and asserts `provider == "gemini"` (never `"auto"`) for a medium-tier call.
   Files: `mcp-servers/llm-proxy/server.py`, `mcp-servers/llm-proxy/tests/test_server.py`.

2. **`llmops_emit.py` import guarded.** Moved `from core import llmops_client`
   inside the per-record `try` in `RAG/backend/core/llmops_emit.py`. The
   function is now incapable of raising regardless of import success.

3. **Docs corrected.** `llmops/CLAUDE.md` table and "Granica etapów" section
   updated — RAG and llm-proxy now documented as wired (verified via
   `chat_service.py:481-482` and `server.py` `_record_cost`), matching commits
   `8146618`/`91fe15c`. "Etap 2 odłożone" language removed.

4. **Deployment env wiring.**
   - `Selfmadeagent/docker-compose.yml`: added `LLMOPS_URL`, `LLMOPS_TOKEN`,
     `LLMOPS_PROJECT: selfmadeagent`, `LLMOPS_SERVICE: orchestrator`,
     `LLMOPS_ENV`/`LLMOPS_HOST` (env-var defaults, not hardcoded, since this
     project's deployment host wasn't confirmed) to the `orchestrator` service.
   - `llmops/README.md`: new section "Aktywacja telemetrii tam, gdzie nie ma
     własnego docker-compose" — exact file + service/env-file for llm-proxy
     (`hermes/docker-compose.yml` service `hermes-llm-proxy` + `hermes/.env`),
     kontekst ai (`kontekst ai/.env`, read via `ai_repo/config.py`), trading-app
     (`trading-app/.env`, read via `config.py`).

5. **Argus no longer depends on the llmops stack to boot.** Removed
   `llmops_net: external: true` and its `networks:` mapping on the `grafana`
   service from `argus/docker-compose.yml`. Repointed the Grafana datasource
   (`llmops/grafana/datasource-llmops.yml`) from the docker-network hostname
   `llmops-postgres:5432` to `${TAILSCALE_IP:-127.0.0.1}:5436` — the
   host-published-port pattern already used elsewhere in this repo for
   cross-stack access. Verified: `docker compose config` in `argus/` exits 0
   with no `llmops_net`/`llmops_default` reference anywhere in the resolved
   config.

6. **Dead `('ollama','ANY',0,0)` seed row removed** from
   `llmops/db-init/02-seed-pricing.sql`, replaced with a comment explaining the
   exact-match join and a copy-pasteable example `INSERT` for a real model name.

7. **`last_usage_tokens` concurrency comment added** at its definition in
   `RAG/backend/core/embeddings.py` (`EmbeddingClient.__init__`), documenting
   the `--concurrency=1` dependency of the Celery-worker singleton.

8. **Known limitation documented.** `llmops/README.md` — new section stating
   RAG's `ok=True` is correct for records it emits (only emitted after success)
   but means RAG's LLM error rate always reads 0% in Grafana; not a
   restructure, explicitly out of scope.

## Verification (real numbers)

- `llmops/`: `pytest tests/ -q` → **21 passed**.
- `mcp-servers/llm-proxy/`: `pytest tests/ -q` → **28 passed, 6 failed**. The 6
  failures are the pre-existing `test_ask_auto_*` ones (all compare `ask_auto`'s
  return value to a plain string; `ask_auto` returns a JSON string — unrelated
  to this fix). Count vs. baseline: unchanged at 6 failures; passed count went
  from 27→28 because of the new test I added.
- `RAG/backend/`: `pytest tests/ -q` → **14 passed**.
- `argus/`: `docker compose config` → exit 0, no `llmops_net`/`llmops_default`
  anywhere in the resolved config (confirmed via grep on the output).

## Approach to item 5

Removed the `external: true` `llmops_net` dependency entirely rather than
making it optional/soft, since Argus's own services (`app`, `liq-listener`,
`argus-guardian`) never used that network — only `grafana` did, purely to
resolve `llmops-postgres` by docker DNS name. Repointed Grafana's llmops
datasource at the host's Tailscale IP + llmops-postgres's published port 5436
(already bound to `${TAILSCALE_IP:-127.0.0.1}` per this repo's convention),
so Grafana reaches it over the host network instead of a shared docker
network. This makes the entire Argus stack independent of whether the llmops
stack exists.

## Concerns / notes

- Two pre-existing untracked empty files were already present in this worktree
  before I started (`argus/grafana/provisioning/dashboards/llmops.yml`,
  `argus/grafana/provisioning/datasources/llmops.yml`, both 0 bytes, dated
  before this session). They are not referenced by `docker-compose.yml` (which
  mounts the real files from `../llmops/grafana/`), so they're inert, but I
  could not remove them — the sandbox's Bash classifier blocked the `rm`/`rmdir`
  call. Flagging so the user can delete them manually if desired.
- Selfmadeagent's actual deployment host was not confirmed in the repo, so
  `LLMOPS_ENV`/`LLMOPS_HOST` there use `${VAR:-production}`/`${VAR:-}` rather
  than a hardcoded `contabo-vps` like Argus/RAG — set the real values in that
  project's `.env` before relying on the telemetry.
- No new dependencies added; no vendored `llmops_client.py` copies modified;
  `cost_usd` is never passed to `llmops_client.record(...)` anywhere touched.
