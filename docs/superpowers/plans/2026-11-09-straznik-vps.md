# Strażnik VPS — plan wdrożenia

> **Dla wykonawców (agentów):** WYMAGANY SKILL: superpowers:subagent-driven-development (zalecany) albo superpowers:executing-plans. Plan realizuje się zadanie po zadaniu. Kroki mają pola wyboru (`- [ ]`).

**Cel:** zbudować na hoście VPS agenta bezpieczeństwa, który:
- blokuje atakujących (CrowdSec),
- wysyła natychmiastowe alarmy,
- dostarcza sekcję 🛡️ do raportu Argusa o 21:00,
- co noc ostrożnie aktualizuje kontenery kategorii A,
- raz w tygodniu skanuje obrazy Trivy.

**Architektura:**
- Pakiet Python 3.12, wyłącznie biblioteka standardowa plus PyYAML (na hoście jest `python3-yaml`). Instalowany w `/opt/straznik` i uruchamiany przez timery systemd jako root.
- Wszystkie wywołania poleceń systemowych przechodzą przez jedną funkcję `run`, którą testy podmieniają. Logika jest testowana lokalnie na Windows (`python -m pytest`), bez Dockera i bez hosta.
- Stan i wyniki: `/var/lib/straznik/`. Argus montuje ten katalog tylko do odczytu i dokleja sekcję raportu.

**Technologie:**
- Python 3.12 (biblioteka standardowa + PyYAML), systemd timers.
- CrowdSec + `crowdsec-firewall-bouncer-iptables`.
- Trivy jako kontener `aquasec/trivy`.
- LiteLLM, grupa `straznik` (Mac `qwen3-coder-next:q4_K_M`).
- Telegram Bot API.

**Spec:** `docs/superpowers/specs/2026-11-08-straznik-vps-design.md`. Wykonawcy czytają go razem z tym planem.

## Ograniczenia globalne

**Zasady pracy:**
- Kod hosta: tylko biblioteka standardowa i `yaml` (PyYAML). Żadnych zależności z `pip` na hoście.
- NIGDY `git stash`. Wdrożenie wyłącznie z commita (`git archive`). Na produkcji działa tylko skrypt uruchamiany przez użytkownika (`!`).
- SSH zawsze na `root@100.71.197.18` (Tailscale), nigdy na adres publiczny.
- Sekrety czytane w czasie działania: token Telegrama z `/root/argus/.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`), klucz LiteLLM z `/root/litellm/.env` (`LITELLM_MASTER_KEY`). Strażnik niczego nie zapisuje ani nie loguje z tych plików.
- Wszystkie teksty dla użytkownika po polsku, z polskimi znakami.

**Ustalone wartości:**
- Katalog stanu: `/var/lib/straznik/`.
- Biała lista CrowdSec: `100.64.0.0/10`, `127.0.0.0/8`, `172.16.0.0/12`.
- Dozwolone porty publiczne: `22/tcp`, `8096/tcp`, `41641/udp`.
- Dozwolony Funnel: `https://vmi3495713.tailce2ab5.ts.net` → `http://127.0.0.1:8300`.
- Alarm o tym samym problemie najwyżej raz na 6 h.

**Harmonogram (czas Europe/Warsaw):**

| Zadanie | Kiedy |
|---|---|
| Kontrola (watch) | co 5 min |
| Raport | 20:50 |
| Aktualizacja | 04:00 |
| Skan Trivy | niedziela 03:00 |

**Aktualizacja kontenerów:**
- 1 kontener na noc. Do 3, gdy w obrazach są dziury CRITICAL lub HIGH z dostępną poprawką.
- Czekanie na zdrowie do 120 s, potem 60 s obserwacji licznika restartów.
- 7 zrzutów bazy na kontener w `/root/backups/straznik/`.

**Trivy:** `--scanners vuln`, limit pamięci 1,5 GB.

**Model:** grupa LiteLLM `straznik`, `keep_alive: "5m"`, bez modeli zapasowych w chmurze.

**Cel pamięciowy:** Strażnik razem z CrowdSec w spoczynku zużywa mniej niż 250 MB RAM.

