# Selfmadeagent — Progress

## Status: Phase 2 done, Phase 3 next

## Phase 1: Foundation — DONE
- [x] docker-compose.yml (6 serwisów)
- [x] 4 migracje SQL (001_core, 002_memory, 003_patterns, 004_monitoring)
- [x] Orchestrator stub (FastAPI /health)
- [x] Claw-core stub (Rust/Axum /health)
- [x] Web UI placeholder (nginx)
- [x] .env + .gitignore
- [x] Wszystkie kontenery działają, baza zainicjalizowana

### Fixes applied:
- Orchestrator healthcheck: `wget` → `python -c urllib` (python:3.12-slim nie ma wget)
- Web-ui depends_on: `service_healthy` → `service_started` (orchestrator healthcheck wolny)
- Langfuse depends_on: `service_healthy` → `service_started` (wolny startup)

### Porty (przesunięte vs design spec — konflikty z RAG/openwebui):
| Serwis | Port |
|--------|------|
| orchestrator | 8100 |
| claw-core | 8180 |
| langfuse | 3100 |
| web-ui | 3101 |
| agent-db | 5436 |
| langfuse-db | 5433 |

### Langfuse credentials (w .env):
- Public: pk-lf-9dcf78a2-4fc5-418f-8721-8383ea279590
- Secret: sk-lf-dd789e8d-8265-49ca-8ff0-d18ea3ab1dc1

## Phase 2: Agent Core — DONE

Plan: `docs/superpowers/plans/2026-04-02-phase2-agent-core.md`

- [x] Task 1: requirements.txt update (litellm, langfuse, httpx, tiktoken, pydantic)
- [x] Task 2: Langfuse setup (`monitoring/langfuse_setup.py`)
- [x] Task 3: LiteLLM provider wrapper (`agent/providers.py`) — Ollama→OpenRouter→OpenAI→Anthropic fallback
- [x] Task 4: Tool registry (`tools/registry.py`) — 6 tools in OpenAI function-calling format
- [x] Task 5: Claw-core bridge (`tools/claw_bridge.py`) — Python fallback for all tools
- [x] Task 6: Session manager (`agent/sessions.py`) — DB-backed sessions + episodes
- [x] Task 7: Context manager (`agent/context_manager.py`) — token budgeting, 12800 token budget
- [x] Task 8: Agent loop (`agent/loop.py`) — multi-turn tool calling, max 10 rounds
- [x] Task 9: main.py — /chat, /sessions, /ws WebSocket endpoints
- [x] Task 10: Build + integration test — all passing

### Fix applied:
- httpx 0.28.1 → 0.27.2 (litellm 1.57.2 requires httpx<0.28.0)

### Verified:
- Health: `{"status":"ok","db":"connected"}`
- Chat creates session, persists to DB, logs episodes
- Agent loop successfully calls Ollama, processes tool calls, logs to Langfuse

## Phase 3-9: NOT STARTED
See design spec: `docs/2026-04-02-selfmadeagent-design.md`
