# DEPLOY.md — wdrażanie i aktualizacja strony kancelarii

Główny runbook (źródło prawdy) dla strony **borzewski-kancelaria.com** na hostingu **home.pl**.
Opisuje realny, sprawdzony proces: jak wgrać stronę i jak ją aktualizować o zmiany przygotowane lokalnie.

> Skrócone „jak dodać zdjęcie / zmienić tekst" jest w `README.md`, a lokalne uruchomienie dev w `DEVELOPMENT.md`. Ten plik to pełny proces deployu + pułapki.

---

## 1. Jak to działa (architektura w 30 sekund)

- Strona to **Next.js 14 w trybie `output: 'export'`** → `npm run build` generuje statyczny katalog **`out/`** (czysty HTML/CSS/JS, bez Node na serwerze).
- `out/` wgrywamy przez **FTPS** do katalogu domeny na home.pl: **`/kancelaria_html`**.
- Domena `borzewski-kancelaria.com` jest w panelu home.pl przypięta do tego katalogu (patrz §2.2).
- Jedyny element serwerowy to **formularz kontaktowy PHP** (`contact.php`) — uruchamiany osobno, patrz §5.

Deploy robi skrypt **`scripts/deploy.mjs`** (Node + `basic-ftp`), czytający dane logowania z **`.env`** (poza repo).

---

## 2. Setup jednorazowy

Robisz to **raz**. Potem każda aktualizacja to już tylko §4.

### 2.1. Konto FTP (panel home.pl)
1. Panel home.pl → **Serwer WWW / Konta FTP** → **Dodaj konto FTP**.
2. Zanotuj: **host** (np. `serwerXXXXXXX.hosting-home.pl`), **login**, **hasło**, **katalog domowy** (u nas `kancelaria_html`).
3. Port **21**, protokół **FTPS** (szyfrowane).

### 2.2. Przypięcie domeny do katalogu (panel home.pl)
Panel → **Domeny → [borzewski-kancelaria.com] → Edytuj / Ustawienia WWW → Lokalizacja www**:
- zaznacz **„Podkatalog bez separacji serwisu"**,
- w polu podkatalogu wpisz **`kancelaria_html`**,
- zapisz.

To sprawia, że domena serwuje pliki z `/kancelaria_html` (tam gdzie wgrywa deploy).

### 2.3. Certyfikat SSL (HTTPS)
Panel → **Certyfikaty SSL** → dla domeny włącz **bezpłatny Let's Encrypt** (obejmij `borzewski-kancelaria.com` i `www.`).
`.htaccess` **wymusza HTTPS** (redirect + HSTS), więc bez ważnego certyfikatu strona pokaże ostrzeżenie — cert musi być aktywny.

### 2.4. Plik `.env` (lokalnie, dane FTP)
```bash
cd Arturborzewski
cp .env.example .env
```
Uzupełnij `.env` realnymi danymi z panelu:
```
FTP_HOST=serwerXXXXXXX.hosting-home.pl
FTP_USER=deploy@borzewski-kancelaria.com
FTP_PASSWORD="haslo-z-panelu"        # patrz PUŁAPKA niżej
FTP_PORT=21
FTP_SECURE=true                      # FTPS
FTP_REMOTE_DIR=/kancelaria_html
```

> **⚠️ PUŁAPKA — hasło ze znakami specjalnymi.** Node `--env-file` traktuje `#` jako początek komentarza i **utnie** hasło. Jeśli hasło zawiera `#`, `!`, spacje itp. — **weź je w cudzysłowy**: `FTP_PASSWORD="Pa#ss!123"`. Objaw bez cudzysłowów: FTP łączy się, ale zwraca `530 Login authentication failed`.

`.env` jest w `.gitignore` — **nigdy nie trafia do repo**. W repo jest tylko `.env.example` (placeholdery).

---

## 3. Pierwszy deploy

```bash
cd Arturborzewski
npm install                                    # tylko raz
npm run build                                  # generuje out/
node --env-file=.env scripts/deploy.mjs        # wgrywa out/ na FTPS
```
Sukces kończy się linią `✅ Wgrano N plików na ...`. Wejdź na https://borzewski-kancelaria.com i sprawdź (Ctrl+F5 dla pewności, żeby ominąć cache).

---

## 4. Workflow aktualizacji (rdzeń)

**Zasada: edytujesz lokalnie → build → deploy → live.** Zawsze te same 2 komendy na końcu:
```bash
npm run build
node --env-file=.env scripts/deploy.mjs
```

Co zwykle zmieniasz:

| Chcę zmienić | Plik | Uwaga |
|--------------|------|-------|
| Teksty, dane kontaktowe, mail, telefon, adres | `content/site.json` | edytujesz wartości JSON |
| Listę specjalizacji (karty) | `content/site.json` → `specjalizacje[]` | dodaj/edytuj obiekt `{ slug, nazwa, opis }` |
| Adres domeny (canonical/SEO) | `content/site.json` → `kancelaria.url` | zasila canonical + metadataBase + sitemap |
| Zdjęcia / logo | `public/images/` | build sam optymalizuje do WebP (`prebuild`) |
| Układ / kod strony | `app/page.tsx`, `app/*/page.tsx`, komponenty `app/*.tsx` | |
| Nagłówki, cache, CSP, redirecty | `public/.htaccess` | patrz PUŁAPKA CSP w §6 |

