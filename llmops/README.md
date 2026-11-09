# llmops

Centralna telemetria wywołań LLM dla siedmiu projektów w tym repo: RAG, Argus,
mcp-servers/llm-proxy, Selfmadeagent, kontekst ai, trading-app (i sam llmops jako
konsument w testach). Odpowiada na jedno pytanie, na które żaden z tych projektów
osobno nie odpowiada: ile to kosztuje i gdzie się psuje, w jednym miejscu.

## Zasada podziału (nie duplikować)

- **`llm_calls` (ta baza)** = metryka: projekt, model, tokeny, koszt, latencja,
  ok/error. Płaskie wiersze, tanie do agregacji, retencja 90 dni.
- **Langfuse** = trace: pełna treść promptu/odpowiedzi, per-projekt, do debugowania
  konkretnego wywołania. Ta baza NIGDY nie przechowuje treści (patrz niżej).
- **Grafana** = kokpit: dashboard nad `llm_calls`, do pytania "ile wydaliśmy dziś"
  bez logowania się do siedmiu różnych projektów.

Jeśli potrzebujesz treści promptu — to Langfuse, nie to. Jeśli potrzebujesz kosztu
i trendu — to tutaj.

## Uruchomienie

Raz na host — utwórz wspólną sieć, przez którą Grafana Argusa łączy się z bazą
`llmops-postgres:5432` po nazwie kontenera. Sieć jest zewnętrzna celowo — żeby
żaden ze stacków (Argus, llmops) nie blokował startu drugiego:

```bash
docker network create llmops-shared   # raz na host; idempotentnie: || true
```

```bash
docker compose up -d
```

Startuje:
- `llmops-postgres` — baza `llmops`, port `${TAILSCALE_IP:-127.0.0.1}:5436`
- `llmops-collector` — kolektor HTTP, port `${TAILSCALE_IP:-127.0.0.1}:8090`

Port kolektora na hoście ustawia `LLMOPS_PORT` (domyślnie `8090`) — zmień go,
jeśli ten port jest zajęty przez inną usługę.

Dashboard Grafany (prowizjonowany z `argus/docker-compose.yml`, patrz Task 7) jest
dostępny pod `:3000` na tym samym hoście co Argus.

Kolektor testowy (`llmops-collector-test`, port `8091`) NIE startuje przy zwykłym
`docker compose up -d` — patrz sekcja Testowanie.

## Jak dopisać model do cennika

```sql
INSERT INTO model_pricing (provider, model, usd_per_mtok_in, usd_per_mtok_out)
VALUES ('openrouter', 'nowy/model', 0.50, 1.50);
```

**Zmiana ceny istniejącego modelu = nowy wiersz z nowym `valid_from`, NIGDY edycja
istniejącego wiersza.** `v_llm_calls_costed` dobiera cenę per wywołanie na podstawie
`valid_from <= ts` (najnowsza pasująca). Edycja istniejącego wiersza cofnęłaby się w
czasie i przeliczyła historyczne koszty na nową cenę — po to jest `valid_from`, żeby
tego nigdy nie trzeba było robić:

```sql
INSERT INTO model_pricing (provider, model, usd_per_mtok_in, usd_per_mtok_out, valid_from)
VALUES ('openrouter', 'openai/gpt-4o-mini', 0.20, 0.80, now());
```

Stary wiersz zostaje nietknięty i nadal poprawnie ceni wywołania sprzed zmiany.

### Zadanie otwarte: zweryfikować ceny

Ceny płatnych modeli w `db-init/02-seed-pricing.sql` (obecnie tylko
`openai/gpt-4o-mini`, `0.15`/`0.60` USD za milion tokenów) zostały **przepisane z
kodu w tym repo, nie zweryfikowane na stronach cenowych dostawców**. To jest
otwarte zadanie dla człowieka — przed poleganiem na kosztach z tego dashboardu przy
podejmowaniu decyzji, ktoś musi potwierdzić te liczby u źródła (openrouter.ai,
platform.openai.com/pricing, itp.) i w razie rozbieżności dopisać poprawiony
wiersz zgodnie z zasadą `valid_from` powyżej — nie edytować.

