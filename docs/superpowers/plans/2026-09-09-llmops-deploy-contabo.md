# LLMOps — deploy na Contabo VPS

> Plan wdrożeniowy, nie implementacyjny. Kod Etapu 1 jest gotowy i scalony do
> `feat/argus-phase1` (`b8fa5ee`). Ten dokument opisuje wyłącznie uruchomienie go
> na produkcji.

---

## STAN WDROZENIA — 2026-09-09 (jedno miejsce prawdy)

| Faza | Status | Dowod |
|---|---|---|
| 0. Ceny + dashboard lokalnie | ZROBIONE | gpt-4o-mini 0.15/0.60 potwierdzone u dostawcy; uzytkownik obejrzal panele |
| 1. Stack llmops na VPS | ZROBIONE | publiczny IP HTTP 000, tailnet `{"status":"ok"}`, 401 bez tokenu, 8 wierszy cennika |
| 2. Dashboard w Grafanie | ZROBIONE | `Database Connection OK`, 10/10 zapytan paneli bez bledu |
| 3. Argus + RAG | **ODLOZONE** | kod na VPS sprzed telemetrii — `ImportError` klienta w obu kontenerach |
| 4. llm-proxy, kontekst-ai, trading-app, Selfmadeagent | NIE ZACZETE | blokuje to samo co Faze 3 + otwarte pytanie o hosting |
| 5. Retencja (cron) | NIE ZACZETE | |
| 6. Domkniecie po dobie | NIE ZACZETE | wymaga Fazy 3 |

**Telemetria NIE ZBIERA jeszcze danych** — `llm_calls` jest puste i takie zostanie,
dopoki producenci nie dostana kodu z hookami. Infrastruktura jest gotowa i czeka.

**Adresy:** kolektor `http://100.71.197.18:9091` (port 9091, bo 8090 zajmuje
widok-app), Grafana `http://100.71.197.18:3000` → dashboard „LLM Observability"
(folder `General`). Baza `llmops` na `:5436`, dostepna tylko przez tailnet.

**Commity:** `90fca0d` (wdrozenie: LLMOPS_PORT + siec llmops-shared + datasource),
wczesniej `b8fa5ee` (rozdzielenie zmiennej bazy testowej), `24cf51b` i starsze
(Etap 1). Galaz `feat/argus-phase1`, **niewypchnieta** na origin (repo jest
publiczne — swiadoma decyzja o publikacji nie zostala podjeta).

**Backupy na VPS przed kazda zmiana:** `~/argus/docker-compose.yml.bak-2026-09-09`,
`~/rag/docker-compose.vps.yml.bak-2026-09-09`, `~/argus/.env.bak-*`, `~/rag/.env.bak-*`.

**Dlugi do domkniecia:** (1) provisioning nie aktualizuje dashboardu — Grafana
13.1.3 `Cannot change resource manager identity`; (2) status modeli darmowych
u dostawcow nieustalony; (3) 6 czerwonych testow `ask_auto` w llm-proxy z commita
`da87c22` — spoza tego projektu.

---

**Cel:** telemetria LLM z siedmiu projektów trafia do jednej bazy na Contabo, a
dashboard w Grafanie pokazuje realny koszt — zamiast, jak dziś, próbek wstawionych
ręcznie na laptopie.

**Kryterium sukcesu (jedno, weryfikowalne):** po 24 h od wdrożenia
`SELECT project, count(*) FROM llm_calls WHERE ts > now() - interval '24 hours' GROUP BY project`
zwraca wiersze dla **każdego projektu, który w tym czasie faktycznie wołał LLM** —
a panel „wywołania bez cennika" jest pusty albo zawiera wyłącznie modele, o których
wiemy, że są nowe.

**Host:** Contabo, publiczny `169.58.146.162`, tailnet `100.71.197.18`
(patrz pamięć: `reference_contabo_vps`). SSH przez **publiczny** IP z kluczem
`~/.ssh/id_ed25519` — połączenie po tailnecie to Tailscale SSH, które wisi bez
autoryzacji w przeglądarce.

