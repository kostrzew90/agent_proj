# tresrv — agent żywieniowo-treningowy z botem Telegram (Increment 1: Core)

**Data:** 2026-08-23
**Status:** Design (zaakceptowany do zapisu, oczekuje review spec)
**Autor:** brainstorming Sonnet + user, review środowiska/jakości przez Opus (subagent)

---

## 1. Problem / cel

User chce osobistego "trenera" żywieniowo-sportowego dostępnego przez Telegram: loguje co zjadł (tekst lub zdjęcie) i swoją wagę, bot liczy kalorie/makra względem ustalonego celu (redukcja/masa/utrzymanie) i codziennie wieczorem podsumowuje dzień. To pierwszy z trzech zaplanowanych przyrostów — pełny projekt docelowo doda integrację z treningowym trackerem opengym (Increment 2) i pętlę samouczącą korygującą cele na podstawie trendu wagi (Increment 3), ale **ten dokument opisuje wyłącznie Increment 1**.

**tresrv to osobny agent, nie rozszerzenie Argusa** — inna domena (zdrowie vs trading), inny bot Telegram (własny token), własna baza Postgres. Jedyne co jest świadomie *kopiowane* (nie współdzielone) z Argusa to wzorzec scheduler/worker (APScheduler w procesie FastAPI) i styl deployu (docker-compose na tym samym Contabo VPS). Grafana jest współdzielona z Argusem (nowy datasource), żeby nie stawiać drugiej instancji.

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

```
Telegram (webhook/polling)
        │
        ▼
   FastAPI app ──► APScheduler (evening summary job, retry-queue drain job)
        │
        ├─► Gemini API (text + vision) — parsing posiłków
        │
        ▼
   Postgres (własna baza tresrv)
```

Komponenty:
- **Telegram bot** — python-telegram-bot lub raw Bot API (polling, nie webhook — prostsze, brak potrzeby publicznego endpointu). Komendy: `/start` (onboarding), `/profil` (edycja), `/cel` (redukcja|masa|utrzymanie), `/waga <kg>`, `/popraw` (korekta ostatniego wpisu), zwykła wiadomość tekstowa lub zdjęcie = log posiłku.
- **Meal parser** — wywołuje Gemini (tekst → `gemini-2.5-flash`, zdjęcie → ten sam model, wspiera vision) z wąskim promptem: zwróć JSON `{kcal, protein_g, fat_g, carbs_g, opis}`. Wynik + surowy input zapisywany do `meals`.
- **Retry queue** — gdy Gemini zwróci błąd/429/503: surowy wpis (tekst lub image_id) trafia do `pending_parse`, bot odpowiada userowi "zapisane, policzę za chwilę". Job w schedulerze (co 2 min) próbuje ponownie z backoffem (60s→120s→300s→cap), do max N prób; po wyczerpaniu — alert do usera "nie mogę policzyć tego wpisu, spróbuj `/popraw`".
- **Scheduler** — APScheduler w procesie FastAPI (wzorzec z Argusa): `evening_summary_job` (codziennie o ustalonej godzinie), `pending_parse_drain_job` (co 2 min).
- **Profile & goals** — `user_profile` (jeden wiersz na start, przygotowane pod multi-user w nazwie kolumny `chat_id`, ale bez logiki multi-user), formuła Mifflin-St Jeor do BMR→TDEE→target kaloryczny wg wybranego celu.

## 4. Model danych (Postgres)

