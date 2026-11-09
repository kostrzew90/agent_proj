# Strażnik — agent bezpieczeństwa VPS Contabo (projekt)

Data: 2026-11-08 · Status: projekt do akceptacji · Gałąź: `feat/argus-litellm`, katalog `straznik/`

## Po co

Na VPS Contabo (169.58.146.162, Ubuntu 24.04, Tailscale 100.71.197.18) działa 34 kontenerów: Argus, RAG, LiteLLM, LangFuse, widok, wgniotka, Korczaka i inne. Nikt nie pilnuje ich bezpieczeństwa. Poprzedni projekt agenta bezpieczeństwa przepadł przy zmianie hostingu.

Stan na 2026-11-08:
- SSH: tylko klucze, ale ok. 1100 nieudanych prób logowania na dobę, nic ich nie blokuje.
- ufw: domyślnie deny. Z internetu otwarte tylko 22/tcp i Tailscale.
- Docker omija ufw. Strona Korczaka (`korczaka-grav`, 0.0.0.0:8096, Apache) jest publiczna celowo. Każdy inny kontener opublikowany na 0.0.0.0 byłby niezauważony.
- 56 pakietów czeka na aktualizację; `unattended-upgrades` jest aktywne.
- RAM: 12 GB, dostępne ok. 3,5 GB. Narzędzia muszą być lekkie.

Użytkownik chce: blokowania ataków, codziennego raportu, natychmiastowych alarmów, kontroli ataków na stronę Korczaka i codziennej, ostrożnej aktualizacji kontenerów.

## Cele

1. **Blokowanie atakujących** na SSH i na stronie Korczaka (CrowdSec + bouncer w zaporze).
2. **Natychmiastowy alarm na Telegram** (co 5 min sprawdzenie), gdy:
   - nastąpi udane logowanie SSH z adresu spoza Tailscale (100.64.0.0/10),
   - pojawi się port nasłuchujący na publicznym interfejsie spoza listy dozwolonych,
   - CrowdSec lub bouncer przestanie działać,
   - nocna aktualizacja się nie powiodła i nastąpił powrót do starego obrazu.
   Ten sam problem nie generuje alarmu częściej niż raz na 6 h.
3. **Sekcja „🛡️ Bezpieczeństwo” w raporcie o 21:00** (wspólny raport Argusa, `argus/argus/evening_report.py`), za ostatnie 24 h:
   - SSH: nieudane próby, zablokowane adresy, udane logowania (kto, skąd);
   - Korczaka: liczba zapytań, podejrzanych zapytań (alerty CrowdSec), zablokowanych adresów, 3 przykłady;
   - porty publiczne vs lista dozwolonych;
   - aktualizacje kontenerów: co zaktualizowano, co cofnięto;
   - system: czekające łatki bezpieczeństwa, czy potrzebny restart;
   - Trivy: poważne dziury z dostępną poprawką, per obraz;
   - kontenery z przypiętą wersją (kategoria B): czy jest nowsza wersja;
   - nowe kontenery bez kategorii.
   Gdy są ustalenia, model dopisuje 2–3 zdania „co się stało i co zrobić”.
4. **Nocna aktualizacja kontenerów kategorii A** (04:00), z kopią, sprawdzeniem zdrowia i automatycznym powrotem.
5. **Cotygodniowy skan Trivy** (niedziela 03:00) wszystkich używanych obrazów.

## Czego nie robimy (non-goals)

- Strażnik niczego nie naprawia sam poza: blokowaniem przez CrowdSec i aktualizacją kategorii A. Nie zamyka portów, nie aktualizuje systemu (to robi `unattended-upgrades`), nie restartuje serwera.
- **Kategorie B i C tylko zgłaszane** (decyzja użytkownika 2026-11-08).
- Bez Wazuha i innych ciężkich systemów (SIEM).
- Bez pilnowania Maca Studio.
- Bez panelu www; tylko Telegram.

## Anty-cele (porażka, nawet jeśli „działa”)

- Strażnik odcina użytkownika od serwera (ban na SSH przez Tailscale).
- Aktualizacja psuje działającą usługę i jej nie przywraca.
- Alarmy co 5 minut o tym samym — użytkownik przestaje je czytać.
- Dane o bezpieczeństwie wysłane do zewnętrznego modelu.
- Strażnik zjada pamięć potrzebną Argusowi/RAG.

## Ograniczenia i ustalone decyzje

**Gdzie działa:** na hoście (nie w kontenerze), bo potrzebuje `ss`, `journalctl`, `ufw`/`iptables`, `docker`. Skrypty Python 3 (systemowy, tylko biblioteka standardowa) + timery systemd. Stan i wyniki w `/var/lib/straznik/`.

**Kod:** w repo `straznik/` na gałęzi `feat/argus-litellm`. Wdrożenie z commita (`git archive`), skryptem uruchamianym przez użytkownika (`!`), jak Argus.