---

## Założenia i otwarte pytania

**Założenie A (rozstrzygnięte):** `LLMOPS_URL` dla producentów spoza VPS to
`http://100.71.197.18:9091`. Adres tailnetu działa zarówno z samego VPS-a, jak i z
laptopa czy Mac Studio, więc nie musimy rozstrzygać hostingu z góry. Producenci
działający na VPS w tej samej sieci Dockera mogą użyć nazwy kontenera
(`http://llmops-collector:8080`), co jest szybsze i nie wychodzi na tailnet — ale
wymaga wpięcia ich w sieć `llmops_default`.

**Otwarte pytanie 1 (blokuje Fazę 4, nie wcześniejsze):** gdzie faktycznie działa
każdy z czterech producentów bez wzorca `TAILSCALE_IP` — `hermes/llm-proxy`,
`Selfmadeagent`, `kontekst ai`, `trading-app`? Repo tego nie rozstrzyga. Do
ustalenia projekt po projekcie w Fazie 4; każdy jest niezależny, więc brak
odpowiedzi o jednym nie blokuje pozostałych.

**Otwarte pytanie 2 (nie blokuje niczego):** czy Selfmadeagent wołający Ollamę na
Mac Studio ma raportować `LLMOPS_HOST=mac-studio` czy host orchestratora.
Rekomendacja: host **procesu**, bo telemetria opisuje, kto wywołał, nie gdzie stoi
model. Odwrotna decyzja jest równie obronna — wymaga tylko konsekwencji.

---

## Faza 0 — przed dotknięciem VPS-a

Dwie rzeczy tanie teraz, drogie po wdrożeniu.

- [x] **0.1 Zweryfikuj ceny płatnych modeli u dostawców.** ✅ **ZROBIONE 2026-09-09.**
  `openrouter/openai/gpt-4o-mini` = **0.15 / 0.60 USD za 1M** — potwierdzone na
  stronie modelu w OpenRouter, zgodne z `db-init/02-seed-pricing.sql`. To jedyny
  realnie płatny wpis w cenniku, więc ryzyko „koszt liczony ze zmyślonej ceny"
  jest zamknięte.

  **Nierozstrzygnięte (świadomie, nie blokuje deployu):** status modeli darmowych
  (OpenRouter `:free`, Gemini, Groq). Research zwrócił wynik wewnętrznie sprzeczny
  — te same pozycje oznaczone jako „NIE USTALONO" w tabeli i jako „na pewno
  wycofane" w podsumowaniu, przy źródłach z serwisów trzecich zamiast od dostawców.
  Nie przyjęto tego za ustalenie. Konsekwencja dla wdrożenia jest znikoma: model,
  który zniknął, przestaje generować wywołania, a nowy wypłynie na panelu
  „wywołania bez cennika". Jedyne realne ryzyko to model wpisany u nas jako `0/0`,
  który stał się płatny — wychwyci to porównanie sumy kosztów z rachunkiem
  dostawcy, nie ten cennik.

  **Osobny wątek, poza tym planem:** sygnał, że modele wołane przez `llm-proxy`
  (fallbacki w `ask_auto`) mogły zostać wycofane u dostawców. Dotyczy działania
  proxy, nie cennika LLMOps. Możliwy związek z 6 czerwonymi testami `ask_auto`
  pochodzącymi z commita `da87c22`.
- [x] **0.2 Obejrzyj dashboard lokalnie** (`http://127.0.0.1:3000`, folder LLMOps).
  Wszystkie 10 paneli zwraca dane (sprawdzone przez API), ale nikt nie widział
  layoutu. Lepiej znaleźć krzywy panel lokalnie niż na produkcji.
  *Weryfikacja:* panele renderują się, jednostki (USD, tokeny, %) wyglądają sensownie.

---

## Faza 1 — stack llmops na VPS