## Na co szczególnie zwrócić uwagę w przeglądzie

1. **`ss` pokazuje porty związane z Tailscale albo lokalne** (100.x, 127.x, fd7a:…, `%tailscale0`). Nie są publiczne i nie mogą wywołać alarmu. Test w zadaniu 2.
2. **Obraz pobrany przez `docker compose pull` jest identyczny jak uruchomiony** (ten sam ID obrazu). Wtedy nie restartujemy kontenera i nie liczymy go do limitu, tylko przechodzimy do następnego kandydata. Test w zadaniu 3.
3. **Brak pliku `/var/lib/straznik/trivy.json` albo uszkodzony JSON.** Aktualizacja działa dalej, bez priorytetu dziur, a raport pisze „brak skanu”. Testy w zadaniach 3 i 4.
4. **Mac albo LiteLLM nie odpowiada.** Sekcja raportu powstaje bez komentarza modelu i bez wyjątku. Test w zadaniu 5.
5. **Brak tokenu Telegrama albo błąd sieci przy alarmie.** Kontrola nie przerywa się, a alarm nie jest oznaczony jako wysłany, więc ponowi się przy następnym przebiegu. Test w zadaniu 1.

---

### Zadanie 1: Szkielet, konfiguracja, stan, alarmy

**Pliki:**
- Utwórz: `straznik/straznik/__init__.py`, `straznik/straznik/common.py`, `straznik/containers.yaml`, `straznik/tests/conftest.py`, `straznik/tests/test_common.py`, `straznik/pytest.ini`

**Interfejsy (Produces):**
- `run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess`. Używa `text=True` i `capture_output=True`, nie podnosi wyjątku przy kodzie wyjścia różnym od 0. Moduły importują `common.run` i wywołują je przez parametr `runner=run`, żeby testy mogły go podmienić.
- `STATE_DIR = Path(os.getenv("STRAZNIK_STATE_DIR", "/var/lib/straznik"))`.
- `load_state(name: str) -> dict` i `save_state(name: str, data: dict) -> None`. Pliki JSON `STATE_DIR/<name>.json`, zapis atomowy (plik tymczasowy, potem `os.replace`). Brak pliku albo uszkodzony plik → `{}`.
- `load_config(path: Path | None = None) -> dict`. Wczytuje `containers.yaml`; domyślnie plik leży obok pakietu.
- `read_env_value(path: str, key: str) -> str | None`. Parsuje plik `.env`, czyli linie `KEY=VALUE` z opcjonalnymi cudzysłowami.
- `send_telegram(text: str, token: str | None = None, chat: str | None = None) -> bool`. Domyślnie bierze dane z `/root/argus/.env` i wysyła przez `urllib.request`. Zwraca True przy HTTP 200. Każdy błąd → False, bez wyjątku.
- `alert(key: str, text: str, now: datetime | None = None, sender=send_telegram) -> bool`. Deduplikacja w stanie `alerts`, pod kluczem `key` zapisuje czas ostatniego wysłania:
  - jeśli od ostatniego wysłania minęło mniej niż 6 h → nie wysyła, zwraca False;
  - zapisuje czas tylko wtedy, gdy `sender` zwrócił True.
- `containers.yaml`:
  - sekcje `allowed_public_ports` (lista `"22/tcp"`…), `allowed_funnel` (lista `{url, target}`), `crowdsec_whitelist`;
  - sekcja `categories` z kluczami `A`, `B`, `C`, w każdej lista wpisów `{container, image?, github_repo?, http_check?, postgres?: true, dump_before?: <kontener>}`;
  - przypisanie kontenerów dokładnie według sekcji „Kategorie kontenerów” w specu, w tym `langfuse-web` i `langfuse-worker` z `dump_before: langfuse-postgres`;
  - `http_check` dla: `argus-app` → `http://100.71.197.18:8080/health`, `litellm` → `http://100.71.197.18:4000/health/liveliness`, `langfuse-web` → `http://100.71.197.18:3001/api/public/health`, `korczaka-grav` → `http://127.0.0.1:8096/`.

