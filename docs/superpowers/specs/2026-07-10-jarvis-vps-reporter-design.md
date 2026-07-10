# Jarvis: autonomiczny obserwator/reporter na VPS

**Data:** 2026-07-10
**Status:** Zaakceptowany
**Projekt:** `jarvis/` (nowy, VPS obok Argusa)

## Cel

Jarvis = autonomiczny obserwator/reporter na Oracle VPS (niezależny od laptopa usera), który zbiera stan systemów i strategii walidacji, wysyła digesty na Telegram i przypomina o bramkach. Zasada nadrzędna: **read-only** — raportuje i przypomina, NIGDY nie wykonuje akcji samodzielnie. Autonomia wykonawcza rozważana dopiero, gdy raporty okażą się trafne (wzorzec z Argusa: najpierw zmierz wiarygodność, potem ufaj).

## Kontekst decyzji

- User chciał "autonomicznego Jarvisa"; zakres zawężony do obserwatora-reportera w służbie strategii walidacji dwutorowej (patrz `docs/superpowers/specs/2026-07-10-walidacja-dwutorowa-design.md` — Jarvis służy tej strategii).
- Hermes (laptop, 9 kontenerów) ODRZUCONY jako platforma — Jarvis musi działać 24/7 niezależnie od laptopa. Zamiast tego: lekki osobny serwis na VPS obok Argusa, sklejony ze sprawdzonych klocków Argusa.
- Baza wektorowa / PDF-y w v0 ODRZUCONE: kontekst usera to kilka plików markdown ładowanych do prompta w całości; "nauka" = pętla feedbacku (wzorzec samonauki Argusa), nie dokumenty; pytania o PDF-y = projekt RAG, osobna decyzja, nie mieszać do reportera. Gdy pojawi się udowodniona potrzeba — pgvector stoi na tym samym VPS (migracja SQLite→Postgres to popołudnie).
- GUI przeglądarkowe ODRZUCONE w v0: Telegram = pełny interfejs (telefon, desktop, web.telegram.org, dwukierunkowy, push). Read-only strona statusowa możliwa w v1 (wzorzec dashboardu Argusa :8080). Pełne GUI chatowe — poza scope całkowicie.

## Architektura v0

- Nowy katalog `jarvis/` w repo, 1 kontener Python na VPS (docker compose, obok stacka Argusa).
- APScheduler (wzorzec z Argusa): job dzienny ~07:30 (digest operacyjny) + job tygodniowy (digest Argusa), job pollingu Telegram.
- `router.py` — KOPIA sprawdzonego modułu z Argusa (Gemini free → Groq free → OpenRouter free; sliding-window RPM, circuit breaker, backoff 429/503, log każdego calla). W v0 LLM praktycznie nieużywany — digesty są deterministyczne (szablony); router czeka na v0.5.
- Telegram: WŁASNY token bota (od BotFather) — NIE token Hermesa (konflikt getUpdates z telegram-watcherem na laptopie). Wysyłka digestów + polling getUpdates dla komend.
- Stan: SQLite (bramki walidacji, snapshoty rankingów Argusa tydzień-do-tygodnia, log uruchomień jobów, później: widziane pomysły i feedback).
- Wiedza kontekstowa: pliki markdown w `jarvis/context/` (profil usera, streszczenie strategii walidacji, lista odrzuconych kierunków) — ładowane do promptów w całości w v0.5.

## Kolektory v0 (wszystkie deterministyczne, zero LLM)