- [x] **1.1 Wgraj kod.** Na VPS jest już `~/argus` i `~/rag` jako osobne katalogi.
  Zachowaj wzorzec: `~/llmops`. Sposób (git clone vs rsync) — jak przy poprzednich
  deployach tego repo.
- [x] **1.2 Utwórz `~/llmops/.env` z produkcyjnymi wartościami.** Nie kopiuj
  `.env.example` bez zmian — ma same `changeme`:
  - `TAILSCALE_IP=100.71.197.18` — **krytyczne**. Domyślka to `127.0.0.1`; przy
    niej kolektor byłby nieosiągalny dla producentów spoza VPS-a. Odwrotny błąd
    (`0.0.0.0`) wystawiłby telemetrię publicznie, bo **Docker omija ufw na tym
    hoście**.
  - `LLMOPS_DB_PASSWORD=<silne, wygenerowane>` — **hasło jest ustawiane tylko przy
    pierwszej inicjalizacji wolumenu**. Zmiana po fakcie wymaga `ALTER USER`, nie
    edycji `.env`. Ustal je teraz i zapisz w tym samym miejscu, co pozostałe
    sekrety VPS-a.
  - `LLMOPS_TOKEN=<silny, wygenerowany>` — ten sam ciąg trafi do wszystkich
    siedmiu producentów. Bez niego kolektor odrzuca zapisy (401).
  - `LLMOPS_DB_NAME=llmops` — zostaw produkcyjne. Testy mają własną
    `LLMOPS_TEST_DB_NAME` i **nie wymagają** zmiany tej zmiennej (`b8fa5ee`).
- [x] **1.3 Podnieś stack: `docker compose up -d`.** Bez `--profile test` —
  profil testowy startuje drugi kolektor piszący do bazy `llmops_test` i na
  produkcji nie ma czego szukać.
  *Weryfikacja:* `docker compose ps` pokazuje `llmops-postgres` (healthy) i
  `llmops-collector`, a `llmops-collector-test` **nie istnieje**.
- [x] **1.4 Sprawdź, że schemat i cennik wstały.**
  *Weryfikacja:* `SELECT count(*) FROM model_pricing` zwraca **8** (tyle ma seed; dziewiaty wiersz w lokalnej bazie to artefakt testu);
  `\dv` pokazuje `v_llm_calls_costed`.
- [x] **1.5 Sprawdź granicę sieciową — to nie jest formalność.**
  *Weryfikacja:* `curl http://100.71.197.18:9091/health` z tailnetu zwraca
  `{"status":"ok"}`, a `curl http://169.58.146.162:9091/health` z zewnątrz
  **nie odpowiada**. Jeśli odpowiada — telemetria wisi w internecie, zatrzymaj
  wdrożenie i popraw binding.
- [x] **1.6 Sprawdź, że token faktycznie chroni.**
  *Weryfikacja:* `POST /v1/calls` bez nagłówka `Authorization` zwraca 401.

---

## Faza 2 — dashboard w Grafanie Argusa

Grafana jest współdzielona: dashboard i datasource montują się z `argus/docker-compose.yml`.

- [x] **2.1 Zaktualizuj `~/argus` do wersji z `feat/argus-phase1`** — to ona wnosi
  montowanie `llmops/grafana/` oraz `extra_hosts: host.docker.internal:host-gateway`.
- [x] **2.2 Dopisz `LLMOPS_DB_*` do `~/argus/.env`** (user, hasło, nazwa bazy —
  te same wartości co w Fazie 1.2). Grafana czyta je przy provisioningu datasource.
- [x] **2.3 Uwaga na ścieżkę połączenia Grafany.** Datasource celuje w
  `host.docker.internal:5436`. Na Docker Desktop to działa z automatu, na Linuksie
  **tylko dzięki `extra_hosts: host-gateway`** z kroku 2.1. To był realny defekt
  naprawiany dwa razy — wcześniejsza wersja używała `TAILSCALE_IP`, co wewnątrz
  kontenera Grafany wskazywało jej własny loopback.
  *Weryfikacja:* `/api/datasources/uid/llmops-pg/health` zwraca
  `"Database Connection OK"`. **Nie** poprzestawaj na tym, że kontener wstał.