## Jak dopiąć nowy projekt

1. Skopiuj kanonicznego klienta do nowego projektu:
   ```bash
   python client/sync_clients.py
   ```
   (dodaj ścieżkę projektu do `TARGETS` w `client/sync_clients.py` najpierw).
2. W nowym projekcie ustaw zmienne środowiskowe `LLMOPS_URL`, `LLMOPS_TOKEN`,
   `LLMOPS_PROJECT`, `LLMOPS_SERVICE`, `LLMOPS_ENV`, `LLMOPS_HOST` (patrz przykłady
   w `argus/docker-compose.yml`).
3. Wywołaj `llmops_client.record(...)` w miejscu, gdzie kończy się wywołanie LLM —
   zawsze w osobnym `try/except Exception: pass`, żeby telemetria nigdy nie mogła
   wywrócić właściwego wywołania.

## Aktywacja telemetrii tam, gdzie nie ma własnego docker-compose

Hook (`record(...)`) jest już wpięty w kodzie tych trzech projektów, ale bez
zmiennych `LLMOPS_*` w środowisku klient jest cichym no-opem — telemetria nie
aktywuje się sama. W przeciwieństwie do Argusa/RAG/Selfmadeagent te trzy nie mają
własnego (uruchamianego) docker-compose dla procesu, który woła LLM, więc zmienne
trzeba ustawić ręcznie w miejscu, gdzie dany proces faktycznie czyta środowisko:

- **mcp-servers/llm-proxy** — proces `hermes-llm-proxy` startuje z
  `hermes/docker-compose.yml` (serwis `hermes-llm-proxy`, build z
  `../mcp-servers/llm-proxy`). Dopisz do jego bloku `environment:` (obok
  `GEMINI_API_KEY`, `OPENROUTER_API_KEY` itd.):
  `LLMOPS_URL`, `LLMOPS_TOKEN`, `LLMOPS_PROJECT: llm-proxy`,
  `LLMOPS_SERVICE: hermes-llm-proxy`, `LLMOPS_ENV: production`,
  `LLMOPS_HOST: contabo-vps` (lub odpowiedni host wdrożenia). Wartości
  `LLMOPS_URL`/`LLMOPS_TOKEN` bierz z `hermes/.env` (dopisz je tam, kompozycja
  już czyta ten plik dla pozostałych sekretów tego serwisu).
- **kontekst ai** — proces czyta zmienne przez `_load_dotenv` w
  `kontekst ai/ai_repo/config.py` z pliku `kontekst ai/.env` (wzorzec:
  `kontekst ai/.env.example`). Dopisz tam: `LLMOPS_URL`, `LLMOPS_TOKEN`,
  `LLMOPS_PROJECT=kontekst-ai`, `LLMOPS_SERVICE=ai-repo`, `LLMOPS_ENV=production`,
  `LLMOPS_HOST=<host, na którym proces faktycznie działa>`.
- **trading-app** — proces czyta zmienne przez `load_dotenv()` w
  `trading-app/config.py` z pliku `trading-app/.env` (wzorzec:
  `trading-app/.env.example`). Dopisz tam: `LLMOPS_URL`, `LLMOPS_TOKEN`,
  `LLMOPS_PROJECT=trading-app`, `LLMOPS_SERVICE=streamlit`, `LLMOPS_ENV=production`,
  `LLMOPS_HOST=<host, na którym proces faktycznie działa>`.

Bez tego kroku `record(...)` w tych trzech projektach wykonuje się (kod jest
wpięty), ale `llmops_client` widzi pusty `LLMOPS_URL` i nic nie wysyła —
"7 projektów w telemetrii" pozostaje częściowo puste mimo poprawnego kodu.

Weryfikacja spójności kopii klienta we wszystkich projektach:
```bash
python client/sync_clients.py --check   # exit 1, jeśli ktoraś kopia sie rozjechala
```

## Panel "wywołania bez cennika"

