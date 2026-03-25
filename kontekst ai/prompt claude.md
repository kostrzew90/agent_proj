Prompt dla Claude Code (Opus 4.6) – build lokalnego “AI-aware repo” + RAG (Ollama + opcjonalnie Anthropic)



Skopiuj całość jako jedno polecenie do Claude Code (idealnie w repo, w którym ma to wdrożyć):



Jesteś senior AI Infra/MLOps + Staff Software Engineer. Masz przygotować w tym repo lokalny “AI-aware repo build” oraz RAG nad bazą kodu, działający offline-first, z lokalnym serwerem Ollama (modele 4B–8B) i opcją fallback do API Anthropic (jeśli ustawione klucze).



CEL:

\- Zbuduj narzędzie developerskie, które:

&nbsp; 1) indeksuje repo (kod + configi) do Postgres (pgvector),

&nbsp; 2) buduje graf zależności (code graph),

&nbsp; 3) utrzymuje persistent memory o projekcie (facts/decisions),

&nbsp; 4) udostępnia warstwę semantyczną (zapytania o intencje, komponenty, przepływy),

&nbsp; 5) zapewnia API do Q\&A + “co-pilot architekt” nad repo.



WYMAGANIA NIEFUNKCJONALNE:

\- Nie psuj istniejących usług. Wszystko odpalane osobno przez docker compose lub make targets.

\- Idempotentne: ponowne uruchomienie nie duplikuje danych w DB.

\- “offline-first”: domyślnie Ollama, fallback do Anthropic tylko jeśli ANTHROPIC\_API\_KEY jest ustawiony.

\- Modele docelowe: 4B–8B dla generacji, osobny model/tryb do embeddingów.

\- Postgres jako jedyne persistent storage (pgvector + zwykłe tabele).

\- Szybkie iteracje: incremental indexing na podstawie git diff/mtime.



STACK:

\- Docker Compose: postgres (z pgvector), opcjonalnie adminer/pgadmin, opcjonalnie searxng (nieobowiązkowe).

\- Aplikacja: Python (FastAPI) lub Node (Fastify) – wybierz Python jeśli repo jest pythonowe, inaczej Node. 

\- CLI: komenda `ai\_repo index`, `ai\_repo query`, `ai\_repo graph`, `ai\_repo explain`.

\- Konfiguracja: `.env` + `config.yaml`.



INTEGRACJA Z MODELAMI:

\- Ollama:

&nbsp; - inference: przez endpoint Ollama (http://localhost:11434)

&nbsp; - embedding: użyj modelu embeddingowego dostępnego w Ollama (np. nomic-embed-text) albo innego kompatybilnego.

\- Anthropic fallback:

&nbsp; - jeśli ANTHROPIC\_API\_KEY istnieje, można użyć Anthropic do generacji (nie embeddingów), ale tylko jeśli użytkownik w configu ustawi `llm\_provider=anthropic`.



RAG + GRAPH:

\- Zaimplementuj 2-pasmowe retrieval:

&nbsp; A) “semantic chunks” (embeddingi fragmentów kodu i configów),

&nbsp; B) “structural graph retrieval” (graf: plik -> symbol -> wywołania/importy -> zależności).

\- Re-ranking: prosty lokalny (np. BM25 + embedding score) bez ciężkich modeli.

\- Prompting: odpowiedzi mają cytować ścieżki plików i linie (jeśli dostępne), oraz wskazywać ryzyka zmian.



PERSISTENT MEMORY:

\- Tabela `project\_memory` (facts/decisions) + `memory\_sources`.

\- Auto-bootstrapping: po pierwszym indeksie wygeneruj “Project Map”:

&nbsp; - moduły, usługi, bazy danych, entrypointy, env vars, krytyczne przepływy.

&nbsp; - zapisz do `project\_memory` jako zwięzłe fakty.



DELIVERABLES (w repo):

1\) `docker-compose.ai-repo.yml`

2\) `ai\_repo/` (kod aplikacji i CLI)

3\) `migrations/` (SQL dla pgvector + tabele graph/memory)

4\) `Makefile` lub `justfile`:

&nbsp;  - `make ai-up`, `make ai-index`, `make ai-api`, `make ai-query "..."`, `make ai-graph`

5\) `README\_AI\_REPO.md`:

&nbsp;  - instalacja, wymagania, jak dodać nowe repo, jak działa indexing incremental, jak debugować

6\) Testy minimalne: 2–3 testy na parser, DB insert i query.



SCHEMAT DANYCH (min):

\- documents(id, path, type, hash, mtime, repo\_id)

\- chunks(id, document\_id, chunk\_index, content, start\_line, end\_line, tokens, embedding vector)

\- symbols(id, name, kind, file\_path, start\_line, end\_line)

\- edges(id, src\_kind, src\_id, dst\_kind, dst\_id, edge\_type, weight)

\- project\_memory(id, key, value, confidence, updated\_at)

\- retrieval\_logs(id, query, topk, latency\_ms, provider\_used, created\_at)



ZADANIE:

\- Najpierw przeskanuj repo i zaproponuj decyzje (Python/Node, parser, chunking strategy).

\- Następnie wygeneruj kod + compose + migracje + make targets.

\- Na końcu uruchom “dry run” instrukcji i podaj checklistę walidacyjną.



FORMAT ODPOWIEDZI:

\- Najpierw plan w punktach.

\- Potem zmiany plik po pliku (ścieżka + opis + zawartość).

\- Potem instrukcja uruchomienia.

