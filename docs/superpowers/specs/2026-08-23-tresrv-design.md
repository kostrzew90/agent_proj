# tresrv — agent żywieniowo-treningowy z botem Telegram (Increment 1: Core)

**Data:** 2026-08-23
**Status:** Design (po 2 rundach review Opus + poprawkach usera, gotowy do writing-plans)
**Autor:** brainstorming Sonnet + user, review środowiska/jakości/implementacji przez Opus (subagent, 2x)

---

## 1. Problem / cel

User chce osobistego "trenera" żywieniowo-sportowego dostępnego przez Telegram: loguje co zjadł (tekst lub zdjęcie) i swoją wagę, bot liczy kalorie/makra względem ustalonego celu (redukcja/masa/utrzymanie) i codziennie wieczorem podsumowuje dzień. To pierwszy z trzech zaplanowanych przyrostów — pełny projekt docelowo doda integrację z treningowym trackerem opengym (Increment 2) i pętlę samouczącą korygującą cele na podstawie trendu wagi (Increment 3), ale **ten dokument opisuje wyłącznie Increment 1**.

**tresrv to osobny agent, nie rozszerzenie Argusa** — inna domena (zdrowie vs trading), inny bot Telegram (własny token), własna baza Postgres, **osobny klucz Gemini** (limit API jest per-klucz — współdzielenie z Argusem zjadałoby wspólną pulę). Jedyne co jest świadomie *kopiowane* (nie współdzielone) z Argusa to wzorzec scheduler/worker i styl deployu (docker-compose na tym samym Contabo VPS) — **jako plain Python process, nie FastAPI** (patrz sekcja 3, uzasadnienie). Grafana jest współdzielona z Argusem (nowy datasource), żeby nie stawiać drugiej instancji.

## 2. Cele i nie-cele

### Cele (Increment 1)
- Bot Telegram (własny token) przyjmujący: log posiłku (tekst lub zdjęcie), log wagi, komendy profilu i celu.
- Onboarding zbierający dane potrzebne do policzenia celu kalorycznego: waga, wzrost, wiek, płeć, poziom aktywności.
- Cel: redukcja / masa / utrzymanie+wydolność — wybierany i przełączalny w dowolnym momencie.
- Parsowanie posiłku (tekst/zdjęcie) przez Gemini na szacowane kalorie + makra (białko/tłuszcz/węglowodany).
- Odporność na limity/awarie Gemini: log usera nigdy nie ginie (kolejka retry).
- Możliwość poprawienia błędnie sparsowanego wpisu.
- Codzienne wieczorne podsumowanie: kalorie/makra dnia vs cel, krótki komentarz.
- Ustalona strefa czasowa i granica "dnia" (żeby agregaty były spójne).

### Nie-cele (Increment 1, explicite poza zakresem)
- ❌ Integracja z opengym / jakiekolwiek dane treningowe (Increment 2).
- ❌ Przypomnienia przed treningiem / w porze posiłków (Increment 2).
- ❌ Samouczenie / automatyczna korekta celu kalorycznego (Increment 3).
- ❌ Multi-provider LLM router z fallbackiem jak w Argusie (świadomie uproszczone — patrz sekcja 6).
- ❌ Multi-user — jeden user, jeden `chat_id`, brak systemu kont.
- ❌ Rozpoznawanie dokładnej wagi porcji ze zdjęcia (LLM szacuje w dobrej wierze, user może skorygować).

## 3. Architektura

Niezależny stack docker-compose na Contabo VPS (`100.71.197.18`), obok Argusa i RAG.