Po każdej zmianie: `npm run build` → `node --env-file=.env scripts/deploy.mjs`.

> Deploy jest **nie-destrukcyjny**: nadpisuje pliki, ale **nie kasuje** zdalnych plików nieobecnych lokalnie (chroni przyszły `vendor/` PHPMailera i logi formularza). Zmiana bundli Next tworzy nowe pliki w `_next/` (stare zostają jako nieszkodliwe sieroty).

---

## 5. Formularz kontaktowy (etap „później", jeszcze nieaktywny)

Formularz (`public/contact.php`) wysyła maile przez SMTP home.pl. Do uruchomienia potrzeba:
1. **Skrzynka e-mail** kancelarii w home.pl (login = mail, np. `Kancelaria@borzewski-kancelaria.com`).
2. W `public/contact.php` uzupełnij:
   - `$mail->Username` — login skrzynki (już wpisany mail kancelarii),
   - `$mail->Password` — **hasło skrzynki** (obecnie placeholder `SMTP_PASSWORD`),
   - `$mail->addAddress(...)` — dokąd trafiają zapytania (już ustawione na mail kancelarii).
3. **PHPMailer** na serwerze: przez SSH `composer install --no-dev` (w katalogu z `composer.json`) lub wgrać ręcznie do `public/vendor/`.
4. **Cloudflare Turnstile**: utwórz widget, wstaw `secret` do `contact.php` i `sitekey` przed buildem (`NEXT_PUBLIC_TURNSTILE_SITEKEY`) lub w `app/ContactForm.tsx`.

> Przy deployu formularza **nie używaj** trybu kasującego — `vendor/` żyje tylko na serwerze i deploy go nie dotyka (i dobrze).

---

## 6. Pułapki i troubleshooting (realne, napotkane)

- **`530 Login authentication failed` mimo dobrych danych** → hasło ucięte na `#` przez parser `.env`. Ujmij hasło w cudzysłowy (§2.4).
- **Deploy zrywa się w połowie: `Server sent FIN packet unexpectedly`** → home.pl ubija sesję FTPS po kilkunastu plikach. Skrypt sam to obsługuje: **reconnect z kontynuacją** + proaktywny reconnect co 8 plików. Jeśli i tak pada — uruchom deploy ponownie (jest idempotentny, dokończy resztę).
- **Deploy staje na pliku 0-bajtowym (`.gitkeep`)** → puste pliki wywalają FTPS home.pl. Skrypt **automatycznie pomija pliki 0-bajtowe** (i tak są bez znaczenia na serwerze).
- **Strona działa, ale BRAK ANIMACJI / sekcje „martwe"** → to CSP. Next wstrzykuje inline'owe skrypty hydratacji; nagłówek `Content-Security-Policy` w `.htaccess` **musi** mieć `'unsafe-inline'` w `script-src`. Bez tego React się nie hydratuje → framer-motion nie startuje → sekcje zostają na `opacity:0`.
- **Zła domena w canonical / sitemap** → wszystko bierze się z `content/site.json` → `kancelaria.url`. Dodatkowo sprawdź `public/sitemap.xml`, `public/robots.txt`, `public/.well-known/security.txt` (mają domenę wpisaną na sztywno).
- **Build wywala błąd SSL przy pobieraniu Google Fonts** → tylko na maszynie za firmowym proxy przechwytującym SSL. Obejście: `NODE_TLS_REJECT_UNAUTHORIZED=0 npm run build`. Na czystej sieci niepotrzebne. **Nie** wpisuj tego na stałe.
- **Zmiany niewidoczne po deployu** → cache przeglądarki. Twardy refresh **Ctrl+F5**. Pliki `_next/*` mają `Cache-Control: immutable` (1 rok), ale ich nazwy zmieniają się przy każdym buildzie, więc realnie cache nie przeszkadza; problem dotyczy głównie `index.html`.

---

## 7. Diagnostyka połączenia FTP (opcjonalnie)

Zanim zrobisz pełny deploy na nowym koncie/haśle, możesz sprawdzić samo połączenie:
```bash
node --env-file=.env scripts/deploy-test.mjs
```
Skrypt łączy się przez FTPS, wgrywa 1 plik testowy, listuje katalog i **kasuje** plik. Potwierdza: połączenie, hasło, właściwy katalog, prawo zapisu. Nic trwałego nie zostawia.

---

## 8. Bezpieczeństwo

- Sekrety (hasło FTP, hasło SMTP, secret Turnstile) **tylko** w `.env` lub bezpośrednio na serwerze — nigdy w repo.
- `.env` jest w `.gitignore`. W repo jest wyłącznie `.env.example` z placeholderami.
- Jeśli hasło kiedykolwiek pojawiło się w commitcie/logu/czacie — **zresetuj je** w panelu home.pl i podmień w `.env`.

---

## 9. Pliki związane z deployem

| Plik | Rola |
|------|------|
| `scripts/deploy.mjs` | właściwy deploy (build osobno) — upload `out/` przez FTPS z reconnectem |
| `scripts/deploy-test.mjs` | opcjonalna diagnostyka połączenia FTPS |
| `.env.example` | szablon konfiguracji FTP (wersjonowany) |
| `.env` | realne dane FTP (poza repo) |
| `public/.htaccess` | HTTPS redirect, nagłówki bezpieczeństwa, **CSP**, cache |
| `content/site.json` | treści, dane kontaktowe, mail, specjalizacje, `url` (domena) |
