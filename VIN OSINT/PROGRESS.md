# VINhunter — Progress Tracker

**CZYTAJ TEN PLIK NA POCZATKU KAZDEJ SESJI**

## Status projektu

| Faza | Status | Opis |
|------|--------|------|
| Wywiad / specyfikacja | DONE | Pełny wywiad, spec w VIN_osint.MD |
| Inicjalizacja projektu | DONE | Docker, backend FastAPI, frontend Vue 3 |
| Pluginy MVP | DONE | 13 pluginów zarejestrowanych, stack działa |
| Weryfikacja pluginów | DONE | Przetestowane, 6/13 zwraca dane, reszta Cloudflare/no_data |
| Pełny skan UI | DONE | Skan działa end-to-end, statusy poprawne |
| Optymalizacja sesja 4 | DONE | CF pluginy wyłączone, timeouty skrócone, nhtsa_safety dodany |
| Cloudflare bypass | DONE (failed) | Firefox + playwright-stealth nie przeszły CF |
| Nowe źródła API | IN PROGRESS | autoref + vincario pluginy napisane, WYMAGA REBUILD+TEST |

## Aktualny stan (2026-03-01, koniec sesji 4)

### Stack DZIAŁA
```bash
cd "VIN OSINT/vinhunter"
docker compose up -d --build
```
- Frontend: http://localhost:3010
- Backend API: http://localhost:8200
- API docs: http://localhost:8200/docs
- DB: localhost:5436

### 16 pluginów zarejestrowanych (ALL auto-discovered)

| Plugin | Kategoria | Metoda | Status |
|--------|-----------|--------|--------|
| `nhtsa` | vin_decode | REST API (Extended) | DZIAŁA — 28 pól |
| `vininfo_local` | vin_decode | offline Python | DZIAŁA |
| `vindecoderz` | vin_decode | Playwright Firefox+stealth | **WYŁĄCZONY** — Cloudflare |
| `autoref` | vin_decode | REST API (httpx) | **NOWY** — wymaga AUTOREF_API_KEY |
| `vincario` | vin_decode | REST API (httpx) | **NOWY** — wymaga VINCARIO_API_KEY+SECRET |
| `nhtsa_recalls` | damage | REST API | DZIAŁA |
| `nhtsa_complaints` | damage | REST API | DZIAŁA |
| `nhtsa_safety` | damage | REST API | **NOWY** — DZIAŁA, gwiazdki NCAP |
| `bidfax` | damage | Playwright Firefox+stealth | **WYŁĄCZONY** — Cloudflare |
| `statvin` | damage | Playwright Firefox+stealth | **WYŁĄCZONY** — Cloudflare |
| `autoastat` | damage | Playwright Firefox+stealth | **WYŁĄCZONY** — Cloudflare |
| `nl_rdw` | registry | REST API (httpx) | DZIAŁA (tylko NL tablice) |
| `pl_historia` | registry | httpx + brute-force | Wymaga tablicy + daty |
| `uk_mot` | registry | REST API | Wymaga UK_MOT_API_KEY |
| `google_images` | photo_osint | Playwright | **WYŁĄCZONY** — Google blokuje |
| `yandex_images` | photo_osint | Playwright | DZIAŁA (czasem CAPTCHA) |

### Zmiany w sesji 4

#### Optymalizacja
- Wyłączone pluginy: google_images, vindecoderz, bidfax, autoastat, statvin (enabled=False)
- Skrócone timeouty na CF pluginach (goto 10s, CF wait 5s) — potem zmienione na Firefox 20s+8s
- Skan skrócony z ~36s do ~22s

#### Nowy plugin: nhtsa_safety
- NHTSA Safety Ratings (NCAP crash test stars)
- 2-krokowy: decode VIN → get make/model/year → query SafetyRatings API
- Endpoint: `https://api.nhtsa.gov/SafetyRatings/`
- Zwraca: overall rating, frontal/side/rollover crash stars, rollover probability
- BMW 328i 2011: Rollover 5★, overall Not Rated (brak pełnych testów dla tego rocznika)
- Haiku naprawił URL z one.nhtsa.gov na api.nhtsa.gov + dodał User-Agent header