1. **Bramki walidacji**: stan w SQLite (daty wdrożeń, statusy gate zero/discovery/2-tygodniowe pytanie), arytmetyka dat → przypomnienia w digeście (np. "14 dni od wdrożenia u klienta X → czas na pytanie o wyłączenie systemu"). Aktualizacja przez komendy Telegram.
2. **Infra**: docker health kontenerów Argusa (docker socket read-only mount lub `docker ps` via host), zajętość dysku, grep błędów w logach 24h. Odchylenie = alert natychmiast, norma = linijka w digeście. NIE duplikuje guardiana Argusa (guardian pilnuje wnętrza Argusa; Jarvis dokłada bramki/digesty/radar i patrzy szerzej na VPS).
3. **Argus digest (tygodniowy)**: API Argusa po localhost (koniec z SSH, port 8080 zamknięty na firewallu ale localhost dostępny) — /api/sources, /api/wallets, /api/llm/usage → porównanie ze snapshotem z zeszłego tygodnia → zmiany rankingów źródeł, nowe sygnały, dojrzewające outcome'y, anomalie (backlog llm_queue, fail-rate).

## Komendy Telegram v0

- `/jarvis status` — ostatnie uruchomienia jobów, błędy, stan kolektorów (monitoring samego Jarvisa).
- `/jarvis gate <nazwa> <status> [data]` — aktualizacja bramek walidacji.
- Dead-man switch naturalny: brak porannego digestu = sygnał awarii.

## v0.5 — Radar pomysłów na zarobek (dopiero gdy v0 działa ≥1 tydzień)

- Reddit RSS (feedparser — wzorzec z Argusa, działa bez blokad; lista subredditów do ustalenia przy implementacji, np. r/SaaS, r/smallbusiness + polskie źródła) → dedup po URL/hash → batch do LLM przez router (filtr pod profil usera z `jarvis/context/`: wzorzec dokument→decyzja→akcja, self-hosted, rynek PL) → top 3–5 tygodniowo w digeście z linkami.
- Pętla feedbacku OD PIERWSZEGO DNIA radaru: `/jarvis good <n>` / `/jarvis meh <n>` → zapis do SQLite → radar raportuje własną trafność (ile good/meh miesięcznie) i preferencje wpływają na filtr. To jest "nauka" Jarvisa — wzorzec samonauki z Argusa, nie baza wektorowa.
- Wolumen LLM: ~100–300 postów/tydzień batchowane = kilkanaście calls/tydzień — mieści się w darmowych limitach z zapasem. Lekcje z Argusa: batchowanie, cache po hashu, log każdego calla.
- Nowości AI/API (zmiany w narzędziach których user używa) — w tym samym tygodniowym raporcie, ograniczone.
- Uwaga kontekstowa: istnieje pokrewny, nigdy nie zaczęty spec income-radar w Hermesie (`docs/superpowers/specs/2026-05-24-hermes-autonomous-developer-income-radar-design.md`) — radar Jarvisa go zastępuje (superseded).

## v1 (odroczone — tylko po udowodnionej potrzebie)

- pgvector / pamięć wektorowa (np. fuzzy-dedup pomysłów po miesiącach)
- read-only strona statusowa (wzorzec dashboardu Argusa)
- przeniesienie RAG na VPS (osobna decyzja)
- jakiekolwiek akcje autonomiczne

## Kryteria sukcesu v0

- Digest przychodzi regularnie przez 2 tygodnie (dead-man: brak digestu zauważalny od razu).
- Minimum 1 realna akcja usera wywołana digestem (przypomnienie bramki, wykryta awaria).
- Źródło, które tylko szumi (user je przewija) — wycinane, zamiast dokładania kolejnych.

## Ograniczenia i ryzyka

- VPS bez GPU → LLM wyłącznie przez API (router, darmowe tiery).
- RAM budget: Oracle A1 15GB, Argus zajmuje część — Jarvis ma być lekki (1 kontener, SQLite, bez Ollama).
- Free tiery LLM współdzielone z Argusem (te same klucze Gemini/Groq) — wolumen Jarvisa mały, ale logować i obserwować.
- Docker socket mount = dostęp do wszystkich kontenerów — tylko read-only, tylko do health checków.

## Poza zakresem

- Hermes na VPS, migracja czegokolwiek z laptopa
- Baza wektorowa i ingest PDF w v0
- GUI przeglądarkowe (chat)
- Wykonywanie akcji (deploy, restart, transakcje, odpowiadanie komukolwiek poza userem)
- Multi-user