**Plain Python process, NIE FastAPI** (decyzja po review — zmiana względem pierwszej wersji speca):
- Increment 1 nie ma webhooka, nie ma dashboardu (Grafana już to pokrywa — sekcja 9), Telegram działa przez polling. Nic tu nie potrzebuje HTTP servera.
- Sprawdzony wzorzec z Argusa to **nie tylko** FastAPI — `liq-listener` i `guardian` w tym samym stacku już działają jako plain-process kontenery (`command: python -m ...`, zero HTTP) i są równie "sprawdzonym deploymentem" (Dockerfile, compose, `restart: unless-stopped`, `${TAILSCALE_IP}` binding — nic z tego nie zależy od FastAPI).
- Heartbeat żywotności idzie do Postgresa (`heartbeat_job` co 5 min, tabela), nie przez HTTP `/health` — to lepszy sygnał dla bota pollingowego niż "uvicorn odpowiada 200".
- **Odwracalność:** struktura modułów ma czynić dodanie FastAPI później nowym entrypointem, nie refaktorem — `tresrv/domain/` (czysta logika, zero I/O) woła się identycznie z przyszłego endpointu jak z joba schedulera.

```
Telegram (polling)
        │
        ▼
   Python process ──► APScheduler (evening summary, pending_parse drain, heartbeat)
        │
        ├─► Gemini API (text + vision) — parsing posiłków
        │
        ▼
   Postgres (własna baza tresrv)
```

Struktura modułów: `tresrv/db.py`, `tresrv/llm.py`, `tresrv/domain/` (BMR/TDEE, granica dnia, `needs_confirmation`, agregacje dzienne — czysta logika, najgęstsze testy), `tresrv/bot/` (handlery, konwersacje), `tresrv/scheduler/`, entry `python -m tresrv.main`.

Komponenty:
- **Telegram bot** — python-telegram-bot (polling). Komendy: `/start` (onboarding), `/profil` (edycja), `/cel` (redukcja|masa|utrzymanie), `/waga <kg>`, `/popraw` (korekta ostatniego wpisu — makra LUB `consumed_at`), zwykła wiadomość tekstowa lub zdjęcie = log posiłku. `/start` i `/popraw` dzielą tę samą maszynerię `ConversationHandler` (wielokrokowa konwersacja) — stan konwersacji trzymany w pamięci procesu, świadomie bez persistence (restart gubi rozgrzebaną korektę, user klika `/popraw` ponownie).
- **Meal parser** — wywołuje Gemini (`gemini-2.5-flash`, tekst i zdjęcie ten sam model, wspiera vision) z wąskim promptem: zwróć JSON `{kcal, protein_g, fat_g, carbs_g, opis, confidence, when_hint}`. Odpowiedź walidowana (pydantic) — brakujące pola / śmieciowy JSON / `confidence` poza 0..1 traktowane jak błąd parsowania, nie jak sukces z pustymi polami.
- **Retry queue** — gdy Gemini zwróci błąd/429/503 lub nieparsowalny JSON: surowy wpis trafia do `pending_parse` (z czasem przechwyconym **przy odbiorze**, nie przy udanym retry — inaczej wpis z 23:58 sparsowany po północy wyląduje w złym dniu). Bot odpowiada "zapisane, policzę za chwilę". Job w schedulerze (co 2 min, `max_instances=1, coalesce=True` żeby wolne wywołanie Gemini nie nałożyło się na kolejny tick) próbuje ponownie z backoffem (60s→120s→300s→cap). Błąd sieciowy/5xx → retry ma sens; śmieciowy JSON dwa razy z rzędu → od razu `failed_permanently` (ten sam input da prawdopodobnie ten sam wynik).
- **Scheduler** — APScheduler w procesie: `evening_summary_job`, `pending_parse_drain_job` (co 2 min), `heartbeat_job` (co 5 min).
- **Profile & goals** — `user_profile` (jeden wiersz na start, kolumna `chat_id` pod przyszły multi-user, bez logiki multi-user), formuła Mifflin-St Jeor do BMR→TDEE→target kaloryczny wg wybranego celu.
- **Storage zdjęć** — download z Telegram File API **natychmiast przy odbiorze** (przed wywołaniem Gemini) do `/data/meals/<uuid>.jpg` (named volume `tresrv-meals`), `storage_path` w DB + `telegram_file_id` jako fallback gdy download zawiódł (wtedy retry queue próbuje pobrać ponownie). Retencja: trzymamy wszystko, przegląd co tydzień (świadoma decyzja, nie pominięcie — wolumen jest znikomy, rząd MB/tydzień).