**CrowdSec:**
- Instalacja z oficjalnego repozytorium pakietów; kolekcje `crowdsecurity/linux`, `crowdsecurity/sshd`, `crowdsecurity/apache2` (Korczaka używa Apache, log w formacie combined na stdout kontenera).
- Odczyt logów Korczaki przez źródło `docker` (kontener `korczaka-grav`).
- Bouncer `crowdsec-firewall-bouncer-iptables` (system ma iptables-nft). **Musi blokować także w łańcuchu `DOCKER-USER`**, inaczej ruch do portu 8096 omija blokady.
- Biała lista: 100.64.0.0/10 (Tailscale), 127.0.0.0/8, sieci Dockera 172.16.0.0/12.

**Kategorie kontenerów** — plik konfiguracyjny `straznik/containers.yaml` (lista jawna, nie wykrywanie automatyczne):
- **A (auto-aktualizacja):** obrazy z registry z tagiem przypiętym do wersji głównej (pull daje tylko poprawki): `postgres:16-alpine` (argus-db-1, llmops-postgres, wgniotka-postgres, widok-db-1), `postgres:17` (langfuse-postgres), `pgvector/pgvector:pg16`, `redis:7-alpine`, `redis:7`, `caddy:2`, `langfuse:4`, `langfuse-worker:4`, `clickhouse-server:25.12`. *(Decyzja projektanta: tagi `latest`/`nightly` — grafana, ollama, minio, lightpanda, warp — mogą przeskoczyć wersję główną i migrować dane, więc trafiają do B.)*
- **B (tylko zgłaszaj nową wersję):** `litellm`, `prometheus`, `alertmanager`, `json-exporter` (mapowanie na repo GitHub, najnowsze wydanie) oraz `grafana:latest`, `ollama:latest`, `chainguard/minio`, `lightpanda:nightly`, `caomingjun/warp` (zgłaszane, gdy w registry jest nowszy digest).
- **C (tylko zgłaszaj stan obrazu bazowego/CVE):** obrazy budowane lokalnie: argus-*, rag-*, widok-app, wgniotka-*, korczaka-grav, llmops-collector, ai-flow.
- Kontener nieobecny w pliku = „nieskategoryzowany”, zgłaszany w raporcie, nieaktualizowany.

**Nocna aktualizacja (kategoria A):**
- Kolejność: kontener z najstarszym obrazem najpierw.
- `docker compose pull <usługa>` w katalogu projektu (z etykiet `com.docker.compose.project.working_dir` i `com.docker.compose.service`). Jeśli obraz bez zmian → następny kandydat.
- Limit: 1 faktycznie zaktualizowany kontener na noc; do 3, jeśli ostatni skan Trivy pokazał w którymś z nich dziurę CRITICAL/HIGH z dostępną poprawką (te idą pierwsze).
- Przed: stary obraz zachowany pod tagiem `straznik-rollback`; dla Postgresa `pg_dumpall` do `/root/backups/straznik/` (trzymamy 7 ostatnich na kontener).
- Po `docker compose up -d --no-deps <usługa>`: czekamy do 120 s; zdrowy = stan `running`, `healthy` jeśli ma healthcheck, licznik restartów nie rośnie przez 60 s.
- Niezdrowy → powrót do obrazu `straznik-rollback`, ponowne `up -d`, natychmiastowy alarm.
- Kontenery dzielące ten sam obraz aktualizowane osobno, każdy w swojej kolejce.
- *(Decyzje projektanta po przeglądzie:)* Zdrowie sprawdzane także dla kontenerów zależnych w tym samym projekcie compose oraz listą testów HTTP z `containers.yaml` (np. Argus `/health`, LiteLLM `/health/liveliness`, LangFuse `/api/public/health`, Korczaka `/`). Przed aktualizacją `langfuse-web`/`langfuse-worker` zrzut `langfuse-postgres` (migracje). Rollback obrazu nie cofa migracji danych — dlatego zrzut przed każdą aktualizacją Postgresa i LangFuse.
- Aktualizacja pomijana, gdy trwa `apt`/`dpkg` (blokada) — wtedy próba następnej nocy.
- Wszystkie kontenery na serwerze są zarządzane przez compose (sprawdzone 2026-11-08), osobna ścieżka dla `docker run` nie jest potrzebna; kontener bez etykiet compose = tylko zgłoszenie.

**Trivy:** uruchamiany jako kontener `aquasec/trivy` z wolumenem cache, tylko na czas skanu, `--scanners vuln`, obrazy skanowane po kolei, limit pamięci kontenera 1,5 GB; zapis wyników (HIGH/CRITICAL z poprawką) do `/var/lib/straznik/trivy.json`. Nieudany skan = wpis w raporcie (bez natychmiastowego alarmu).

