# Jarvis: autonomiczny obserwator/reporter na VPS

**Data:** 2026-07-10
**Status:** Zaakceptowany
**Projekt:** `jarvis/` (nowy, VPS obok Argusa) + `RAG/` (przenoszony na VPS jako GUI)

## Cel

Jarvis = autonomiczny obserwator/reporter na Oracle VPS (niezależny od laptopa usera), który zbiera stan systemów i strategii walidacji, wysyła digesty/alerty i przypomina o bramkach. Zasada nadrzędna: **read-only** — raportuje i przypomina, NIGDY nie wykonuje akcji samodzielnie. Autonomia wykonawcza rozważana dopiero, gdy raporty okażą się trafne (wzorzec z Argusa: najpierw zmierz wiarygodność, potem ufaj).

## Kontekst decyzji

- User chciał "autonomicznego Jarvisa"; zakres zawężony do obserwatora-reportera w służbie strategii walidacji dwutorowej (patrz `docs/superpowers/specs/2026-07-10-walidacja-dwutorowa-design.md` — Jarvis służy tej strategii).
- Hermes (laptop, 9 kontenerów) ODRZUCONY jako platforma — Jarvis musi działać 24/7 niezależnie od laptopa. Zamiast tego: lekki osobny serwis na VPS obok Argusa, sklejony ze sprawdzonych klocków Argusa.
- **2026-07-10 — decyzja usera po review: GUI-first zamiast Telegram-only.** Rekomendacja była reporter-first (Telegram, szybszy pierwszy działający element); user świadomie wybrał GUI mimo tej rekomendacji i mimo ~miesiąca wieczorów do pierwszego działającego elementu. Powód: GUI nie jest budowane od zera — **istniejący projekt RAG (`RAG/`) zostaje przeniesiony na VPS i staje się "domem" Jarvisa**. RAG ma już gotowe: login/JWT, czat z historią i streamingiem SSE, upload dokumentów drag-and-drop, parsowanie Docling, pgvector. Budowa własnego GUI od zera byłaby odrzucona jako over-engineering; reużycie gotowego stacku zmienia kalkulację.
- Telegram zdegradowany do roli dzwonka: push o digeście/alercie (własny token bota nadal wymagany — telefon/laptop, przeglądarka sama nie powiadomi). Rozmowa i dokumenty żyją w GUI, nie w Telegramie.
- Dostęp do GUI przez **Tailscale** (VPS dołącza do istniejącego tailnetu usera; telefon/laptop z appką Tailscale) — zero publicznego wystawiania portów, zero własnego HTTPS/auth-hardeningu ponad istniejący JWT RAG-a.

## Struktura faz

### Faza 1 — RAG na VPS (fundament GUI)

- Deploy stacka RAG na Oracle VPS obok Argusa: backend FastAPI + frontend + Postgres/pgvector + Redis + Celery workers.
- Adaptacje wymagane:
  - **Generacja LLM przez API zamiast lokalnego Ollamy** — router wzorowany na `argus/llm/router.py` (Gemini free → Groq free → OpenRouter free) wpięty w `RAG/backend/core/llm.py`.
  - **Embeddingi**: qwen3-embedding:0.6b na CPU VPS (mały model, wolumen niski) LUB API embeddings — decyzja przy implementacji po teście wydajności na 4 vCPU.
  - Tailscale na VPS.
- PREREQUISITE: uporządkować ~20 niezacommitowanych plików w `RAG/` (commit lub świadome odrzucenie) PRZED deployem.
- Kryterium: user loguje się z telefonu przez Tailscale, prowadzi czat z historią, wgrywa PDF i pyta o niego.

### Faza 2 — Reporter (kolektory Jarvisa)

- Jak w pierwotnym planie: bramki walidacji (arytmetyka dat), infra (docker health, dysk, logi), Argus digest tygodniowy (API localhost) — wszystko deterministyczne, zero LLM w digestach.
- **NOWE:** digesty i alerty zapisywane jako dokumenty w RAG (przeszukiwalne archiwum: "co Jarvis mówił o rankingu w czerwcu?") + push na Telegram.
- Stan Jarvisa (bramki, snapshoty, log jobów): tabele w Postgresie RAG-a (zamiast SQLite — baza już stoi na VPS).
- Aktualizacja bramek: komendy Telegram (`/jarvis gate <nazwa> <status> [data]`) — GUI-owy panel bramek to nice-to-have, nie blokuje.
- Kolektory:
  1. **Bramki walidacji**: stan w Postgresie RAG-a (daty wdrożeń, statusy gate zero/discovery/2-tygodniowe pytanie), arytmetyka dat → przypomnienia w digeście (np. "14 dni od wdrożenia u klienta X → czas na pytanie o wyłączenie systemu").
  2. **Infra**: docker health kontenerów Argusa (docker socket read-only mount lub `docker ps` via host), zajętość dysku, grep błędów w logach 24h. Odchylenie = alert natychmiast, norma = linijka w digeście. NIE duplikuje guardiana Argusa (guardian pilnuje wnętrza Argusa; Jarvis dokłada bramki/digesty/radar i patrzy szerzej na VPS).
  3. **Argus digest (tygodniowy)**: API Argusa po localhost (koniec z SSH, port 8080 zamknięty na firewallu ale localhost dostępny) — /api/sources, /api/wallets, /api/llm/usage → porównanie ze snapshotem z zeszłego tygodnia → zmiany rankingów źródeł, nowe sygnały, dojrzewające outcome'y, anomalie (backlog llm_queue, fail-rate).
