# Deploy strony Artur Borzewski na home.pl + runbook aktualizacji

**Data:** 2026-07-28
**Projekt:** `Arturborzewski/` (Next.js 14 static export, strona kancelarii adwokackiej)
**Cel:** Postawić zbudowaną stronę na kupionej domenie w home.pl oraz dostarczyć powtarzalny, udokumentowany proces aktualizacji strony o zmiany przygotowane lokalnie.

---

## Problem / kontekst

- Strona istnieje jako Next.js 14 z `output: 'export'` → build produkuje statyczny katalog `out/`, gotowy do wgrania na shared hosting.
- Jedyny element serwerowy: formularz kontaktowy PHP (`contact.php`, `get-csrf.php`, PHPMailer przez `composer.json`, Cloudflare Turnstile, SMTP home.pl).
- Istnieje już `README.md` i `DEVELOPMENT.md` opisujące ręczny FTP, ale **nie ma automatyzacji** ani jednego runbooka „source of truth" dla aktualizacji.

### Stan wyjściowy (ustalony z userem)
- Domena kupiona, dostęp do panelu home.pl, hosting www najpewniej aktywny.
- **Konto FTP jeszcze nie istnieje** — trzeba założyć w panelu.
- Deploy: **skrypt automatyczny** (jedna komenda).
- **Etap 1 = sama strona.** Formularz kontaktowy (SMTP + Turnstile + `composer install`) w osobnym, późniejszym kroku.
- Protokół: **FTPS** (FTP po TLS) jako domyślny, z możliwością przełączenia na zwykły FTP w `.env`.

### Out of scope (Etap 1)
- Konfiguracja i uruchomienie formularza kontaktowego (osobny etap — opisany w runbooku jako sekcja „później").
- Zakup/aktywacja hostingu (zakładamy, że hosting istnieje).
- Zmiany w wyglądzie/treści strony (to robi się w normalnym workflow aktualizacji).
- CI/CD w chmurze (deploy pozostaje lokalny, na żądanie).

---

## Wybrane podejście

**Skrypt Node.js** (biblioteka `basic-ftp`, tryb FTPS) uruchamiany przez `npm run deploy`, czytający dane logowania z `Arturborzewski/.env` (poza repo). Wybrany zamiast WinSCP CLI (tylko Windows, osobna instalacja) i czystego PowerShell FTP (kruchy przy plikach binarnych i katalogach) — bo jest cross-platform, powtarzalny i żyje w tym samym ekosystemie co projekt.

---

## Architektura rozwiązania

### 1. Setup jednorazowy (panel home.pl) — udokumentowany, wykonuje user
1. Założenie konta FTP/SFTP w panelu → host, login, hasło, port.
2. Weryfikacja, że domena wskazuje na katalog strony (`public_html` lub odpowiedni katalog domeny).
3. Utworzenie `Arturborzewski/.env` z danymi FTP (na bazie `.env.example`).
4. Dopisanie `.env` do `Arturborzewski/.gitignore`.

### 2. Skrypt deployu — `Arturborzewski/scripts/deploy.mjs`
- Wejście: zmienne z `.env`:
  - `FTP_HOST`, `FTP_USER`, `FTP_PASSWORD`, `FTP_PORT` (domyślnie 21)
  - `FTP_SECURE` (domyślnie `true` → FTPS)
  - `FTP_REMOTE_DIR` (domyślnie `/public_html` — konfigurowalne, bo katalog domeny bywa inny)
- Działanie:
  - Sprawdza, że `out/` istnieje (jeśli nie → komunikat „uruchom najpierw build").
  - Łączy się przez FTPS, rekurencyjnie wgrywa całą zawartość `out/` do `FTP_REMOTE_DIR`.
  - **Bez destrukcyjnego mirrora** domyślnie: nadpisuje pliki, ale **nie kasuje** zdalnych plików nieobecnych lokalnie. Powód: chroni `vendor/` (PHPMailer instalowany na serwerze, poza repo) i logi formularza (`mail_error.log`) w przyszłym etapie.
  - Flaga `--clean` włącza mirror z kasowaniem (świadome, jawne użycie).
  - Loguje postęp i podsumowanie (ile plików wgrano).
- Obsługa błędów: czytelny komunikat przy braku `.env`, błędzie logowania, braku katalogu zdalnego.

### 3. Skrypty npm (`package.json`)
- `deploy` → `npm run build && node scripts/deploy.mjs`
- `deploy:only` → `node scripts/deploy.mjs` (sam upload bez rebuildu)
- Zależność dev: `basic-ftp`, `dotenv` (do wczytania `.env`).

### 4. Pliki konfiguracyjne
- `Arturborzewski/.env.example` — szablon z opisem każdej zmiennej (commitowany).
- `Arturborzewski/.gitignore` — dopisanie `.env`.

### 5. Dokumentacja — `Arturborzewski/DEPLOY.md` (główny runbook, source of truth)
Sekcje:
1. **Setup jednorazowy** — panel home.pl krok po kroku: konto FTP, podpięcie domeny, wypełnienie `.env`.
2. **Pierwszy deploy** — `npm install` → `npm run deploy` → weryfikacja pod domeną.
3. **Workflow aktualizacji** (rdzeń zadania) — jak nanosić lokalne rozwinięcia i publikować:
   - Zmiana treści/danych → `content/site.json`
   - Zmiana/dodanie zdjęć → `public/images/`
   - Zmiana kodu/układu → `app/`
   - Zawsze zakończone: `npm run deploy`
   - Przykłady typowych zmian (edytuj → deploy → live).
4. **Formularz kontaktowy — konfiguracja (etap „później")** — SMTP home.pl, klucze Turnstile, `composer install --no-dev`, uzupełnienie sekretów w `contact.php`. Uwaga o `--clean` (nie kasować `vendor/`).
5. **Bezpieczeństwo** — sekrety tylko w `.env` / na serwerze, nigdy w repo.
6. **Rollback & troubleshooting** — co zrobić przy błędzie logowania FTPS, złym katalogu domeny, cache przeglądarki, błędach buildu (proxy/SSL z DEVELOPMENT.md).

### 6. Istniejące docs
- `README.md` i `DEVELOPMENT.md` **zostają bez zmian**; w każdym dodaję jedną linijkę odsyłającą do `DEPLOY.md` jako głównego runbooka. Bez przepisywania działającej treści.

---

## Kryteria sukcesu
1. `npm run deploy` (po jednorazowym `.env`) buduje stronę i wgrywa `out/` na home.pl bez ręcznego klikania w FTP.
2. Strona otwiera się pod kupioną domeną.
3. Deploy **nie kasuje** zdalnych plików spoza `out/` (weryfikowalne: plik dodany ręcznie na serwerze przetrwa deploy bez `--clean`).
4. `DEPLOY.md` pozwala osobie nietechnicznej nanieść typową zmianę (tekst/zdjęcie) i opublikować ją samodzielnie.
5. Sekrety FTP nie trafiają do repo (`.env` w `.gitignore`, w repo tylko `.env.example`).

---

## Otwarte kwestie (do potwierdzenia w trakcie setupu)
- Dokładny katalog docelowy domeny w home.pl (`public_html` vs katalog per-domena) — ustalimy przy zakładaniu FTP; stąd `FTP_REMOTE_DIR` konfigurowalne.
- Czy pakiet hostingowy wspiera FTPS na porcie 21 z `AUTH TLS` (standard home.pl) — fallback na FTP przez `FTP_SECURE=false`.