- [ ] **Krok 1: Testy, które na razie nie przechodzą.** W `test_common.py`:
  - `test_state_roundtrip_and_corrupt`: zapis i odczyt dają ten sam słownik; uszkodzony plik → `{}`;
  - `test_read_env_value_quotes`;
  - `test_alert_dedup_6h`: wysyła o t0; o t0+5h59m zwraca False; o t0+6h01m zwraca True;
  - `test_alert_not_marked_when_send_fails`: sender zwraca False, więc kolejne wywołanie znowu próbuje wysłać;
  - `test_config_has_all_categories`: `A`, `B`, `C` są niepuste, `argus-db-1` ∈ A, `litellm` ∈ B, `argus-app` ∈ C, `grafana`/`argus-grafana` ∈ B.

  `conftest.py` ustawia `STRAZNIK_STATE_DIR` na `tmp_path` (monkeypatch + przeładowanie albo funkcja zwracająca katalog).
- [ ] **Krok 2:** `cd straznik && python -m pytest -q` → FAIL (brak modułów).
- [ ] **Krok 3:** Zaimplementuj `common.py` i `containers.yaml`.
- [ ] **Krok 4:** `python -m pytest -q` → PASS.
- [ ] **Krok 5:** Commit `feat(straznik): szkielet, stan, alarmy z deduplikacja`.

### Zadanie 2: Kontrola co 5 minut (watch)

**Pliki:** Utwórz `straznik/straznik/watch.py` i `straznik/tests/test_watch.py`.

**Interfejsy:**
- Korzysta z: `run`, `alert`, `load_config`, `load_state`, `save_state` z zadania 1.
- Udostępnia:
  - `parse_ssh_accepted(journal_text: str) -> list[dict]`. Każdy element ma postać `{ts, user, ip, method}` i pochodzi z linii `Accepted publickey for root from 1.2.3.4 port …`.
  - `is_tailscale(ip: str) -> bool` (100.64.0.0/10 albo fd7a:115c:a1e0::/48).
  - `parse_public_listeners(ss_text: str) -> set[str]`. Zwraca zbiór `"8096/tcp"`, `"41641/udp"`… Wejście to wynik `ss -tulnH`. Pomija adresy pętli zwrotnej, Tailscale (100.64/10, fd7a:…), dowiązane do interfejsu (`%…`) i 172.16/12.
  - `parse_funnel(status_text: str) -> list[dict]`. Każdy element ma postać `{url, target}` i pochodzi z wyniku `tailscale funnel status`.
  - `check(now=None, runner=run, alert_fn=alert) -> list[str]`. Zwraca listę kluczy wysłanych alarmów.

**Zachowanie `check`:**
1. **Logowania SSH:**
   - źródło: `journalctl -u ssh --since "<ostatni przebieg albo 10 min temu>" -o short-iso`;
   - każde logowanie spoza Tailscale → alarm z kluczem `ssh:<ip>` i treścią „🚨 Logowanie SSH spoza Tailscale: root z <ip> o <czas>. Jeśli to nie Ty — natychmiast zmień klucze.”;
   - stan `watch.last_run` zapisywany na końcu.
2. **Porty publiczne:**
   - porty z `parse_public_listeners` minus dozwolone → alarm `port:<port>`.
3. **Funnel:**
   - wpisy spoza `allowed_funnel` → alarm `funnel:<url>`.
4. **CrowdSec:**
   - `systemctl is-active crowdsec` oraz `systemctl is-active crowdsec-firewall-bouncer`;
   - jeśli którekolwiek ≠ `active` → alarm `crowdsec:<usługa>`.