## 4. Model danych (Postgres)

- **`user_profile`** — `chat_id` (PK), `plec`, `wiek`, `wzrost_cm`, `waga_kg` (aktualna, aktualizowana z `weight_logs`), `poziom_aktywnosci` (sedentary|light|moderate|active|very_active), `cel` (reduction|mass|maintenance), `updated_at`.

- **`weight_logs`** — `id`, `chat_id`, `waga_kg`, `logged_at` (`timestamptz`), `local_date` (`date`, wyliczane przez aplikację z `logged_at` w Europe/Warsaw — klucz upsertu, `UNIQUE (chat_id, local_date)`). Jeden wpis dziennie, startuje od dnia 1.

- **`meals`** — pełna definicja (rozstrzyga uwagi usera o `storage_path`/`confidence`/`consumed_at`):
  - `id`, `chat_id`
  - `logged_at` (`timestamptz`, kiedy user napisał do bota) i `consumed_at` (`timestamptz`, kiedy faktycznie jadł — domyślnie `= logged_at`, nadpisywalne przez `when_hint` z LLM lub `/popraw`)
  - `consumed_date` (`date`, `consumed_at` w Europe/Warsaw — ustawiane przez aplikację, **nie generated column**: konwersja strefy jest `STABLE` nie `IMMUTABLE`, Postgres by to odrzucił)
  - `raw_input_type` (text|photo), `raw_text` (nullable), `storage_path` (nullable, `/data/meals/<uuid>.jpg`), `telegram_file_id` (nullable, fallback)
  - `opis`, `kcal`, `protein_g`, `fat_g`, `carbs_g` (wynik parsowania)
  - `confidence` (0..1, z LLM — surowy sygnał) i `needs_confirmation` (bool, **wyliczane regułą aplikacji**, nie przez LLM: `confidence < 0.7 OR kcal > 1200 OR (photo AND brak gramatury w opisie)` — LLM-owa samoocena "czy się upewnić" byłaby drugą, niekalibrowaną opinią tego samego modelu)
  - `value_source` (`llm`|`user` — steruje komunikatem "Szacunek: X kcal" vs "Twoja korekta: X kcal"), `llm_model` (np. `gemini-2.5-flash`, pod przyszły re-parsing w Increment 3)
  - `status` (`parsed`|`corrected`|`superseded`) i `corrected_from_id` (self-FK) — `/popraw` wstawia nowy wiersz (`corrected`, `value_source=user`) i **w tej samej transakcji** ustawia staremu `status=superseded`. Wszystkie zapytania agregujące filtrują `status <> 'superseded'` — bez tego wieczorne podsumowanie policzyłoby poprawiony posiłek dwa razy.

- **`pending_parse`** — `id`, `chat_id`, `raw_input_type`, `raw_text`, `storage_path`, `telegram_file_id`, `logged_at`/`consumed_at` (przechwycone **przy odbiorze**, nie przy udanym retry), `attempts`, `last_attempt_at`, `next_attempt_at`, `last_error` (rozróżnia 429/503 od śmieciowego JSON — steruje czy retry ma sens), `status` (pending|failed_permanently|resolved), `meal_id` (FK, wypełniane po sukcesie).

- **`daily_targets`** (widok/funkcja, nie tabela) — liczony on-the-fly z `user_profile` (BMR Mifflin-St Jeor × mnożnik aktywności × modyfikator celu: redukcja -20%, masa +15%, utrzymanie 0%; białko z `waga_kg × 1.8g` niezależnie od celu).

- **Wszystkie agregacje dzienne liczą po `consumed_date`, nigdy po `logged_at`.**

## 5. Przepływ — kluczowe scenariusze

**Onboarding (`/start`):** bot pyta sekwencyjnie płeć → wiek → wzrost → waga → poziom aktywności → cel. Zapisuje `user_profile` + pierwszy wpis w `weight_logs`. Bez onboardingu bot odrzuca logowanie posiłków komunikatem "najpierw `/start`".