**Ustalenia Fazy 2 (2026-09-09) — sciezka polaczenia byla ZLA i zostala przebudowana:**
`host.docker.internal` NIE dziala na tym hoscie. Grafana siedzi w sieci `argus_default`
(172.18.x), Postgres LLMOps w `llmops_default` (172.21.x), a Docker nie trasuje miedzy
mostkami — nieosiagalne byly wszystkie warianty: brama, tailnet i IP kontenera.
Rozwiazanie: wspolna siec zewnetrzna `llmops-shared` (tworzona raz przez
`docker network create llmops-shared`), do ktorej naleza oba kontenery; datasource
laczy sie po nazwie `llmops-postgres:5432`. Siec jest external CELOWO — jest trwalym
zasobem hosta, wiec Argus nie zalezy od stacku LLMOps (wymog ze specu). `extra_hosts`
usuniete jako martwe. Zweryfikowane: `Database Connection OK` + 10/10 zapytan paneli
wykonuje sie bez bledu.

**DLUG (nie blokuje, do domkniecia pozniej):** provisioning nie moze aktualizowac
dashboardu — Grafana 13.1.3 zwraca w kolko `Cannot change resource manager identity`,
a dashboard wylsdowal w folderze `General` zamiast `LLMOps`. Skutek: dashboard DZIALA,
ale przyszle zmiany w `llm-observability.json` NIE wjada automatycznie. API odmawia
usuniecia (`provisioned dashboard cannot be deleted`), restart nie pomaga. Mozliwe
drogi: usuniecie wpisu z `grafana.db` przy zatrzymanej Grafanie albo nadanie
dashboardowi nowego `uid`. To cicha awaria aktualizacji — dokladnie klasa problemu,
ktora ten projekt zwalcza, wiec nie zostawiac tego na zawsze.

- [ ] **2.4 Obejrzyj dashboard pod `100.71.197.18:3000`.**
  *Weryfikacja:* wszystkie 10 paneli renderuje się bez „No data" — poza sytuacją,
  gdy żaden producent jeszcze nic nie wysłał, co jest wtedy poprawnym stanem.

---

## Faza 3 — ODLOZONA decyzja uzytkownika 2026-09-09

**BLOKADA (obalone zalozenie planu):** plan zakladal, ze na VPS stoi aktualny kod i
wystarczy dodac zmienne srodowiskowe. NIEPRAWDA. Kod aplikacji na VPS jest sprzed
telemetrii:

| Dowod | Stan |
|---|---|
| `argus/argus/llmops_client.py` na VPS | NIE ISTNIEJE |
| `argus/argus/llm/router.py` | brak hooka (grep llmops = 0), plik z 8 lipca |
| `rag/backend/core/llmops_emit.py` | NIE ISTNIEJE |
| `rag/backend/services/chat_service.py` | z 18 sierpnia, bez `call_records` |
| import klienta w kontenerach | `ImportError` w argus-app i rag-api |

Zeby telemetria ruszyla, trzeba wgrac kod aplikacji i PRZEBUDOWAC obrazy — co
wciagneloby dwa miesiace niezwiazanych zmian na systemy dzialajace nieprzerwanie
od 2-3 tygodni. Uzytkownik wybral: **nie ruszac produkcji dla telemetrii**.

**CO ZOSTALO PRZYGOTOWANE (dziala, czeka na kod):**
- `~/argus/.env` i `~/rag/.env` maja juz `LLMOPS_URL=http://100.71.197.18:9091`
  i `LLMOPS_TOKEN` (zgodnosc z kolektorem potwierdzona hashem).
- Compose obu projektow na VPS ma komplet `LLMOPS_*` per usluga (backupy:
  `docker-compose.yml.bak-2026-09-09`, `docker-compose.vps.yml.bak-2026-09-09`,
  `.env.bak-llmops-2026-09-09`).