\- Potem ryzyka i jak cofnąć zmiany.




Aktualizacja 

ROZSZERZENIE: PLUGINS / FUNCTIONS z GitHuba (MCP-enabled)

Chcę, aby system był “core + plugins”:

CORE (stabilny):
- indexing (documents/chunks/embeddings)
- code graph (symbols/edges)
- project memory (facts/decisions)
- retrieval (semantic + graph)
- API/CLI
- MCP server exposing tools

PLUGINS (rozszerzalne, z GitHuba):
- Mogę dodawać funkcje przez repozytoria GitHub (plugin packages) bez edycji core.
- Pluginy mają manifest + wersjonowanie + permissions.
- Każdy plugin rejestruje "tools" do MCP (np. log_analyzer, ci_failure_tracer, security_scan, dependency_audit, changelog_generator).

WYMAGANIA DLA PLUGINS:
1) Standard plugin interface:
   - folder `plugins/` + loader
   - każdy plugin ma `plugin.yaml` (name, version, entrypoint, required_env, permissions, tools list)
   - entrypoint: Python module lub Node module z funkcją `register(context)` zwracającą tool handlers
2) Instalacja pluginów:
   - `ai_repo plugin install <git_url>@<ref>`
   - pobranie do `plugins/_vendor/<name>/<ref>/` (pinning do commita/taga)
   - cache + checksum
3) Bezpieczeństwo:
   - pluginy domyślnie sandbox: brak dostępu do systemu plików poza repo, brak sieci (chyba że w permissions)
   - allowlist permissions w config.yaml
4) Narzędzia MCP:
   - MCP ma endpoint `tools/list` i `tools/call`
   - core wystawia narzędzia: `repo.search`, `repo.graph_neighbors`, `repo.impact_analysis`, `repo.memory_get`, `repo.memory_set`
   - pluginy mogą dodać: `logs.query`, `logs.summarize_window`, `ci.parse`, `sec.scan`, `deps.diff`, `pr.review_bundle`
5) Integracje:
   - Zapewnij prosty adapter do CodeRabbit: endpoint `pr_context_bundle(pr_id)` zwracający:
     - diff summary
     - top changed symbols
     - risk hotspots
     - relevant memory facts
     - optional logs/ci findings (jeśli pluginy włączone)

LOGS / OBSERVABILITY (plugin):
- Zaimplementuj plugin bazowy `plugin-logs`:
  - parsuje logi z plików lub z Loki/Prometheus (opcjonalnie)
  - przechowuje "structured events" w Postgres (bez embeddingowania surowego strumienia)
  - wspiera embedding tylko dla agregatów: incident summaries + rare patterns
  - narzędzia: `logs.top_errors`, `logs.trace_request`, `logs.summarize_last_30m`, `logs.correlate_with_commit`

DELIVERABLES:
- `plugins/README.md` z instrukcją jak pisać pluginy
- `ai_repo plugin ...` komendy
- przykładowy plugin z GitHuba (szablon) jako folder `plugins/examples/plugin-template`
- MCP server który rejestruje narzędzia core + plugin tools w runtime



Co embeddingować, żeby to miało sens (i faktycznie przyspieszało “rozumienie”)?

Log store: trzymasz surowe logi w Loki / plikach / S3 (albo nawet w Postgres, ale to zwykle gorsze).

Structured events w Postgres:

events(ts, service, level, error_signature, trace_id, message, meta_json)

indeksy po ts, service, error_signature

Embeddings tylko dla:

incident_summaries

error_signatures (dedup)

window_summaries

RAG łączy to z code graph:

error_signature → pliki/symbole (jeśli znasz stacktrace)

window_summary → commit/deploy → changed symbols

Plan działania (żebyś mógł to rozwijać z GitHuba)

W core: plugin loader + MCP tool registry.

Pierwsze pluginy (lokalne):

plugin-logs

plugin-ci

plugin-security (np. semgrep wrapper)

Dopiero potem: “plugin install z GitHub” + pin do commita + allowlist permissions.




Czy RAG w tym zadaniu ma sens?

Tak — ale nie jako “magiczne szukanie w logach”, tylko jako warstwa kontekstu dla agentów/narzędzi:

RAG jest bardzo przydatny do:

“Zrozum co się zmieniło w PR i jakie są skutki” (diff + graph + memory)

“Przypomnij, jak wcześniej rozwiązywaliśmy ten typ awarii” (incydenty/lessons learned)

“Pokaż miejsca w kodzie powiązane z błędem z CI” (trace z logów → symbole/pliki)

RAG jest średni do:

“Przepchnij miliony linijek surowych logów przez embeddingi i licz, że będzie szybciej”

Czyli: RAG jako współarchitekt i archiwum wiedzy, a logi/metryki jako dane analityczne (SQL/time-series) z ewentualnym “RAG-em na skrótach”.

C) Logi: czy warto embeddingować dużo danych?
1) Embedding surowych logów — zwykle NIE

Embeddingowanie wszystkiego:

kosztuje czas i miejsce (wektory + indeks)

generuje szum (powtarzalne linie, identyczne stacktrace’y, spam)

często pogarsza trafność (logi są “wysokoentropijne”: ID requestów, timestampy)

I najważniejsze: nie przyspiesza analizy logów, bo analiza logów to zwykle:

agregacje w oknach czasu

liczenie top błędów

korelacje (service, pod, trace_id)

filtrowanie regex/structured fields

To robi się szybciej przez strukturyzację + indeksy w DB/Loki, nie przez wektory.