**Kroki:**
- [ ] **Krok 1: Testy, które na razie nie przechodzą.** Prawdziwe próbki wyjścia z VPS z 2026-11-08 jako stałe w teście, w tym linie `ss` z sekcji „ports” z tej rozmowy:
  - `0.0.0.0:22`, `0.0.0.0:8096`, `udp 0.0.0.0:41641`;
  - `[fd7a:…]%tailscale0:443`;
  - `100.71.197.18:8080`;
  - `127.0.0.1:8300`.

  Testy:
  - `test_public_listeners_ignores_tailscale_and_local` → `{"22/tcp","8096/tcp","41641/udp"}`;
  - `test_check_alerts_new_public_port`: dodatkowa linia `0.0.0.0:18999` → jeden alarm `port:18999/tcp`;
  - `test_check_ssh_tailscale_login_silent`;
  - `test_check_ssh_public_login_alerts`;
  - `test_check_funnel_unknown_alerts`;
  - `test_check_crowdsec_down_alerts`.
- [ ] **Krok 2:** uruchom testy → FAIL.
- [ ] **Krok 3:** zaimplementuj `watch.py`. Dodaj `if __name__ == "__main__": check()`.
- [ ] **Krok 4:** testy → PASS.
- [ ] **Krok 5:** commit `feat(straznik): kontrola co 5 min (ssh, porty, funnel, crowdsec)`.

### Zadanie 3: Nocna aktualizacja kategorii A

**Pliki:** Utwórz `straznik/straznik/updater.py` i `straznik/tests/test_updater.py`.

**Interfejsy:**
- Korzysta z: `run`, `alert`, `load_config`, `load_state`, `save_state`, `STATE_DIR`.
- Udostępnia:
  - `pick_candidates(containers: list[dict], vulnerable: set[str]) -> list[dict]`. Wejście to wpisy kategorii A uzupełnione o `image_created`. Kolejność wyniku:
    1. najpierw kontenery, których obraz jest w `vulnerable`;
    2. potem rosnąco po `image_created`.
  - `vulnerable_images(trivy: dict) -> set[str]`. Zwraca obrazy, które mają w `trivy.json` co najmniej jedną dziurę CRITICAL lub HIGH z `fixed_version`.
  - `apt_busy(runner=run) -> bool`. Sprawdza `fuser /var/lib/dpkg/lock-frontend`; kod wyjścia 0 oznacza zajęte.
  - `update_one(entry: dict, runner=run, sleep=time.sleep, now=None) -> str`. Zwraca `"unchanged" | "updated" | "rolled_back" | "failed"`.
  - `nightly(runner=run, sleep=time.sleep, now=None) -> list[dict]`. Wynik dopisuje do stanu `updates` (lista `{ts, container, result, old_image, new_image}`, przechowywanie 30 dni).

**Algorytm `update_one`** (zapisany, bo nie wynika z samej sygnatury):
1. Z `docker inspect <c>` odczytaj etykiety `com.docker.compose.project.working_dir` i `com.docker.compose.service` oraz bieżący ID obrazu (`.Image`). Brak etykiet → `"failed"` (tylko zgłoszenie).
2. `docker compose pull <service>` (cwd = working_dir). Odczytaj nowy ID obrazu: `docker image inspect <image ref> --format {{.Id}}`. Jeśli taki sam jak bieżący → `"unchanged"`.
3. `docker tag <stary ID> <repozytorium>:straznik-rollback`.
4. Zrzut bazy przed aktualizacją:
   - jeśli `postgres: true` → zrzut tego kontenera;
   - jeśli `dump_before` → zrzut kontenera wskazanego w `dump_before`;
   - polecenie: `docker exec <c> pg_dumpall -U <user>`, gdzie `user` to `POSTGRES_USER` z `docker inspect` (domyślnie `postgres`);
   - wynik do `/root/backups/straznik/<c>-<YYYYmmdd-HHMM>.sql.gz` (gzip w Pythonie);
   - zostaje 7 najnowszych plików na kontener;
   - zrzut nieudany → przerwij bez aktualizacji, zwróć `"failed"` i wyślij alarm.
5. `docker compose up -d --no-deps <service>`.
6. Sprawdź zdrowie:
   - co 5 s przez maksymalnie 120 s: `State.Status == running` i (`Health.Status == healthy` albo brak healthchecka);
   - potem przez 60 s licznik `RestartCount` nie może rosnąć;
   - potem `http_check` tego kontenera oraz `http_check` wszystkich kontenerów z tym samym `working_dir` → każdy musi zwrócić kod HTTP mniejszy niż 500.