- Zweryfikowano, ze kontenery producentow DOSIEGAJA kolektora po tailnecie
  (`rag-api` i `argus-app` dostaja `{"status":"ok"}` z `:9091`) — sciezka sieciowa
  jest sprawna, brakuje wylacznie kodu.

**KIEDY WROCIC:** przy najblizszym planowym deployu Argusa/RAG-a. Telemetria wlaczy
sie wtedy sama — zmienne juz sa, kod przyniesie hooki. Weryfikacja: wiersze
`project='argus'` / `'rag'` w `llm_calls` (patrz krok 3.3 ponizej).

**UWAGA przy tym deployu:** obrazy trzeba PRZEBUDOWAC (`docker compose build`),
nie tylko zrestartowac — hooki i `llmops_client.py` musza trafic do obrazu.

---

### Oryginalne kroki Fazy 3 (do wykonania pozniej)

## Faza 3 — producenci na VPS (Argus, RAG)

Oba mają własny compose i już stoją na tym hoście, więc to najtańsze wpięcia.

- [ ] **3.1 Argus** — dopisz do `~/argus/.env`: `LLMOPS_URL`, `LLMOPS_TOKEN`,
  `LLMOPS_PROJECT=argus`, `LLMOPS_ENV=production`, `LLMOPS_HOST=contabo-vps`.
  `LLMOPS_SERVICE` jest już ustawiane per-usługa w compose. Restart usług Argusa.
- [ ] **3.2 RAG** — to samo w `~/rag/.env` (`LLMOPS_PROJECT=rag`,
  `LLMOPS_SERVICE` per usługa: API i workery ingestu). Restart.
- [ ] **3.3 Weryfikacja obu naraz:** wywołaj coś, co realnie idzie do LLM (zapytanie
  w RAG, cykl Argusa), potem
  `SELECT project, service, count(*) FROM llm_calls GROUP BY 1,2`.
  *Weryfikacja:* wiersze dla `argus` i `rag`. Brak wierszy = klient jest no-opem,
  najpewniej literówka w `LLMOPS_URL` — to cicha awaria z założenia, więc nie
  licz na błąd w logach.

**Pamiętaj przy interpretacji:** RAG **nigdy** nie zaraportuje `ok=false` —
emituje rekordy dopiero po udanym wywołaniu. 0% error rate dla RAG to nie dowód
zdrowia, tylko znany ślepy punkt (opisany w README).

---

## Faza 4 — producenci bez własnego (uruchamianego) compose