**Log posiłku (tekst):** user pisze wolny tekst → Gemini parsuje (w tym opcjonalny `when_hint`, np. "wczoraj wieczorem") → zapis do `meals` (status `parsed`) → bot odpowiada w formacie **"Szacunek: 740 kcal, B 48g/T 22g/W 73g"** (nigdy jak zmierzona wartość) + jeśli `needs_confirmation` — prośba o potwierdzenie gramatury; jeśli `when_hint` przesunął `consumed_at` — echo daty ("zapisane na: wczoraj ~20:00"), a przesunięcie >48h wymaga jawnego potwierdzenia usera zamiast cichej akceptacji.

**Log posiłku (zdjęcie):** download natychmiast do `storage_path`, potem Gemini z vision, dalej jak wyżej. Jeśli LLM zwróci `{"error": "not_food"}` — bot prosi o inny input, nic nie zapisuje do `meals`.

**Awaria Gemini:** wpis trafia do `pending_parse` (z `consumed_at` przechwyconym od razu), user dostaje natychmiastowe potwierdzenie zapisania (nie utraty danych), drain job dobija w tle.

**`/popraw`:** interaktywnie przez inline keyboard — pokazuje ostatni posiłek z rozbiciem, przyciski `[Kalorie] [Białko] [Tłuszcz] [Węgle] [Kiedy jadłem] [Cały posiłek]`. Wybór pola → bot prosi o nową wartość → nowy wiersz w `meals` (`status=corrected`, `value_source=user`), stary → `status=superseded` (jedna transakcja). Edycja **"Kiedy jadłem"** zmienia `consumed_at`/`consumed_date` tego wpisu. Tekstowy fallback (`/popraw kcal 740`) zostaje jako deterministyczna, testowalna ścieżka — keyboard może wypaść z pierwszego cięcia pod presją czasu bez utraty funkcji.

**`/waga <kg>`:** upsert do `weight_logs` na `local_date` dzisiaj. Wielokrotne logowanie w ciągu dnia nadpisuje, nie duplikuje.

**Wieczorne podsumowanie (godzina konfigurowalna, domyślnie 21:00 Europe/Warsaw):** suma `meals` (`status <> 'superseded'`, po `consumed_date` = dzisiaj) vs `daily_targets`, krótki tekst z tym samym rozróżnieniem szacunek/korekta (np. "Szacunkowo 1850/2100 kcal, białko 140/160g — blisko celu"). Podsumowanie jest **snapshotem, nie wysyłane ponownie** — jeśli user późnym rankiem dopisze wczorajszy posiłek, wczorajsze podsumowanie zostaje błędne w Telegramie, ale dane w DB (które karmią Increment 3) są poprawne. Bez rekomendacji korygującej cel — to Increment 3.

## 6. LLM — Gemini bez fallback routera (świadoma decyzja + zabezpieczenie)

W przeciwieństwie do Argusa (Gemini → OpenRouter → Groq → paid) tresrv używa **wyłącznie Gemini** — mniej kodu na start, akceptowalne bo:
- Konsekwencja limitu/awarii jest zaabsorbowana przez **kolejkę retry** (sekcja 3), nie przez odrzucenie wpisu usera. To adresuje realne ryzyko (Argus ma udokumentowaną historię wyczerpywania darmowych limitów) bez budowania całego mechanizmu multi-provider.
- Jeśli w praktyce kolejka retry okaże się niewystarczająca (Gemini martwy godzinami), dodanie drugiego providera do routera jest izolowaną zmianą w jednym module (`llm_client.py`) — nie wymaga przeprojektowania.

## 7. Error handling