7. Niezdrowy:
   - `docker tag <repozytorium>:straznik-rollback <image ref>`, potem `docker compose up -d --no-deps <service>`;
   - alarm `update:<c>` z treścią „⚠️ Aktualizacja <c> nieudana — przywrócono poprzedni obraz.”;
   - zwróć `"rolled_back"`.
8. Zdrowy → `"updated"`.

**`nightly`:**
- jeśli `apt_busy` → zapisz wynik `skipped_apt` i zakończ;
- limit = 3, jeśli zbiór `vulnerable` przecina się z obrazami kategorii A, inaczej 1;
- przechodzi po kandydatach, dopóki liczba wyników `updated` + `rolled_back` nie osiągnie limitu;
- `unchanged` nie liczy się do limitu.

**Kroki:**
- [ ] **Krok 1: Testy, które na razie nie przechodzą.** Atrapa `runner` to słownik: prefiks polecenia → (kod, stdout).
  - `test_pick_candidates_vulnerable_first_then_oldest`;
  - `test_update_unchanged_image_no_restart`: brak wywołań `up -d` ani `tag`;
  - `test_update_healthy_postgres_dumps_first`: kolejność wywołań to `pull`, `tag`, `pg_dumpall`, `up`;
  - `test_update_unhealthy_rolls_back_and_alerts`;
  - `test_update_dependent_http_fail_rolls_back`;
  - `test_dump_failure_aborts_update`;
  - `test_nightly_limit_1_and_3_with_cve`;
  - `test_nightly_skips_when_apt_busy`;
  - `test_nightly_missing_trivy_json_still_runs`;
  - `test_only_category_A_ever_updated`: kontenery B i C nigdy nie pojawiają się w poleceniach `pull` ani `up`.
- [ ] **Krok 2:** FAIL.
- [ ] **Krok 3:** zaimplementuj `updater.py` z `__main__` → `nightly()`.
- [ ] **Krok 4:** PASS.
- [ ] **Krok 5:** commit `feat(straznik): nocna aktualizacja kategorii A z kopia i rollbackiem`.

### Zadanie 4: Skan Trivy i nowe wersje (B, C)

**Pliki:** Utwórz `straznik/straznik/scan.py` i `straznik/tests/test_scan.py`.

**Interfejsy:**
- `parse_trivy(report: dict) -> list[dict]`. Wejście to raport `trivy image -f json`. Zwraca listę `{id, pkg, severity, installed, fixed_version}`, tylko pozycje CRITICAL i HIGH z niepustym `FixedVersion`.
- `weekly_scan(runner=run, now=None) -> dict`:
  - dla każdego unikalnego obrazu uruchomionego kontenera (`docker ps --format {{.Image}}`) uruchamia `docker run --rm --memory 1536m -v /var/run/docker.sock:/var/run/docker.sock -v straznik-trivy-cache:/root/.cache aquasec/trivy:latest image --scanners vuln -q -f json <image>`;
  - zapisuje do `/var/lib/straznik/trivy.json` strukturę `{"scanned_at": ..., "images": {image: [findings]}, "errors": {image: msg}}`.
- `latest_github_release(repo: str, fetch=urlopen_json) -> str | None` korzysta z `https://api.github.com/repos/<repo>/releases/latest` i zwraca `tag_name`.
- `check_versions(runner=run, fetch=...) -> dict`. Zapisuje wynik do `/var/lib/straznik/versions.json`:
  - dla wpisów B z `github_repo`: porównanie bieżącego tagu obrazu z najnowszym wydaniem;
  - dla wpisów B bez `github_repo`: porównanie digestu z registry (`docker buildx imagetools inspect <ref> --format '{{json .Manifest.Digest}}'`) z `RepoDigests` uruchomionego obrazu.

  Nie pobiera obrazów.

