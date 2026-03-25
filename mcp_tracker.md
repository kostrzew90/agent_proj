# MCP Tracker - Phone & Email OSINT Verification

## Project Overview

MCP Server do weryfikacji numerów telefonów i adresów email przy użyciu narzędzi OSINT, inspirowany [ClarityCheck](https://claritycheck.com/pl). Dostępny jako tool w OpenWebUI.

**Status**: W pełni funkcjonalny (Faza 1 + 2 + 3 zrealizowane)
**Data utworzenia**: 2026-02-02
**Ostatnia aktualizacja**: 2026-02-03
**Wersja**: 0.4

---

## Podsumowanie (TL;DR)

### Co to jest?
Lokalne narzędzie OSINT do weryfikacji numerów telefonów, adresów email i nazw użytkowników. Sprawdza obecność w komunikatorach, social media, portalach randkowych i bazach wycieków.

### Kluczowe możliwości

| Typ sprawdzenia | Źródła | Pokrycie |
|-----------------|--------|----------|
| **Numer telefonu** | phonenumbers, Phoneinfoga, WhatsApp, Telegram, Viber, ignorant | Operator, kraj + 6 platform |
| **Email** | Holehe, HIBP, Gravatar, Maigret | 120+ serwisów + wycieki |
| **Username** | Maigret | **3000+ serwisów** |

### Główne funkcje
- ✅ **Auto-detect** - automatyczne rozpoznanie typu (phone/email/username)
- ✅ **Messenger check** - WhatsApp, Telegram, Viber, Signal
- ✅ **Platform check** - Amazon, Instagram, Snapchat (via ignorant)
- ✅ **Username OSINT** - 3000+ serwisów via Maigret (social, dating, gaming, professional)
- ✅ **Risk scoring** - automatyczna kategoryzacja LOW/MEDIUM/HIGH/CRITICAL
- ✅ **Historia** - wszystkie sprawdzenia zapisywane w PostgreSQL

### Szybki start
```bash
# Uruchom
docker-compose up -d osint-tracker

# Sprawdź numer telefonu
curl -X POST http://localhost:8766/osint/check \
  -H "Content-Type: application/json" \
  -d '{"input": "+48123456789"}'

# Sprawdź email
curl -X POST http://localhost:8766/osint/check \
  -H "Content-Type: application/json" \
  -d '{"input": "test@example.com"}'

# Sprawdź username (3000+ serwisów)
curl -X POST http://localhost:8766/osint/check/username \
  -H "Content-Type: application/json" \
  -d '{"username": "johndoe"}'
```

### Przykładowy wynik (telefon)
```
+48 502 745 006 → Poland, Orange
├── WhatsApp:  ✅ Zarejestrowany
├── Viber:     ✅ Zarejestrowany
├── Instagram: ✅ Konto powiązane
├── Telegram:  ❌ Wymaga API
├── Amazon:    ❌ Brak konta
└── Risk:      🟢 LOW
```

### Stack technologiczny
- **Backend**: Python 3.12 + Flask
- **OSINT tools**: Holehe, Maigret, ignorant, Phoneinfoga
- **Database**: PostgreSQL (pgvector)
- **Deployment**: Docker Compose
- **Port**: 8766

---

## 1. Wymagania biznesowe

### 1.1 Cele projektu
| Cel | Opis |
|-----|------|
| Weryfikacja kontrahentów | Sprawdzanie wiarygodności firm/osób przed współpracą |
| Anti-fraud | Wykrywanie potencjalnych oszustów i fałszywych tożsamości |
| Due diligence | Dogłębna analiza przed inwestycją lub zatrudnieniem |
| Osobiste OSINT | Sprawdzanie osób z życia prywatnego (np. randki online) |

### 1.2 Użytkownicy
- **Docelowy użytkownik**: Tylko właściciel (single user)
- **Poziom techniczny**: Zaawansowany
- **Interface**: OpenWebUI jako frontend

### 1.3 Częstotliwość użycia
- **Przewidywana**: Sporadycznie (kilka sprawdzeń tygodniowo)
- **Implikacje**: Brak potrzeby agresywnego cachowania, prostsze limity

---

## 2. Architektura techniczna

### 2.1 Stack technologiczny (aktualizacja 2026-02-03)
```
┌─────────────────────────────────────────────────────────────────┐
│                        OpenWebUI                                 │
│                     (localhost:3000)                             │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP API (OpenAPI 3.1)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     MCP OSINT Server                             │
│                   (osint-tracker:8766)                           │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ Phone        │  │ Email        │  │ Username     │           │
│  │ Checker      │  │ Checker      │  │ Checker      │           │
│  │              │  │              │  │ (Maigret)    │           │
│  │ • phonenums  │  │ • Holehe     │  │              │           │
│  │ • Phoneinfoga│  │ • HIBP       │  │ • 3000+      │           │
│  │ • ignorant   │  │ • Gravatar   │  │   serwisów   │           │
│  │ • messengers │  │ • Maigret    │  │              │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Messengers  │    │  Platforms   │    │   External   │
│              │    │  (ignorant)  │    │     APIs     │
│ • WhatsApp   │    │              │    │              │
│ • Telegram   │    │ • Amazon     │    │ • NumVerify  │
│ • Viber      │    │ • Instagram  │    │ • HIBP       │
│ • Signal     │    │ • Snapchat   │    │ • Hunter.io  │
└──────────────┘    └──────────────┘    └──────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       PostgreSQL                                 │
│                    (ai-postgres:5432)                            │
│  ┌─────────────────────┐  ┌─────────────────────┐               │
│  │ osint_checks        │  │ osint_sources       │               │
│  │ (główne wyniki)     │  │ (szczegóły źródeł)  │               │
│  └─────────────────────┘  └─────────────────────┘               │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Integracja z Docker Compose
Serwis aktywny w `docker-compose.yml`:
- Port: **8766**
- Network: Wspólna sieć z OpenWebUI i PostgreSQL
- Volumes: Brak (stateless, dane w PostgreSQL)

---

## 3. Zaimplementowane źródła danych OSINT

### 3.1 Numery telefonów

| Źródło | Typ | Status | Informacje |
|--------|-----|--------|------------|
| **phonenumbers** | Library | ✅ Aktywne | Walidacja, kraj, operator |
| **Phoneinfoga** | CLI | ✅ Aktywne | Footprinting, carrier |
| **NumVerify API** | Freemium | ⚙️ Wymaga klucza | Szczegółowa walidacja |
| **WhatsApp** | HTTP check | ✅ Aktywne | Czy numer zarejestrowany |
| **Telegram** | HTTP check | ✅ Aktywne | Podstawowe sprawdzenie |
| **Viber** | HTTP check | ✅ Aktywne | Czy numer zarejestrowany |
| **Signal** | Info only | ✅ Aktywne | Brak publicznego API |
| **ignorant (Amazon)** | CLI | ✅ Aktywne | Konto powiązane z numerem |
| **ignorant (Instagram)** | CLI | ✅ Aktywne | Konto powiązane z numerem |
| **ignorant (Snapchat)** | CLI | ✅ Aktywne | Konto powiązane z numerem |

### 3.2 Adresy email

| Źródło | Typ | Status | Informacje |
|--------|-----|--------|------------|
| **Holehe** | CLI | ✅ Aktywne | 120+ serwisów, rejestracje |
| **Have I Been Pwned** | API | ✅ Aktywne | Wycieki danych |
| **Gravatar** | API | ✅ Aktywne | Avatar, powiązane konta |
| **Maigret** | CLI | ✅ Aktywne | 3000+ serwisów via username |

### 3.3 Username (Maigret - 3000+ serwisów)

| Kategoria | Przykłady serwisów |
|-----------|-------------------|
| **Social Media** | Instagram, Facebook, Twitter, TikTok, VK, Twitch |
| **Dating** | Tinder, Bumble, Badoo, OkCupid |
| **Professional** | GitHub, LinkedIn, Behance, Dribbble, Kaggle |
| **Gaming** | Steam, Chess.com, Lichess, Roblox, OP.GG |
| **Other** | 2900+ innych serwisów |

---

## 4. API Endpoints

### 4.1 Dostępne endpointy

| Endpoint | Method | Opis | Status |
|----------|--------|------|--------|
| `/osint/check` | POST | Główne sprawdzenie (auto-detect type) | ✅ |
| `/osint/check/username` | POST | Sprawdzenie username (Maigret) | ✅ |
| `/osint/history` | POST | Historia sprawdzeń dla input | ✅ |
| `/osint/list` | GET | Lista wszystkich sprawdzeń | ✅ |
| `/osint/details/<id>` | GET | Szczegóły sprawdzenia | ✅ |
| `/health` | GET | Health check | ✅ |
| `/openapi.json` | GET | OpenAPI spec dla OpenWebUI | ✅ |

### 4.2 Przykładowy wynik (prawdziwy test)

**POST /osint/check** z `{"input": "+48502745006"}`

```json
{
  "id": 6,
  "input": "+48502745006",
  "type": "phone",
  "normalized": "+48502745006",
  "risk_category": "LOW",
  "risk_factors": [
    "Komunikatory: Whatsapp, Viber",
    "Konta powiązane: Instagram",
    "Minimalne czerwone flagi (4 źródeł)"
  ],
  "sources_checked": 9,
  "sources_found": 4,
  "duration_ms": 4379,
  "timestamp": "2026-02-03T13:02:19.894001"
}
```

**Wyniki szczegółowe:**

| Źródło | Status | Szczegóły |
|--------|--------|-----------|
| phonenumbers | ✅ | Polska, Orange |
| WhatsApp | ✅ | Zarejestrowany |
| Viber | ✅ | Zarejestrowany |
| Instagram | ✅ | **Konto powiązane z numerem** |
| Telegram | ❌ | Wymaga API |
| Amazon | ❌ | Brak konta |
| Snapchat | ⚠️ | Rate limited |

---

## 5. Struktura projektu

```
mcp-servers/osint-tracker/
├── Dockerfile              # Python 3.12 + narzędzia OSINT
├── requirements.txt        # Zależności Python
├── checkers.py            # Główna logika checkerów
│   ├── Email checkers     # Holehe, HIBP, Gravatar
│   ├── Phone checkers     # Phoneinfoga, NumVerify, phonenumbers
│   ├── Messenger checkers # WhatsApp, Telegram, Viber, Signal
│   ├── Platform checkers  # ignorant (Amazon, Instagram, Snapchat)
│   ├── Username checkers  # Maigret (3000+ serwisów)
│   └── Risk scoring       # Kalkulacja kategorii ryzyka
├── database.py            # PostgreSQL operations
├── http_server.py         # Flask API server
├── formatter.py           # Markdown output formatter
└── scripts/               # Helper scripts
```

---

## 6. Zainstalowane narzędzia OSINT

### 6.1 W kontenerze Docker

| Narzędzie | Wersja | Instalacja | Użycie |
|-----------|--------|------------|--------|
| **Holehe** | 1.61 | pip | Email → 120+ serwisów |
| **Maigret** | 0.5.0 | pip | Username → 3000+ serwisów |
| **ignorant** | 1.2 | pip | Phone → Amazon, Instagram, Snapchat |
| **Phoneinfoga** | latest | binary | Phone footprinting |
| **phonenumbers** | 9.0.22 | pip | Phone parsing & validation |

### 6.2 Zewnętrzne API (opcjonalne)

| API | Status | Konfiguracja |
|-----|--------|--------------|
| NumVerify | ⚙️ Opcjonalne | `NUMVERIFY_API_KEY` |
| HIBP | ✅ Free tier | `HIBP_API_KEY` (opcjonalne) |
| Hunter.io | ⚙️ Opcjonalne | `HUNTER_API_KEY` |

---

## 7. Risk Scoring

### 7.1 Kategorie ryzyka

| Kategoria | Punkty | Opis |
|-----------|--------|------|
| **LOW** | 0-2 | Minimalne czerwone flagi |
| **MEDIUM** | 3-5 | Pewne wątpliwości, wymaga uwagi |
| **HIGH** | 6-8 | Znaczące ryzyko, zachować ostrożność |
| **CRITICAL** | 9+ | Bardzo wysokie ryzyko, unikać kontaktu |

### 7.2 Czynniki ryzyka

| Czynnik | Punkty | Źródło |
|---------|--------|--------|
| Email w wycieku danych | +1 | HIBP |
| Email w >5 wyciekach | +3 | HIBP |
| Konto na portalu randkowym | +1-2 | Maigret, Holehe |
| Konta na >3 portalach randkowych | +3 | Maigret |
| Nietypowo dużo kont (>50) | +2 | Maigret |
| Brak w komunikatorach | +1 | Messenger checks |
| Powiązane konta (Instagram, etc.) | info | ignorant |

---

## 8. Konfiguracja

### 8.1 Docker Compose (aktywne)

```yaml
osint-tracker:
  build:
    context: ./mcp-servers/osint-tracker
    dockerfile: Dockerfile
  container_name: osint-tracker
  restart: unless-stopped
  ports:
    - "8766:8766"
  depends_on:
    postgres:
      condition: service_healthy
  environment:
    - OSINT_DB_HOST=postgres
    - OSINT_DB_PORT=5432
    - OSINT_DB_USER=n8n
    - OSINT_DB_PASSWORD=n8npass
    - OSINT_DB_NAME=n8n
    - NUMVERIFY_API_KEY=${NUMVERIFY_API_KEY:-}
    - HIBP_API_KEY=${HIBP_API_KEY:-}
    - TZ=Europe/Warsaw
```

### 8.2 requirements.txt

```
flask>=3.0.0
flask-cors>=6.0.0
psycopg2-binary>=2.9.9
requests>=2.31.0
httpx>=0.27.0
holehe>=1.61
maigret>=0.4.4
ignorant>=0.0.12
phonenumbers>=8.13.0
aiohttp>=3.9.0
python-dotenv>=1.0.0
```

---

## 9. Implementacja - Status

### Faza 1: MVP ✅ ZREALIZOWANA
- [x] Struktura projektu i Dockerfile
- [x] Schemat bazy danych
- [x] OpenAPI endpoint `/openapi.json`
- [x] Sprawdzenie email (Holehe + HIBP + Gravatar)
- [x] Sprawdzenie phone (Phoneinfoga + phonenumbers)
- [x] Risk scoring
- [x] Integracja z docker-compose.yml

### Faza 2: Maigret Integration ✅ ZREALIZOWANA
- [x] Maigret wrapper w `checkers.py`
- [x] Username derivation z email
- [x] Kategoryzacja wyników (social, dating, professional, gaming)
- [x] Nowy endpoint `/osint/check/username`
- [x] Risk scoring dla Maigret (3000+ serwisów)

### Faza 3: Messenger & Platform Checks ✅ ZREALIZOWANA
- [x] WhatsApp check (wa.me lookup)
- [x] Telegram check (web lookup)
- [x] Viber check
- [x] Signal info
- [x] ignorant integration (Amazon, Instagram, Snapchat)
- [x] Formatter dla nowych źródeł

### Faza 4: Rozszerzenia (opcjonalne, przyszłe)
- [ ] Google dorking
- [ ] Telegram API (pełna weryfikacja z credentials)
- [ ] Historia i porównania
- [ ] Eksport raportów PDF
- [ ] Webhook notifications
- [ ] Epieos API integration (płatne)

---

## 10. Znane ograniczenia

| Ograniczenie | Opis | Mitygacja |
|--------------|------|-----------|
| **Rate limiting** | Ignorant (Snapchat) może być rate limited | Retry logic, zmiana IP |
| **Telegram** | Pełna weryfikacja wymaga API credentials | Podstawowy web check działa |
| **Signal** | Brak publicznego API (privacy by design) | Tylko informacja o linku |
| **Facebook/Google** | Wymagają zaawansowanej weryfikacji | Placeholder w wynikach |

---

## 11. Changelog

| Data | Wersja | Zmiany |
|------|--------|--------|
| 2026-02-03 | **0.4** | **Messenger checkers** (WhatsApp, Telegram, Viber, Signal) + **ignorant** (Amazon, Instagram, Snapchat) |
| 2026-02-03 | 0.3 | Maigret integration: 3000+ serwisów, username check |
| 2026-02-02 | 0.2 | MVP: checkers.py, database.py, http_server.py, formatter.py |
| 2026-02-02 | 0.1 | Inicjalna specyfikacja |

---

## 12. Uruchomienie

```bash
# Start serwisu
docker-compose up -d osint-tracker

# Sprawdź logi
docker logs osint-tracker

# Test API
curl -X POST http://localhost:8766/osint/check \
  -H "Content-Type: application/json" \
  -d '{"input": "+48123456789"}'

# Test username (Maigret)
curl -X POST http://localhost:8766/osint/check/username \
  -H "Content-Type: application/json" \
  -d '{"username": "johndoe"}'
```

---

## 13. Następne kroki (opcjonalne)

1. **Telegram API** - dodać pełną weryfikację z app_id/app_hash
2. **Epieos** - rozważyć płatną integrację (€30/mies) dla phone→email matching
3. **Google Dorking** - automatyczne wyszukiwanie numeru w internecie
4. **Eksport PDF** - generowanie raportów do pobrania
5. **OpenWebUI Tool** - zarejestrować jako oficjalny tool w OpenWebUI