#### Cloudflare bypass — PRÓBY (wszystkie nieudane)
1. Firefox zamiast Chromium — nadal blocked
2. Firefox + playwright-stealth (pip) — nadal blocked
3. Wniosek: CF wykrywa headless browser niezależnie od przeglądarki/stealth
4. Decyzja: odpuścić CF pluginy, skupić się na API

#### Nowe pluginy API (napisane, NIE PRZETESTOWANE)
- `autoref` — AutoRef.eu API, wymaga AUTOREF_API_KEY (50 free/month, €20/5K)
- `vincario` — Vincario API, wymaga VINCARIO_API_KEY + VINCARIO_SECRET_KEY ($0.25/decode)
- Oba auto-disable bez kluczy (property enabled zwraca bool(key))
- Klucze dodane do config.py i .env.example

### Wynik skanu po optymalizacji (VIN: WBAPH5C55BA436952)
- **5 done**: nhtsa, vininfo_local, nhtsa_recalls, nhtsa_complaints, nhtsa_safety
- **3 no_data**: nl_rdw, pl_historia, uk_mot
- **1 error**: yandex_images (CAPTCHA)
- **6 wyłączonych**: bidfax, autoastat, statvin, vindecoderz, google_images + (autoref/vincario bez kluczy)
- Czas skanu: ~22s
- Status: done_with_errors

### Zmiany w plikach (sesja 4)
- `backend/Dockerfile` — dodany Firefox: `playwright install --with-deps chromium firefox`
- `backend/requirements.txt` — dodany `playwright-stealth>=2.0.0`
- `backend/core/config.py` — dodane: autoref_api_key, vincario_api_key, vincario_secret_key
- `backend/plugins/damage/nhtsa_safety.py` — NOWY plugin
- `backend/plugins/vin_decode/autoref.py` — NOWY plugin
- `backend/plugins/vin_decode/vincario.py` — NOWY plugin
- `backend/plugins/damage/bidfax.py` — Firefox + stealth + enabled=False
- `backend/plugins/damage/autoastat.py` — Firefox + stealth + enabled=False
- `backend/plugins/damage/statvin.py` — Firefox + stealth + enabled=False
- `backend/plugins/vin_decode/vindecoderz.py` — Firefox + stealth + enabled=False
- `backend/plugins/osint_photo/google_images.py` — enabled=False
- `.env.example` — dodane API key placeholders
- Import stealth zmieniony przez Haiku: `from playwright_stealth.stealth import Stealth` + `stealth = Stealth(); await stealth.apply_stealth_async(page)`

## Co dalej (następna sesja)

### PRIORYTET 1: Rebuild i test nowych pluginów ⚠️
- `docker compose up -d --build vinhunter-backend` — WYMAGA REBUILD
- Sprawdzić czy autoref i vincario się ładują bez import errors
- Jeśli masz klucze API — dodać do .env i przetestować

### PRIORYTET 2: Rejestracja API keys
- **AutoRef.eu** — zarejestruj na https://autoref.eu/en/contact (50 free/month)
- **Vincario** — zarejestruj na https://vincario.com ($0.25/decode)
- Dodaj klucze do `vinhunter/.env`

### PRIORYTET 3: UI/UX
- Przetestować generowanie raportu HTML
- Sprawdzić WebSocket real-time updates w przeglądarce
- Dodać podsumowanie skanu (ile źródeł done/error/no_data)

### Znane problemy
- Cloudflare blokuje wszystko (Firefox+stealth nie pomaga) — pluginy wyłączone
- `pl_historia` wymaga tablicy + daty — nie działa z samym VIN
- `uk_mot` wymaga API key
- yandex_images — czasem CAPTCHA
- vininfo_local — `UnsupportedBrand` dla BMW

## Porty (faktyczne)
| Serwis | Port |
|--------|------|
| Frontend (Vue 3) | **3010** |
| Backend (FastAPI) | **8200** |
| PostgreSQL | **5436** |

## Pliki
- `VIN_osint.MD` — pełna specyfikacja techniczna
- `vin.md` — wstępny research
- `PROGRESS.md` — ten plik
- `vinhunter/` — kod projektu