**Model (LLM):** przez LiteLLM (100.71.197.18:4000), nowa grupa `straznik` = tylko Mac `qwen3-coder-next:q4_K_M` (wybór użytkownika 2026-11-08), **bez zapasowych modeli w chmurze**. Model ma 52 GB i wypycha z pamięci Maca model Argusa, więc wywołanie z `keep_alive: 5m` (zwolnienie pamięci po 5 min) i tylko raz dziennie, do raportu; alarmy natychmiastowe są bez modelu. Test 2026-11-08: 45 s z ładowaniem, poprawna polszczyzna, konkretne polecenia. Mac niedostępny → raport bez komentarza modelu. Model dostaje tylko listę ustaleń, nie surowe logi. Wykrywanie robią reguły, nie model. Dodanie grupy wymaga restartu LiteLLM — w ramach wdrożenia, krótka przerwa dla Argusa i RAG.

**Połączenie z raportem Argusa:** Strażnik zapisuje gotową sekcję tekstową do `/var/lib/straznik/section.txt` (około 20:50). Argus montuje katalog tylko do odczytu i dokleja sekcję jako trzecią; brak pliku lub plik starszy niż 26 h → „🛡️ Bezpieczeństwo: brak danych ze Strażnika”.

**Telegram dla alarmów:** ten sam bot i czat co Argus; skrypt (jednostki systemd jako root) czyta token z `/root/argus/.env` w czasie działania (sekret nie jest kopiowany ani zapisywany przez Strażnika).

**Zmiana w Argusie:** wolumen `/var/lib/straznik:/straznik:ro` w `argus/docker-compose.yml` i trzecia sekcja w `evening_report.py`; wdrażane razem ze Strażnikiem.

**Korczaka — statystyki:** logi Apache pokazują prawdziwe adresy klientów (sprawdzone 2026-11-08, bez proxy/CDN). „Podejrzane” = alerty CrowdSec dla tego źródła. Liczba zapytań z `docker logs --since 24h`. Logi kontenerów nie mają rotacji (json-file bez limitów) — poza zakresem, zgłoszone w raporcie jako uwaga.

**Lista dozwolonych portów publicznych:** `22/tcp`, `8096/tcp` (Korczaka), `41641/udp` (Tailscale).

**Tailscale Funnel** to druga droga z internetu, omijająca zaporę: dziś `https://vmi3495713.tailce2ab5.ts.net` → `127.0.0.1:8300` (wgniotka-caddy, demo sklepu za hasłem, odpowiada 401). Strażnik porównuje `tailscale funnel status` z listą dozwolonych (dziś: tylko ten jeden wpis); nowy wpis = natychmiastowy alarm, jak nowy port.

**Logowanie SSH (decyzja użytkownika 2026-11-09, opcja a):** Tailscale SSH wyłączone (`tailscale set --ssh=false`), więc pod 100.71.197.18 odpowiada zwykły OpenSSH na klucz. Wszystkie skrypty i sesje Claude łączą się przez Tailscale. Każde udane logowanie spoza 100.64.0.0/10 = alarm (bez listy zaufanych adresów publicznych). Publiczne 22/tcp zostaje otwarte jako zapasowe wejście.

## Do decyzji wykonawcy

- Dokładny układ skryptów i timerów, format plików stanu.
- Sposób parsowania logów SSH (journal) i liczenia statystyk Korczaki (CrowdSec `cscli alerts list -o json` + zliczanie logów kontenera).
- Sposób sprawdzania najnowszych wersji B (API GitHub releases).
- Testy: logika (kolejność, limity, decyzja zdrowy/niezdrowy, rollback, deduplikacja alarmów, budowa raportu) testowana na danych z atrapami komend; instalacja CrowdSec sprawdzana na żywym serwerze.

## Kryteria akceptacji

1. Atakujący adres z SSH lub Korczaki trafia na listę blokad i jego ruch do portu 8096 jest odrzucany (sprawdzone `cscli decisions add` na adres testowy).
2. Adres z Tailscale nigdy nie zostaje zablokowany.
3. Udane logowanie SSH spoza Tailscale → alarm w ciągu 5 min; to samo zdarzenie nie powtarza alarmu.
4. Nowy kontener opublikowany na 0.0.0.0 na porcie spoza listy → alarm w ciągu 5 min.
5. Raport o 21:00 zawiera sekcję 🛡️ ze wszystkimi punktami z „Cele 3”; brak danych → jasny komunikat, reszta raportu wychodzi.
6. Nocna aktualizacja: zaktualizowany najwyżej 1 kontener (3 przy CVE), najstarszy najpierw; niezdrowy wraca do starego obrazu i jest alarm; baza Postgres ma świeży zrzut przed aktualizacją.
7. Kategorie B i C nigdy nie są aktualizowane automatycznie.
8. Strażnik w spoczynku (bez skanu Trivy) zużywa łącznie z CrowdSec < 250 MB RAM.
9. Model dostaje tylko ustalenia; przy niedostępnym Macu raport przychodzi bez komentarza.