Jeśli panel w Grafanie pokazuje wiersze z `pricing_missing = true` — to znaczy, że
jakiś projekt woła model, którego nie ma w `model_pricing`. **Dopisz model do
cennika (patrz wyżej), nie ignoruj.** Ignorowanie oznacza, że koszt tego modelu
cicho znika z sumy kosztów zamiast być widoczny jako $0-ale-w-rzeczywistości-płatny.

## Znane ograniczenie: RAG nigdy nie raportuje błędów (`ok=False`)

`RAG/backend/core/llmops_emit.py` woła `llmops_client.record(..., ok=True)` na
sztywno. To jest faktycznie poprawne dla rekordów, które emituje — RAG dopisuje
wpis do `call_records` dopiero PO udanym wywołaniu LLM, więc każdy rekord, który w
ogóle dociera do `emit_llmops_calls`, faktycznie się udał. Konsekwencja: nieudane
wywołania LLM w RAG (wyjątek, timeout, błąd providera) nigdy nie tworzą wiersza w
`llm_calls` — RAG error rate w Grafanie zawsze pokaże 0%, niezależnie od
rzeczywistej awaryjności. **0% error rate dla RAG nie jest dowodem, że nic się nie
psuje — to dowód, że porażki są niewidoczne dla tej telemetrii.** Naprawa
wymagałaby przebudowy ścieżek błędów w RAG (emisja rekordu również przy
wyjątku) — to celowo poza zakresem tego projektu.

## Retencja

`scripts/retention.sh` kasuje wiersze z `llm_calls` starsze niż
`LLMOPS_RETENTION_DAYS` (domyślnie 90). Zainstalowane jako cron na VPS:

```bash
chmod +x scripts/retention.sh
crontab -e
# dopisz:
0 4 * * * /path/to/llmops/scripts/retention.sh >> /var/log/llmops-retention.log 2>&1
```

`model_pricing` nigdy nie jest kasowane — to katalog cennika, nie telemetria.

## Testowanie

Ten projekt utrzymuje **dwie bazy**: `llmops` (produkcyjna) i `llmops_test`
(izolowana, wyłącznie dla testów). Testy piszą i kasują dane w `llm_calls`
(`TRUNCATE` przy każdym teście) — puszczenie ich na produkcyjnej bazie
skasowałoby prawdziwą historię telemetrii.

Guard w `tests/conftest.py`'s `db` fixture odmawia działania na jakiejkolwiek
bazie, której nazwa nie kończy się na `_test`. Jeśli zobaczysz błąd:

```
SAFETY GUARD: Test suite can only run against databases ending with '_test'.
Current database: llmops
```

`.env` pozostaje produkcyjny (`LLMOPS_DB_NAME=llmops`) i **nie należy** go
przestawiać pod testy — testy domyślnie i bez żadnej konfiguracji celują w
`llmops_test`. Nadpisać to da się przez `LLMOPS_TEST_DB_NAME` (samą nazwę bazy)
albo `LLMOPS_TEST_DSN` (całe DSN). Guard nadal odmawia pracy na bazie bez
końcówki `_test` — nie usuwaj go.

`tests/test_collector.py` testuje przez prawdziwe HTTP realny kolektor ASGI, nie
in-process test client — dlatego istnieje **osobny kontener kolektora**,
`llmops-collector-test`, wpięty w `llmops_test` zamiast w `llmops`, publikowany na
porcie `8091`. Żyje za profilem compose `test`, żeby nigdy nie wystartował
przypadkiem na produkcyjnym VPS przy zwykłym `docker compose up -d`:

```bash
docker compose --profile test up -d   # startuje TAKŻE llmops-collector-test
pytest tests/ -q
```

`LLMOPS_TEST_URL` (domyślnie `http://127.0.0.1:8091`) pozwala nadpisać adres
testowego kolektora, jeśli trzeba.

## Powiązane projekty (Taski 4-6)

Patrz `llmops/CLAUDE.md` — tabela punktów wpięcia we wszystkich siedmiu projektach.