- Gemini zwraca nieparsowalny JSON → traktowane jak błąd (trafia do `pending_parse`), nie jak sukces z pustymi polami.
- Zdjęcie nieczytelne/nie-jedzenie → Gemini instruowany (prompt) zwrócić `{"error": "not_food"}` → bot prosi o inny input, nie zapisuje do `meals`.
- Brak profilu przy próbie logowania posiłku → komunikat + link do `/start`, żaden wpis nie ginie w międzyczasie (loguje się do `meals` bez targetu, podsumowanie doliczy target retroaktywnie po onboardingu).
- `pending_parse` po wyczerpaniu prób (np. 5) → status `failed_permanently`, alert do usera z sugestią `/popraw`.
- Download zdjęcia z Telegrama zawiedzie → zapis do `pending_parse` z samym `telegram_file_id` (bez `storage_path`), drain job próbuje pobrania ponownie.
- Śmieciowy JSON od Gemini dwa razy z rzędu na tym samym wpisie → od razu `failed_permanently` (retry z tym samym inputem prawdopodobnie da ten sam wynik) zamiast wyczerpywać wszystkie próby.

## 8. Testing

- Unit (`domain/`, zero I/O — największa gęstość testów w projekcie): formuła BMR/TDEE/target (tabela przypadków płeć/wiek/aktywność/cel), resolver granicy dnia (`timestamptz`→`consumed_date`), resolver `when_hint`→`consumed_at`, reguła `needs_confirmation`, agregacja dzienna na wierszach in-memory (w tym: wiersz `superseded` NIE wchodzi do sumy).
- Unit (`llm.py`): walidacja odpowiedzi Gemini (pydantic) — pełny JSON, brakujące pola, śmieciowy JSON, `confidence` poza 0..1, `{"error":"not_food"}`.
- `/popraw` tekstowy fallback: tworzy nowy wiersz z poprawnym `corrected_from_id`, stary faktycznie zmienia status na `superseded`, regresja — suma dnia po korekcie liczy się raz, nie dwa razy.
- Integracyjne: retry queue — symulacja 429/503/śmieciowego JSON (wstrzyknięty klient LLM, bez Telegrama) → wpis w `pending_parse` → drain job → sukces po N próbach lub `failed_permanently`; upsert `weight_logs` (idempotencja per `local_date`).
- Manualne (przed deployem): pełny onboarding przez realnego bota testowego, log tekstowy, log zdjęciowy (w tym download-fail ścieżka), `/popraw` przez inline keyboard, wieczorne podsumowanie o wymuszonej godzinie testowej.

## 9. Infrastruktura / deploy

- Nowy katalog `tresrv/` w repo, docker-compose z 2 serwisami: `app` (plain Python process — bot+scheduler+llm client) i `db` (Postgres, osobna od Argusa), plus named volume `tresrv-meals:/data/meals`.
- Deploy na Contabo VPS obok Argusa — bez wystawionego portu (bot działa przez polling, brak HTTP servera; jeśli kiedyś dojdzie dashboard/API, dopiero wtedy port na `${TAILSCALE_IP}` jak reszta usług, patrz `reference_contabo_vps`).
- Przed deployem: dodać 2GB swapfile na VPS (obecnie 0B swap) jako bufor przy kolejnym stacku.
- `.env`: `TELEGRAM_BOT_TOKEN` (nowy, osobny bot — założony przez BotFather), `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY` — **nowy, osobny klucz** (nie współdzielony z Argusem — limit jest per-klucz).
- Grafana: nowy datasource wskazujący na bazę tresrv, dodany do istniejącej instancji Argusa — bez nowego kontenera.

## 10. Roadmapa (poza zakresem tego dokumentu, do przyszłych spec)

- **Increment 2** — przypomnienia treningowe na własnym harmonogramie wpisywanym ręcznie przez usera NAJPIERW; opengym jako źródło planu treningowego DOPIERO POTEM (deploy na VPS, odczyt `state-<user>.json` read-only + retry na częściowy zapis — do zweryfikowania czy zapis w opengym jest atomowy).
- **Increment 3** — samouczenie: 7-dniowa średnia krocząca wagi, korekta targetu kalorycznego ±100-150 kcal nie częściej niż raz na 14 dni, floor/ceiling na target. **Korekta wyłącznie na podstawie trendu wagi, nigdy na różnicy target-vs-zalogowane kalorie** (bo błąd estymacji LLM ~20-30% zniekształciłby sygnał).