**Kroki:**
- [ ] **Krok 1: Testy.**
  - `test_parse_trivy_keeps_only_fixable_high_critical`, na małym, prawdziwym w kształcie raporcie JSON;
  - `test_weekly_scan_records_error_per_image`;
  - `test_check_versions_newer_release_reported`;
  - `test_check_versions_digest_changed_reported`.
- [ ] **Krok 2:** FAIL.
- [ ] **Krok 3:** zaimplementuj `scan.py` z `__main__`. Kolejność: `weekly_scan()`, potem `check_versions()`.
- [ ] **Krok 4:** PASS.
- [ ] **Krok 5:** commit `feat(straznik): tygodniowy skan trivy i sprawdzanie nowych wersji`.

### Zadanie 5: Raport dzienny i komentarz modelu

**Pliki:** Utwórz `straznik/straznik/report.py` i `straznik/tests/test_report.py`.

**Interfejsy:**
- Korzysta z: `parse_ssh_accepted`, `is_tailscale`, `parse_public_listeners`, `parse_funnel` (zadanie 2); stanu `updates` (zadanie 3); plików `trivy.json` i `versions.json` (zadanie 4).
- `collect(now=None, runner=run) -> dict`, ostatnie 24 h:
  - `ssh_failed`: liczba linii `Failed|Invalid user` z journala;
  - `ssh_logins`: lista z `parse_ssh_accepted`, z polem `outside: bool`;
  - `crowdsec`: z `cscli decisions list -o json` i `cscli alerts list --since 24h -o json`, liczba zablokowanych adresów ogółem oraz dla scenariuszy `ssh`, `http`/`apache`;
  - `korczaka`:
    - `requests` = liczba linii z `docker logs --since 24h korczaka-grav`, które wyglądają jak log dostępu;
    - `suspicious` = alerty CrowdSec, których źródło dotyczy kontenera korczaka;
    - `blocked`;
    - `examples` = do 3 linii żądań z adresów zablokowanych albo z alertów;
  - `ports`, `funnel`: stan względem dozwolonych;
  - `updates`: wpisy z ostatnich 24 h;
  - `apt_security`: liczba pakietów z `apt list --upgradable`, w których nazwie repozytorium jest `-security`;
  - `reboot_required`: czy istnieje `/var/run/reboot-required`;
  - `trivy`: obraz → liczba dziur, plus `scanned_at` albo `None`;
  - `versions`;
  - `uncategorized`: kontenery z `docker ps` nieobecne w `containers.yaml`.
- `format_section(data: dict) -> str`. Nagłówek `🛡️ Bezpieczeństwo — ostatnie 24 h`, a pod nim po jednej linii na każdy punkt z sekcji spec „Cele 3”. Puste kategorie pisze jako „brak”. Gdy nie ma skanu Trivy: „Trivy: brak skanu”. Na końcu stała uwaga „Logi kontenerów bez rotacji”, dopóki `docker info` nie pokazuje `max-size`. Tę uwagę wyłącz, jeśli komplikuje kod, i zapisz decyzję w commicie.
- `findings(data: dict) -> list[str]`. Same ustalenia wymagające działania: logowania z zewnątrz, nowe porty lub wpisy Funnel, nieudane aktualizacje, łatki bezpieczeństwa > 0, wymagany restart, dziury z poprawką, nowsze wersje B, kontenery bez kategorii. Pusta lista → bez komentarza modelu.
- `llm_comment(findings: list[str], post=urlopen_json_post) -> str | None`:
  - `POST http://100.71.197.18:4000/v1/chat/completions`, `model: "straznik"`, nagłówek `Authorization: Bearer <LITELLM_MASTER_KEY z /root/litellm/.env>`, timeout 240 s, temperatura 0,2;
  - prompt: „Jesteś asystentem bezpieczeństwa serwera. Na podstawie ustaleń napisz po polsku 2-3 krótkie zdania: co jest najważniejsze i co konkretnie zrobić. Bez wstępów.” + ustalenia;
  - każdy błąd → `None`.
- `daily(now=None, runner=run) -> str`. Składa `format_section`, a jeśli jest komentarz, dopisuje `"\n💬 " + komentarz`. Zapisuje atomowo do `/var/lib/straznik/section.txt` i zwraca tekst.

