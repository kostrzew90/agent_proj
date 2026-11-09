# CLAUDE.md — llmops

Centralny magazyn telemetrii wywołań LLM: koszt, tokeny, latencja, błędy — dla
wszystkich projektów w tym repo, w jednym miejscu. Nie duplikuje Langfuse (treść
promptów/odpowiedzi) ani logów per-projekt — patrz `README.md` dla podziału
odpowiedzialności `llm_calls` / Langfuse / Grafana.

## Architektura

```
projekt (RAG, Argus, ...) --llmops_client.record()--> kolejka w pamięci (wątek)
                                                              |
                                                              v
                                            HTTP POST /v1/calls (llmops-collector)
                                                              |
                                                              v
                                              Postgres: llm_calls + model_pricing
                                                              |
                                                              v
                                          v_llm_calls_costed (widok) --> Grafana
```

- `db-init/01-schema.sql` — tabela `llm_calls` (metryka, bez treści), tabela
  `model_pricing` (cennik wersjonowany po `valid_from`), widok
  `v_llm_calls_costed` (dolicza koszt per wywołanie, `LATERAL` join po najnowszej
  cenie ważnej w momencie wywołania).
- `db-init/02-seed-pricing.sql` — seed cennika. **Ceny płatnych modeli nie zostały
  zweryfikowane u dostawców** — patrz `README.md`.
- `collector/` — FastAPI (`app.py`), waliduje payload (`models.py`, `extra:
  forbid` + walidator odrzucający pola z treścią), zapisuje (`db.py`).
- `client/llmops_client.py` — kanoniczny klient: kolejka w pamięci + wątek roboczy,
  `record(...)` nigdy nie rzuca i nigdy nie blokuje wywołania LLM. Kopie w innych
  projektach generuje `client/sync_clients.py` — **nie edytuj kopii, edytuj
  oryginał i uruchom sync**.
- `grafana/` — provisioning datasource + dashboard (`llm-observability.json`),
  montowane z `argus/docker-compose.yml` (Grafana Argusa jest współdzielona).
- `scripts/retention.sh` — kasuje `llm_calls` starsze niż `LLMOPS_RETENTION_DAYS`
  dni (domyślnie 90), cron na VPS.

## Punkty wpięcia w siedmiu projektach

| Projekt | Plik | Status |
|---|---|---|
| Argus | `argus/argus/llm/router.py` (`_record`) | Wpięte — osobny `try/except Exception: pass`, `LLMOPS_SERVICE` w `docker-compose.yml` |
| kontekst ai | `kontekst ai/ai_repo/core/llm.py` (`_record`) | Wpięte — emisja przed guardem `if not self._db: return`, `tokens_estimated=True` |
| Selfmadeagent | `Selfmadeagent/orchestrator/agent/providers.py` (`call_llm`, `_record_llmops`) | Wpięte — emisja na ścieżce sukcesu i błędu, przed fallbackiem |
| trading-app | `trading-app/core/ollama_client.py` (`generate`/`chat`/`embed`) | Wpięte — bez testów (projekt nie ma infrastruktury testowej) |
| RAG | `RAG/backend/core/llmops_emit.py` (`emit_llmops_calls`), wywoływane z `chat_service.py` (`query_stream`, blok `finally`) | Wpięte — emisja po zakończeniu (sukces), guardowana per-rekord `try/except Exception: continue` |
| mcp-servers/llm-proxy | `mcp-servers/llm-proxy/server.py` (`_record_cost`) | Wpięte — emisja dla `ask_gemini`/`ask_openrouter`/`ask_ollama`/`ask_auto`, `ask_auto` raportuje realnego providera (routing decision), nie literał `"auto"` |
| llmops (sam siebie) | `tests/` | Konsument referencyjny — testy kolektora i klienta |

## Konwencje

- **Telemetria nigdy nie rzuca i nigdy nie blokuje.** Każde wywołanie
  `llmops_client.record(...)` w projekcie konsumenckim żyje w osobnym
  `try/except Exception: pass`, niezależnym od lokalnej logiki (np. lokalnego
  zapisu do bazy projektu). Awaria kolektora/sieci nigdy nie wywraca wywołania
  LLM ani lokalnego zapisu.
- **Zero treści.** `llm_calls` nie przechowuje promptu ani odpowiedzi — tylko
  metadane (projekt, model, tokeny, koszt, latencja, ok/error, `trace_id` do
  skorelowania z Langfuse). Kolektor odrzuca (422) payload z polem treści.
- **Kanoniczny klient w `client/`.** Nie edytuj skopiowanych plików
  `llmops_client.py` w innych projektach — edytuj `client/llmops_client.py` i
  uruchom `python client/sync_clients.py`. `--check` w CI/przed commitem wykrywa
  rozjazd kopii.
- **Cennik: nowy wiersz, nie edycja.** Patrz `README.md` — edycja istniejącego
  wiersza `model_pricing` przeliczyłaby historyczne koszty.
- Porty binduj na `${TAILSCALE_IP:-127.0.0.1}`, nigdy na `0.0.0.0`.
- **Sieć `llmops-shared` (external).** Grafana Argusa i `llmops-postgres` łączą
  się przez wspólną, ręcznie utworzoną sieć zewnętrzną (`docker network create
  llmops-shared`) zamiast jeden stack deklarował sieć drugiego — dzięki temu
  Argus startuje niezależnie od tego, czy stack llmops w ogóle istnieje.

## Komendy testowe

```bash
# llmops samo (wymaga: docker compose --profile test up -d)
cd llmops && pytest tests/ -q

# projekty skonsumowane (patrz tabela wyżej — Argus, kontekst ai, Selfmadeagent, trading-app)
cd argus && pytest tests/test_llm_router.py -v
cd "kontekst ai" && pytest tests/ -v
cd Selfmadeagent/orchestrator && pytest tests/ -v

# spójność kopii klienta we wszystkich projektach
cd llmops && python client/sync_clients.py --check
```

## Granica etapów

- **Etap 1 (ten branch)**: schemat, kolektor, klient, wpięcie we wszystkich
  siedmiu projektach (Argus, kontekst ai, Selfmadeagent, trading-app, RAG,
  mcp-servers/llm-proxy), dashboard Grafany, retencja, dokumentacja.
- **Etap 2 (poza zakresem)**: pełne trace'y treści — to już rola Langfuse, nie
  tego projektu; `llm_calls` celowo tego nie robi.