- **`user_profile`** — `chat_id` (PK), `plec`, `wiek`, `wzrost_cm`, `waga_kg` (aktualna, aktualizowana z `weight_logs`), `poziom_aktywnosci` (sedentary|light|moderate|active|very_active), `cel` (reduction|mass|maintenance), `updated_at`.
- **`weight_logs`** — `id`, `chat_id`, `waga_kg`, `logged_at` (data lokalna, Europe/Warsaw). Jeden wpis dziennie (upsert po dacie) — startuje od dnia 1, niezależnie od tego że Increment 3 (samouczenie) przyjdzie później.
- **`meals`** — `id`, `chat_id`, `logged_at`, `raw_input_type` (text|photo), `raw_text` (nullable), `raw_image_ref` (nullable, ścieżka/file_id), `kcal`, `protein_g`, `fat_g`, `carbs_g`, `opis` (parsed), `status` (parsed|corrected), `corrected_from_id` (nullable, self-FK gdy `/popraw` tworzy nowy wpis zamiast nadpisywać).
- **`pending_parse`** — `id`, `chat_id`, `raw_input_type`, `raw_text`, `raw_image_ref`, `attempts`, `last_attempt_at`, `next_attempt_at`, `status` (pending|failed_permanently|resolved`), `created_at`.
- **`daily_targets`** (widok/funkcja, nie tabela) — liczony on-the-fly z `user_profile` (BMR Mifflin-St Jeor × mnożnik aktywności × modyfikator celu: redukcja -20%, masa +15%, utrzymanie 0%; białko z `waga_kg × 1.8g` niezależnie od celu).

## 5. Przepływ — kluczowe scenariusze

**Onboarding (`/start`):** bot pyta sekwencyjnie płeć → wiek → wzrost → waga → poziom aktywności → cel. Zapisuje `user_profile` + pierwszy wpis w `weight_logs`. Bez onboardingu bot odrzuca logowanie posiłków komunikatem "najpierw `/start`".

**Log posiłku (tekst):** user pisze wolny tekst → Gemini parsuje → zapis do `meals` (status `parsed`) → bot odpowiada z rozbiciem kcal/makr + pytaniem czy się zgadza (nie blokujące — user może zignorować albo użyć `/popraw`).

**Log posiłku (zdjęcie):** analogicznie, Gemini z vision. Jeśli zdjęcie nieczytelne — Gemini zwraca low-confidence flag w JSON, bot prosi o tekst zamiast zdjęcia.

**Awaria Gemini:** wpis trafia do `pending_parse`, user dostaje natychmiastowe potwierdzenie zapisania (nie utraty danych), drain job dobija w tle.

**`/popraw`:** user podaje nowe wartości (albo nowy opis do re-parsowania) dla ostatniego wpisu z `meals` — tworzy nowy wiersz z `corrected_from_id` wskazującym na poprzedni (audit trail, nie nadpisywanie).

**`/waga <kg>`:** upsert do `weight_logs` na dzisiejszą datę (Europe/Warsaw). Wielokrotne logowanie w ciągu dnia nadpisuje, nie duplikuje.

**Wieczorne podsumowanie (godzina konfigurowalna, domyślnie 21:00 Europe/Warsaw):** suma `meals` z dzisiejszego dnia lokalnego vs `daily_targets`, krótki tekst (np. "1850/2100 kcal, białko 140/160g — blisko celu"). Bez rekomendacji korygującej cel — to Increment 3.

## 6. LLM — Gemini bez fallback routera (świadoma decyzja + zabezpieczenie)

W przeciwieństwie do Argusa (Gemini → OpenRouter → Groq → paid) tresrv używa **wyłącznie Gemini** — mniej kodu na start, akceptowalne bo:
- Konsekwencja limitu/awarii jest zaabsorbowana przez **kolejkę retry** (sekcja 3), nie przez odrzucenie wpisu usera. To adresuje realne ryzyko (Argus ma udokumentowaną historię wyczerpywania darmowych limitów) bez budowania całego mechanizmu multi-provider.
- Jeśli w praktyce kolejka retry okaże się niewystarczająca (Gemini martwy godzinami), dodanie drugiego providera do routera jest izolowaną zmianą w jednym module (`llm_client.py`) — nie wymaga przeprojektowania.

## 7. Error handling

- Gemini zwraca nieparsowalny JSON → traktowane jak błąd (trafia do `pending_parse`), nie jak sukces z pustymi polami.
- Zdjęcie nieczytelne/nie-jedzenie → Gemini instruowany (prompt) zwrócić `{"error": "not_food"}` → bot prosi o inny input, nie zapisuje do `meals`.
- Brak profilu przy próbie logowania posiłku → komunikat + link do `/start`, żaden wpis nie ginie w międzyczasie (loguje się do `meals` bez targetu, podsumowanie doliczy target retroaktywnie po onboardingu).
- `pending_parse` po wyczerpaniu prób (np. 5) → status `failed_permanently`, alert do usera z sugestią `/popraw`.

## 8. Testing

- Unit: formuła BMR/TDEE/target (tabela przypadków płeć/wiek/aktywność/cel), parser JSON z Gemini (mockowany response, w tym błędne/częściowe JSON), upsert `weight_logs` (idempotencja per dzień), `/popraw` tworzy nowy wiersz z poprawnym `corrected_from_id`.
- Integracyjne: retry queue — symulacja 429/503 → wpis w `pending_parse` → drain job → sukces po N próbach lub `failed_permanently`.
- Manualne (przed deployem): pełny onboarding przez realnego bota testowego, log tekstowy, log zdjęciowy, wieczorne podsumowanie o wymuszonej godzinie testowej.

## 9. Infrastruktura / deploy

- Nowy katalog `tresrv/` w repo, docker-compose z 2 serwisami: `app` (FastAPI+scheduler+bot) i `db` (Postgres, osobna od Argusa).
- Deploy na Contabo VPS obok Argusa — porty bindowane na `${TAILSCALE_IP}` jak reszta usług (patrz `reference_contabo_vps`), jeśli w ogóle potrzebny publikowany port (bot działa przez polling, nie musi mieć wystawionego portu — ewentualny port tylko pod przyszły dashboard/debug).
- Przed deployem: dodać 2GB swapfile na VPS (obecnie 0B swap) jako bufor przy kolejnym stacku.
- `.env`: `TELEGRAM_BOT_TOKEN` (nowy, osobny bot — założony przez BotFather), `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY` (może być ten sam klucz co Argus, osobne API quoty per-key nie per-projekt więc **do sprawdzenia czy dzielenie klucza z Argusem nie zje wspólnego limitu** — jeśli tak, założyć drugi klucz Gemini).
- Grafana: nowy datasource wskazujący na bazę tresrv, dodany do istniejącej instancji Argusa — bez nowego kontenera.

## 10. Roadmapa (poza zakresem tego dokumentu, do przyszłych spec)

- **Increment 2** — przypomnienia treningowe na własnym harmonogramie wpisywanym ręcznie przez usera NAJPIERW; opengym jako źródło planu treningowego DOPIERO POTEM (deploy na VPS, odczyt `state-<user>.json` read-only + retry na częściowy zapis — do zweryfikowania czy zapis w opengym jest atomowy).
- **Increment 3** — samouczenie: 7-dniowa średnia krocząca wagi, korekta targetu kalorycznego ±100-150 kcal nie częściej niż raz na 14 dni, floor/ceiling na target. **Korekta wyłącznie na podstawie trendu wagi, nigdy na różnicy target-vs-zalogowane kalorie** (bo błąd estymacji LLM ~20-30% zniekształciłby sygnał).