- Komendy Telegram: `/jarvis status` (ostatnie uruchomienia jobów, błędy, stan kolektorów), `/jarvis gate <nazwa> <status> [data]`. Dead-man switch naturalny: brak porannego digestu = sygnał awarii.
- Kryteria: digest/alert przychodzi regularnie przez 2 tygodnie + minimum 1 realna akcja usera wywołana digestem + źródło, które tylko szumi, wycinane zamiast dokładania kolejnych.

### Faza 3 — Radar pomysłów na zarobek (dawne v0.5, bez zmian merytorycznych; dopiero gdy Faza 2 działa ≥1 tydzień)

- Reddit RSS (feedparser — wzorzec z Argusa, działa bez blokad; lista subredditów do ustalenia przy implementacji, np. r/SaaS, r/smallbusiness + polskie źródła) → dedup po URL/hash → batch do LLM przez router (filtr pod profil usera z `jarvis/context/`: wzorzec dokument→decyzja→akcja, self-hosted, rynek PL) → top 3–5 tygodniowo.
- Pętla feedbacku OD PIERWSZEGO DNIA radaru: `good`/`meh` przez Telegram (`/jarvis good <n>` / `/jarvis meh <n>`) lub przez GUI → zapis do Postgresa RAG-a → radar raportuje własną trafność (ile good/meh miesięcznie) i preferencje wpływają na filtr. To jest "nauka" Jarvisa — wzorzec samonauki z Argusa, nie baza wektorowa.
- Znaleziska zapisywane też do RAG jako dokumenty (przeszukiwalne, jak digesty z Fazy 2).
- Wolumen LLM: ~100–300 postów/tydzień batchowane = kilkanaście calls/tydzień — mieści się w darmowych limitach z zapasem. Lekcje z Argusa: batchowanie, cache po hashu, log każdego calla.
- Nowości AI/API (zmiany w narzędziach których user używa) — w tym samym tygodniowym raporcie, ograniczone.
- Uwaga kontekstowa: istnieje pokrewny, nigdy nie zaczęty spec income-radar w Hermesie (`docs/superpowers/specs/2026-05-24-hermes-autonomous-developer-income-radar-design.md`) — radar Jarvisa go zastępuje (superseded).

## Odroczone (tylko po udowodnionej potrzebie)

- Akcje autonomiczne (deploy, restart, transakcje, odpowiadanie komukolwiek poza userem).
- Multi-user.
- Publiczne wystawienie GUI (poza Tailscale).

## Ograniczenia i ryzyka

- VPS bez GPU → LLM wyłącznie przez API (router, darmowe tiery).
- ~Miesiąc wieczorów zanim cokolwiek działa (świadoma decyzja usera, patrz Kontekst decyzji); bramki walidacji w tym czasie bez automatycznych przypomnień — pilnowane ręcznie.
- RAM budget: Oracle A1 15GB. Stack RAG (Postgres+Redis+Celery+backend+frontend) + Argus na tym samym budżecie — do zważenia przy deployu: ograniczenie workerów Celery do 1, bez LangFuse na VPS w Fazie 1.
- Embeddingi CPU: wydajność do przetestowania na 4 vCPU zanim decyzja CPU vs API.
- Generacja przez darmowe API współdzielone z Argusem (te same klucze Gemini/Groq) — czat GUI może być wolny/limitowany w godzinach szczytu; jakość odpowiedzi czatu zależy od darmowych modeli (nie qwen3:4b lokalnie jak wcześniej w RAG). Wolumen Jarvisa mały, ale logować i obserwować.
- Chat RAG odpowiada Z BAZY WIEDZY (dokumenty + digesty) — to NIE jest kanał komend do Jarvisa; komendy idą przez Telegram.
- Docker socket mount = dostęp do wszystkich kontenerów — tylko read-only, tylko do health checków.

## Poza zakresem

- Budowa własnego frontendu czatu od zera (reużywamy RAG).
- Hermes na VPS, migracja czegokolwiek z laptopa (w tym migracja Hermesa).
- Wykonywanie akcji (deploy, restart, transakcje, odpowiadanie komukolwiek poza userem).
- Multi-user.