**Kroki:**
- [ ] **Krok 1: Testy.**
  - `test_format_section_all_points_present`;
  - `test_format_section_empty_day_says_brak`;
  - `test_findings_empty_no_llm_call`;
  - `test_llm_failure_section_without_comment`;
  - `test_daily_writes_section_file`;
  - `test_collect_missing_trivy_json`.
- [ ] **Krok 2:** FAIL.
- [ ] **Krok 3:** zaimplementuj `report.py` z `__main__` → `daily()`.
- [ ] **Krok 4:** PASS.
- [ ] **Krok 5:** commit `feat(straznik): raport dzienny + komentarz modelu`.

### Zadanie 6: Instalacja na hoście (CrowdSec, systemd)

**Pliki do utworzenia:**
- `straznik/deploy/install.sh`;
- `straznik/deploy/crowdsec/acquis-korczaka.yaml`;
- `straznik/deploy/crowdsec/whitelist-straznik.yaml`;
- `straznik/deploy/crowdsec/bouncer-override.yaml`;
- `straznik/deploy/systemd/straznik-{watch,report,update,scan}.{service,timer}`.

**Ustalenia:**
- `install.sh` (idempotentny, `set -euo pipefail`):
  1. Instaluje CrowdSec z oficjalnego repozytorium (`curl -s https://install.crowdsec.net | sh`, potem `apt-get install -y crowdsec crowdsec-firewall-bouncer-iptables`).
  2. Instaluje kolekcje `crowdsecurity/linux`, `crowdsecurity/sshd`, `crowdsecurity/apache2`.
  3. Kopiuje pliki konfiguracji: acquis do `/etc/crowdsec/acquis.d/korczaka.yaml` oraz whitelistę do `/etc/crowdsec/parsers/s02-enrich/straznik-whitelist.yaml`.
  4. Ustawia w `/etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml` `iptables_chains: [INPUT, DOCKER-USER]`.
  5. Przeładowuje oba serwisy.
  6. Kopiuje pakiet do `/opt/straznik`.
  7. Instaluje jednostki systemd i wykonuje `systemctl daemon-reload` oraz `enable --now` dla 4 timerów.
- Acquis:

  ```yaml
  source: docker
  container_name: [korczaka-grav]
  labels: {type: apache2}
  ```
- Jednostki `.service`: `Type=oneshot`, `WorkingDirectory=/opt/straznik`, `ExecStart=/usr/bin/python3 -m straznik.<watch|report|updater|scan>`.
- Timery:
  - `OnCalendar=*:0/5` (watch);
  - `*-*-* 20:50:00 Europe/Warsaw`;
  - `*-*-* 04:00:00 Europe/Warsaw`;
  - `Sun *-*-* 03:00:00 Europe/Warsaw`;
  - wszystkie z `Persistent=true`.
- [ ] **Krok 1:** `bash -n straznik/deploy/install.sh` → bez błędów składni. Sprawdź jednostki: `systemd-analyze verify` uruchomione na VPS w zadaniu 9.
- [ ] **Krok 2:** commit `feat(straznik): instalator crowdsec + timery systemd`.

### Zadanie 7: Sekcja Strażnika w raporcie Argusa

**Pliki:**
- Modyfikuj: `argus/argus/evening_report.py`, `argus/docker-compose.yml` (usługa `app`: `volumes: ["/var/lib/straznik:/straznik:ro"]`).
- Test: `argus/tests/test_evening_report.py`.

**Interfejsy:** `straznik_section(path="/straznik/section.txt", now=None) -> str`, w `evening_report.py`:
- plik nie istnieje albo jest starszy niż 26 h (mtime) → `"🛡️ Bezpieczeństwo: brak danych ze Strażnika"`;
- inaczej treść pliku.

Dodaj ją jako trzecią sekcję, w tej samej obudowie try/except co pozostałe.

- [ ] **Krok 1:** Testy:
  - `test_straznik_section_fresh_file`;
  - `test_straznik_section_missing_or_stale`;
  - `test_evening_report_has_three_sections`.