Cztery projekty, każdy niezależny. **Tu wraca otwarte pytanie 1** — dla każdego
trzeba wiedzieć, gdzie proces faktycznie czyta środowisko. README ma dla nich
gotową sekcję („Aktywacja telemetrii tam, gdzie nie ma własnego docker-compose").

- [ ] **4.1 llm-proxy** — zmienne do bloku `environment:` serwisu
  `hermes-llm-proxy` w `hermes/docker-compose.yml`, wartości z `hermes/.env`.
  `LLMOPS_PROJECT=llm-proxy`, `LLMOPS_SERVICE=hermes-llm-proxy`.
  Najważniejszy producent — Hermes chodzi przez niego, więc pokrywa się pośrednio.
- [ ] **4.2 kontekst ai** — `kontekst ai/.env`, `LLMOPS_PROJECT=kontekst-ai`,
  `LLMOPS_SERVICE=ai-repo`.
- [ ] **4.3 trading-app** — `trading-app/.env`, `LLMOPS_PROJECT=trading-app`,
  `LLMOPS_SERVICE=streamlit`.
- [ ] **4.4 Selfmadeagent** — zmienne w `Selfmadeagent/docker-compose.yml`
  (orchestrator). Patrz otwarte pytanie 2 co do `LLMOPS_HOST`.
- [ ] **4.5 Weryfikacja per projekt:** wywołanie LLM → wiersz w `llm_calls`.
  Rób to **projekt po projekcie**, nie hurtem — przy czterech naraz nie odróżnisz,
  który nie działa.

---

## Faza 5 — retencja

- [ ] **5.1 `chmod +x ~/llmops/scripts/retention.sh`**, cron na 4:00:
  `0 4 * * * /root/llmops/scripts/retention.sh >> /var/log/llmops-retention.log 2>&1`
- [ ] **5.2 Uruchom raz ręcznie** — przy pustej/świeżej bazie ma przejść bez błędu
  i nic nie skasować.
  *Weryfikacja:* skrypt kończy się kodem 0, `llm_calls` bez zmian, log zapisany.
  Skrypt czyta `LLMOPS_DB_NAME` — czyli produkcyjną bazę. To poprawne, ale znaczy,
  że **literówka w tej zmiennej kasuje nie to, co trzeba**.

---

## Faza 6 — domknięcie po dobie

- [ ] **6.1** Zapytanie z kryterium sukcesu (góra dokumentu).
- [ ] **6.2** Panel „wywołania bez cennika" — każdy model, który tam wypłynął,
  dopisz do `model_pricing` **nowym wierszem z `valid_from`**, nigdy edycją
  istniejącego (edycja przeliczyłaby wstecz historyczne koszty).
- [ ] **6.3** Zaktualizuj pamięć projektu (`project_llmops`): z „NIE wdrożony"
  na stan faktyczny.

---

## Wycofanie

Telemetria jest z założenia opcjonalna, więc rollback jest tani i nie wymaga
odwracania migracji:

1. **Jeden producent zachowuje się dziwnie** → usuń `LLMOPS_URL` z jego env i
   zrestartuj. Klient bez URL-a jest cichym no-opem; kod zostaje wpięty.
2. **Kolektor przeszkadza** → `docker compose stop llmops-collector`. Producenci
   gubią metryki (kolejka w pamięci, `try/except`), ale **żadne wywołanie LLM nie
   pada** — to gwarancja projektu, przetestowana (`test_collector_down_does_not_raise`).
3. **Pełne wycofanie** → `docker compose down` w `~/llmops` + usunięcie zmiennych
   `LLMOPS_*`. Wolumen z danymi zostaje; `down -v` skasowałby historię telemetrii
   **i cennik**.

---

## Ryzyka

| Ryzyko | Dlaczego realne | Ograniczenie |
|---|---|---|
| Port 8090 publicznie | Docker omija ufw na tym hoście — to nie teoria, tylko udokumentowana właściwość tej maszyny | Krok 1.5 sprawdza publiczny IP wprost |
| Telemetria cicho nie działa | Klient jest no-opem bez `LLMOPS_URL` **z założenia** — nie będzie błędu w logach | Weryfikacja per projekt (3.3, 4.5), nie „wszystko naraz" |
| Rozjazd hasła bazy | Hasło ustawiane tylko przy initdb; `.env` zmieniony później nie działa | Ustalić hasło w 1.2, przed pierwszym startem |
| Fałszywe koszty | Ceny płatnych modeli nieweryfikowane u dostawców | Faza 0.1 + panel „bez cennika" ujawnia luki zamiast je zerować |
| Skasowanie cennika przez testy | Zdarzyło się **dwa razy** (2026-09-08 i 09) | Nie uruchamiać `--profile test` na VPS; guard `_test` w conftest |
| `0% error rate` dla RAG | Znane ograniczenie, wygląda jak dobra wiadomość | Udokumentowane w README; nie traktować jako sygnału zdrowia |

---

## Czego ten plan świadomie nie robi

- **Backfillu historii** (Task 9 z planu Etapu 1) — osobne zadanie, sensowne
  dopiero gdy baza stoi.
- **Naprawy ścieżek błędów w RAG** — wymaga przebudowy, jawnie poza zakresem Etapu 1.
- **Przeniesienia Langfuse** — `llm_calls` celowo nie trzyma treści; to inna warstwa.
- **Pushowania gałęzi** — `feat/argus-phase1` jest 41 commitów przed `origin`;
  decyzja użytkownika, nie krok wdrożeniowy.