- [ ] **Krok 2:** FAIL.
- [ ] **Krok 3:** zaimplementuj.
- [ ] **Krok 4:** `cd argus && python -m pytest -q`. Wynik: wyłącznie 6 znanych porażek z linii bazowej (test_entry_backdate ×3, test_evaluator ×2, test_llm_extractor ×1).
- [ ] **Krok 5:** commit `feat(argus): sekcja Straznika w raporcie wieczornym`.

### Zadanie 8: Grupa LiteLLM `straznik`

**Pliki:** Modyfikuj `litellm/config.yaml`.

- [ ] **Krok 1:** Dodaj grupę `straznik` z jedną pozycją: `{<<: *mac, model: ollama_chat/qwen3-coder-next:q4_K_M, keep_alive: "5m", timeout: 240, stream_timeout: 240}` i `model_info: *mac_info`. Dopisz ją do komentarza nagłówka, z adnotacją „bez chmury — dane bezpieczeństwa zostają u nas”.
- [ ] **Krok 2:** `python -c "import yaml; yaml.safe_load(open('litellm/config.yaml'))"` → bez błędu.
- [ ] **Krok 3:** commit `feat(litellm): grupa straznik (tylko Mac qwen3-coder-next)`.

### Zadanie 9: Wdrożenie i sprawdzenie na żywo

**Pliki:** skrypt w scratchpadzie sesji (nie w repo): `straznik_deploy_<commit>.sh`. Uruchamia go użytkownik przez `!`.

**Co robi skrypt:**
1. Kopia zapasowa: `/etc/crowdsec` (jeśli jest), `~/argus/docker-compose.yml`, `~/litellm/config.yaml`.
2. `git archive <commit> straznik argus/docker-compose.yml argus/argus/evening_report.py litellm/config.yaml` rozpakowane do katalogu tymczasowego na VPS, potem `bash install.sh`.
3. Argus: kopiuje 2 pliki, potem `build app && up -d --no-deps app`.
4. LiteLLM: kopiuje config, potem `docker compose up -d --force-recreate litellm` i czeka na `/health/liveliness`.

**Sprawdzenia** (każde wypisuje wynik):
- [ ] Wszystkie 4 timery mają `systemctl list-timers 'straznik-*'` z następnym uruchomieniem.
- [ ] `python3 -m straznik.watch` bez alarmu. Na tym etapie jedyne logowanie przychodzi przez Tailscale.
- [ ] **Kryterium 1:** `cscli decisions add --ip 203.0.113.7 --duration 5m`. Reguła DROP w `DOCKER-USER` i w `INPUT` jest widoczna przez `iptables -S`. Na koniec `cscli decisions delete --ip 203.0.113.7`.
- [ ] **Kryterium 2:** `cscli decisions add --ip 100.79.154.116 --duration 1m` zostaje odrzucone przez whitelistę albo nie pojawia się w `iptables`. Wynik zapisz.
- [ ] **Kryterium 4:** `docker run -d --rm --name straznik-test -p 0.0.0.0:18999:80 nginx:alpine`, potem `python3 -m straznik.watch`, potem `docker stop straznik-test`. Oczekiwany alarm na Telegramie `port:18999/tcp`.
- [ ] `python3 -m straznik.report`. `cat /var/lib/straznik/section.txt` pokazuje wszystkie punkty. Z kontenera Argusa działa `docker exec argus-app cat /straznik/section.txt`.
- [ ] **Kryterium 8:** `systemctl show crowdsec crowdsec-firewall-bouncer -p MemoryCurrent`. Suma mniejsza niż 250 MB.
- [ ] Zdrowie Argusa i LiteLLM bez zmian: `/health` = 200, `docker inspect` RestartCount = 0.
- [ ] Pierwsza aktualizacja i skan Trivy wykonują się same według harmonogramu. Wynik sprawdzić w raporcie następnego dnia (kryterium 6) oraz po pierwszej niedzieli.
- [ ] Zapisz w pamięci projektu `project_straznik.md` stan wdrożenia i pułapki.
