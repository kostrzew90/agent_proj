# VINhunter — Specyfikacja Techniczna

## 1. Cel projektu

Osobiste narzedzie OSINT do weryfikacji samochodow przed zakupem. Glowny problem: auta ~20-letnie importowane z roznych krajow EU — dane sa rozproszone po wielu rejestrach, sprzedawcy nie udostepniaja pelnych informacji, a jednej bazy obejmujacej cala Europe nie ma.

**VINhunter** odpytuje rownolegle wiele zrodel (rejestry, bazy szkod, archiwa ogloszen, wyszukiwarki obrazow) i prezentuje wyniki w jednym dashboardzie z real-time statusem kazdego zrodla.

### Kluczowe wymagania

- Wejscie: numer VIN (obowiazkowy) + opcjonalnie tablica rejestracyjna
- Rownolegle odpytywanie wielu zrodel z live statusem per zrodlo (WebSocket)
- Dekodowanie VIN z wielu zrodel (offline + NHTSA + producent)
- OSINT zdjeciowy: Google Images, Yandex, archiwa ogloszen, fora
- Bazy szkod/wypadkow: aukcje powypadkowe, rejestry publiczne
- Plugin system: kazde zrodlo = osobny adapter, latwo dodawac nowe
- Export raportu do HTML (self-contained lub z obrazkami)
- Reczne rozwiazywanie CAPTCHA (wizard wyswietla CAPTCHA w UI)
- Zero budzetu na platne API — tylko darmowe zrodla i scraping
- LLM: pominiete w MVP, zaplanowane na pozniej

---

## 2. Architektura

### 2.1 Stack technologiczny

| Warstwa | Technologia | Uzasadnienie |
|---------|-------------|--------------|
| Backend API | FastAPI (Python 3.11+) | Async, WebSocket natywnie, szybki, znany z innych projektow |
| Frontend | Vue 3 (Composition API) + Vite | Prostszy start niz React, intuicyjny template syntax, dobry wizard flow |
| Baza danych | PostgreSQL 16 | Sprawdzona, uzywa sie w innych projektach, port **5434** |
| Scraping | Crawlee (Python) + Playwright | Gotowy framework z anti-detekcja, headless browser, retry logic |
| Real-time | WebSocket (FastAPI native) | Live status kazdego zrodla podczas skanowania |
| Konteneryzacja | Docker Compose | Osobny stack, niezalezny od n8n i tradingu |
| Proxy | Brak na start | Dodane gdy pojawia sie bany; architektura gotowa na proxy rotation |

### 2.2 Diagram komponentow

```
                    +-------------------+
                    |   Vue 3 Frontend  |
                    |   (port 3000)     |
                    +--------+----------+
                             |
                        WebSocket + REST
                             |
                    +--------v----------+
                    |   FastAPI Backend  |
                    |   (port 8200)      |
                    +--------+----------+
                             |
              +--------------+--------------+
              |              |              |
     +--------v---+  +------v------+  +----v--------+
     | VIN Decoder |  | Scan Engine |  | Report Gen  |
     | (multi-src) |  | (parallel)  |  | (HTML)      |
     +-------------+  +------+------+  +-------------+
                             |
                    +--------v----------+
                    |  Plugin Manager   |
                    +--------+----------+
                             |
         +--------+----------+----------+--------+
         |        |          |          |        |
      +--v--+  +--v--+  +---v---+  +---v--+  +--v---+
      | PL  |  | UK  |  |  DE   |  | OSINT|  | ...  |
      | reg |  | MOT |  |  KBA  |  | foto |  |plugin|
      +-----+  +-----+  +-------+  +------+  +------+
```

### 2.3 Struktura katalogow

```
vinhunter/
├── docker-compose.yml
├── .env.example
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                    # FastAPI entry point
│   │
│   ├── api/
│   │   ├── routes/
│   │   │   ├── scan.py            # POST /scan, GET /scan/{id}/status (WebSocket)
│   │   │   ├── vin.py             # GET /vin/decode/{vin}
│   │   │   ├── reports.py         # GET /reports, GET /reports/{id}/download
│   │   │   └── plugins.py         # GET /plugins, POST /plugins/{name}/toggle
│   │   └── websocket.py           # WebSocket handler dla live scan status
│   │
│   ├── core/
│   │   ├── config.py              # Dataclass config z .env
│   │   ├── database.py            # PostgreSQL operations (asyncpg)
│   │   ├── scan_engine.py         # Orkiestracja rownoleglego skanowania
│   │   ├── vin_decoder.py         # Multi-source VIN decode + merge
│   │   ├── report_generator.py    # HTML report builder (Jinja2)
│   │   └── captcha_bridge.py      # CAPTCHA -> frontend -> user -> response
│   │
│   ├── plugins/
│   │   ├── base.py                # Abstrakcyjna klasa SourcePlugin
│   │   ├── registry.py            # Plugin discovery + management
│   │   │
│   │   ├── vin_decode/
│   │   │   ├── nhtsa.py           # NHTSA vPIC API (darmowe, oficjalne)
│   │   │   ├── vininfo_local.py   # Offline decode (vininfo lib)
│   │   │   └── manufacturer.py    # Scraping stron producentow (BMW, MB, VW)
│   │   │
│   │   ├── registries/
│   │   │   ├── pl_historia.py     # HistoriaPojazdu.gov.pl (CAPTCHA)
│   │   │   ├── uk_mot.py          # UK MOT History API (darmowe!)
│   │   │   ├── uk_dvla.py         # DVLA vehicle enquiry
│   │   │   ├── nl_rdw.py          # RDW Open Data (Holandia)
│   │   │   ├── fr_histovec.py     # Histovec (Francja)
│   │   │   ├── be_carpass.py      # Car-Pass (Belgia)
│   │   │   ├── de_kba.py          # KBA / TecDoc (Niemcy)
│   │   │   ├── ch_stva.py         # Szwajcaria rejestr
│   │   │   └── se_transportstyrelsen.py  # Szwecja
│   │   │
│   │   ├── damage/
│   │   │   ├── bidfax.py          # bidfax.info (agregator Copart/IAAI)
│   │   │   ├── statvin.py         # stat.vin (agregator aukcji)
│   │   │   └── poctr.py           # poctr.com
│   │   │
│   │   ├── osint_photo/
│   │   │   ├── google_images.py   # Google Images search po VIN/tablicy
│   │   │   ├── yandex_images.py   # Yandex (lepszy dla EU/RU zdjec)
│   │   │   ├── wayback.py         # Wayback Machine cached pages
│   │   │   └── forum_search.py    # Fora motoryzacyjne (szukaj VIN/tablicy)
│   │   │
│   │   └── ads_archive/
│   │       ├── otomoto.py         # OTOMOTO archiwa ogloszen
│   │       ├── mobile_de.py       # mobile.de historia ogloszen
│   │       └── autoscout24.py     # AutoScout24 archiwa
│   │
│   ├── templates/
│   │   ├── report_full.html       # Jinja2 template raportu (self-contained)
│   │   └── report_images.html     # Template z linkami do obrazkow
│   │
│   └── db-init/
│       └── init.sql               # Schema PostgreSQL
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── App.vue
│   │   ├── main.ts
│   │   ├── router/
│   │   │   └── index.ts           # Vue Router (/, /scan/:id, /reports)
│   │   ├── stores/
│   │   │   └── scan.ts            # Pinia store (scan state, WebSocket)
│   │   ├── composables/
│   │   │   ├── useWebSocket.ts    # WebSocket composable
│   │   │   └── useCaptcha.ts      # CAPTCHA dialog composable
│   │   ├── components/
│   │   │   ├── VinInput.vue       # Formularz wejsciowy (VIN + tablica)
│   │   │   ├── ScanDashboard.vue  # Glowny dashboard z statusami zrodel
│   │   │   ├── SourceCard.vue     # Karta pojedynczego zrodla (status + wyniki)
│   │   │   ├── CaptchaDialog.vue  # Modal do recznego rozwiazywania CAPTCHA
│   │   │   ├── VinDecoded.vue     # Wyniki dekodowania VIN
│   │   │   ├── PhotoGallery.vue   # Galeria znalezionych zdjec
│   │   │   └── ReportExport.vue   # Przycisk eksportu + opcje formatu
│   │   ├── views/
│   │   │   ├── HomeView.vue       # Strona glowna z VinInput
│   │   │   ├── ScanView.vue       # Widok aktywnego/zakonzczonego skanu
│   │   │   └── ReportsView.vue    # Lista wygenerowanych raportow
│   │   └── types/
│   │       └── index.ts           # TypeScript typy (ScanResult, SourceStatus, etc.)
│   └── public/
│       └── favicon.ico
│
└── proxy/                         # (przygotowane na przyszlosc)
    └── README.md                  # Instrukcja dodania proxy rotation
```

---

## 3. Plugin System

### 3.1 Interfejs bazowy

Kazdy plugin implementuje abstrakcyjna klase `SourcePlugin`:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class SourceCategory(Enum):
    VIN_DECODE = "vin_decode"
    REGISTRY = "registry"
    DAMAGE = "damage"
    PHOTO_OSINT = "photo_osint"
    ADS_ARCHIVE = "ads_archive"

class SourceStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    CAPTCHA_REQUIRED = "captcha_required"
    DONE = "done"
    ERROR = "error"
    NO_DATA = "no_data"

@dataclass
class PluginResult:
    source_name: str
    category: SourceCategory
    status: SourceStatus
    data: dict                    # Ustrukturyzowane wyniki
    raw_html: Optional[str]       # Surowy HTML (do debugowania)
    screenshots: list[str]        # Sciezki do zrzutow ekranu
    error_message: Optional[str]
    execution_time_ms: int

class SourcePlugin(ABC):
    """Bazowa klasa dla kazdego zrodla danych."""

    name: str                     # Unikalna nazwa (np. "uk_mot")
    display_name: str             # Nazwa wyswietlana (np. "UK MOT History")
    category: SourceCategory
    country: str                  # Kod kraju ISO (np. "GB", "PL", "DE")
    requires_captcha: bool = False
    requires_login: bool = False  # Jesli True — plugin jest pomijany (na start)
    enabled: bool = True

    @abstractmethod
    async def search_by_vin(self, vin: str) -> PluginResult:
        """Szukaj danych po numerze VIN."""
        ...

    async def search_by_plate(self, plate: str, country: str) -> PluginResult:
        """Opcjonalnie: szukaj po tablicy rejestracyjnej."""
        raise NotImplementedError(f"{self.name} nie obsluguje wyszukiwania po tablicy")

    async def resolve_captcha(self, captcha_image: bytes) -> str:
        """Wywolywane gdy requires_captcha=True. Deleguje do CaptchaBridge -> UI."""
        raise NotImplementedError
```

### 3.2 Plugin discovery

Pluginy sa automatycznie odkrywane przez skanowanie katalogu `plugins/`:

```python
# plugins/registry.py
import importlib
import pkgutil
from pathlib import Path

class PluginRegistry:
    def __init__(self):
        self.plugins: dict[str, SourcePlugin] = {}

    def discover(self):
        """Skanuj podkatalogi plugins/ i zarejestruj wszystkie klasy dziedziczace z SourcePlugin."""
        plugin_dir = Path(__file__).parent
        for subdir in ["vin_decode", "registries", "damage", "osint_photo", "ads_archive"]:
            package = f"plugins.{subdir}"
            path = plugin_dir / subdir
            for _, module_name, _ in pkgutil.iter_modules([str(path)]):
                module = importlib.import_module(f"{package}.{module_name}")
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, SourcePlugin) and attr is not SourcePlugin:
                        instance = attr()
                        if not instance.requires_login:  # Pomijamy zrodla wymagajace logowania
                            self.plugins[instance.name] = instance

    def get_enabled(self) -> list[SourcePlugin]:
        return [p for p in self.plugins.values() if p.enabled]

    def get_by_category(self, category: SourceCategory) -> list[SourcePlugin]:
        return [p for p in self.get_enabled() if p.category == category]
```

### 3.3 Dodawanie nowego pluginu

Aby dodac nowe zrodlo:

1. Utworz plik w odpowiednim podkatalogu `plugins/` (np. `plugins/registries/at_eurotax.py`)
2. Zaimplementuj klase dziedziczaca z `SourcePlugin`
3. Ustaw `name`, `display_name`, `category`, `country`
4. Zaimplementuj `search_by_vin()` (i opcjonalnie `search_by_plate()`)
5. Plugin zostanie automatycznie wykryty i zarejestrowany

---

## 4. Scan Engine — rownolegle skanowanie

### 4.1 Orkiestracja

```python
# core/scan_engine.py
import asyncio
from datetime import datetime

class ScanEngine:
    def __init__(self, plugin_registry: PluginRegistry, db: Database, ws_manager: WebSocketManager):
        self.registry = plugin_registry
        self.db = db
        self.ws = ws_manager

    async def run_scan(self, scan_id: str, vin: str, plate: Optional[str] = None):
        """Uruchom wszystkie pluginy rownolegle, streamuj statusy przez WebSocket."""
        plugins = self.registry.get_enabled()

        # Faza 1: VIN decode (musi byc pierwszy — inne pluginy moga potrzebowac marki/modelu)
        decode_plugins = [p for p in plugins if p.category == SourceCategory.VIN_DECODE]
        decode_results = await asyncio.gather(
            *[self._run_plugin(scan_id, p, vin, plate) for p in decode_plugins],
            return_exceptions=True
        )
        decoded_info = self._merge_vin_data(decode_results)

        # Faza 2: Wszystko inne rownolegle
        other_plugins = [p for p in plugins if p.category != SourceCategory.VIN_DECODE]
        await asyncio.gather(
            *[self._run_plugin(scan_id, p, vin, plate) for p in other_plugins],
            return_exceptions=True
        )

    async def _run_plugin(self, scan_id: str, plugin: SourcePlugin, vin: str, plate: Optional[str]):
        """Uruchom pojedynczy plugin z obsluga bledow i raportowaniem statusu."""
        await self.ws.broadcast(scan_id, {
            "source": plugin.name,
            "status": "running",
            "display_name": plugin.display_name
        })

        start = datetime.utcnow()
        try:
            result = await plugin.search_by_vin(vin)

            # Jesli plugin wymaga CAPTCHA — wyslij do UI i czekaj na odpowiedz
            if result.status == SourceStatus.CAPTCHA_REQUIRED:
                await self.ws.broadcast(scan_id, {
                    "source": plugin.name,
                    "status": "captcha_required",
                    "captcha_image": result.data.get("captcha_image_base64")
                })
                # Czekaj na odpowiedz z frontendu (timeout 120s)
                captcha_answer = await self.ws.wait_for_captcha(scan_id, plugin.name, timeout=120)
                result = await plugin.submit_captcha(vin, captcha_answer)

            await self.db.save_scan_result(scan_id, result)
            await self.ws.broadcast(scan_id, {
                "source": plugin.name,
                "status": result.status.value,
                "data": result.data,
                "execution_time_ms": result.execution_time_ms
            })
        except Exception as e:
            await self.ws.broadcast(scan_id, {
                "source": plugin.name,
                "status": "error",
                "error": str(e)
            })
```

### 4.2 Merge VIN data

Dane z wielu zrodel VIN decode sa mergowane z priorytetami:
1. NHTSA API (najlepsza baza, oficjalna)
2. Scraping producenta (dokladne dane specyficzne dla modelu)
3. Offline vininfo/corgi (szybkie, ale ograniczone dla starszych aut)

Zasada: jesli zrodlo A ma pole a zrodlo B nie — bierz z A. Jesli oba maja — bierz z zrodla o wyzszym priorytecie.

---

## 5. CAPTCHA Bridge

### 5.1 Flow

```
Plugin wymaga CAPTCHA
        |
        v
ScanEngine wysyla CAPTCHA image przez WebSocket
        |
        v
Frontend wyswietla CaptchaDialog (modal z obrazkiem)
        |
        v
Uzytkownik wpisuje rozwiazanie
        |
        v
Frontend wysyla odpowiedz przez WebSocket
        |
        v
ScanEngine przekazuje do pluginu, plugin kontynuuje
```

### 5.2 Timeout

- CAPTCHA timeout: 120 sekund
- Jesli uzytkownik nie odpowie — plugin konczy sie ze statusem `CAPTCHA_TIMEOUT`
- Uzytkownik moze recznie ponowic skan danego zrodla

---

## 6. Zrodla danych — szczegoly pluginow

### 6.1 VIN Decoding

| Plugin | Zrodlo | Metoda | CAPTCHA | Uwagi |
|--------|--------|--------|---------|-------|
| `nhtsa` | NHTSA vPIC API | REST API (darmowe) | Nie | Najlepsza darmowa baza, obsluguje EU auta |
| `vininfo_local` | Biblioteka vininfo | Offline Python | Nie | Szybkie, ograniczone dla starszych modeli |
| `manufacturer` | Strony BMW/MB/VW/Audi | Playwright scraping | Mozliwe | Dokladne dane specyficzne, ale ryzyko zmian stron |

**Dane wyjsciowe dekodera:**
- Marka, model, rok produkcji
- Typ nadwozia, silnik (pojemnosc, moc, paliwo)
- Skrzynia biegow, naped
- Fabryczne wyposazenie (jesli dostepne)
- Kraj produkcji, zaklad
- Wersja/generacja modelu

### 6.2 Rejestry pojazdow EU

| Plugin | Kraj | Zrodlo | Metoda | CAPTCHA | Dane |
|--------|------|--------|--------|---------|------|
| `pl_historia` | PL | HistoriaPojazdu.gov.pl | Playwright | TAK | Data rejestracji, status, przebieg (ograniczony) |
| `uk_mot` | UK | MOT History API | REST API | Nie | **Pelna historia MOT** — przebiegi, usterki, daty! |
| `uk_dvla` | UK | DVLA Vehicle Enquiry | REST API | Nie | Rejestracja, klasa emisji, data pierwszej rej. |
| `nl_rdw` | NL | RDW Open Data | REST API | Nie | Dane techniczne, status APK, historia wlascicieli |
| `fr_histovec` | FR | histovec.interieur.gouv.fr | Playwright | TAK | Historia rejestracji, status kradziez, controle technique |
| `be_carpass` | BE | Car-Pass | Playwright | Mozliwe | Historia przebiegow z oficjalnych zrodel belgijskich |
| `de_kba` | DE | KBA / TecDoc | Playwright | Mozliwe | Dane rejestracyjne, specyfikacje techniczne |
| `ch_stva` | CH | Kantonalne rejestry | Playwright | Mozliwe | Dane rejestracyjne Szwajcaria |
| `se_transport` | SE | Transportstyrelsen | Playwright | Mozliwe | Dane rejestracyjne Szwecja |

**Priorytet implementacji**: UK MOT (darmowe API, swietne dane) > NL RDW (open data) > PL Historia > FR Histovec > reszta

### 6.3 Bazy szkod/wypadkow

| Plugin | Zrodlo | Metoda | Dane |
|--------|--------|--------|------|
| `bidfax` | bidfax.info | Playwright | Zdjecia powypadkowe, dane aukcji Copart/IAAI |
| `statvin` | stat.vin | Playwright | Agregat aukcji, zdjecia, ceny |
| `poctr` | poctr.com | Playwright | Archiwum aukcji powypadkowych |

**Uwaga**: Te zrodla obejmuja glownie auta ktore przeszly przez rynek USA. Dla aut czysto europejskich dane moga byc ograniczone — dlatego OSINT zdjeciowy jest kluczowy.

### 6.4 OSINT zdjeciowy

| Plugin | Zrodlo | Metoda | Szukaj po |
|--------|--------|--------|-----------|
| `google_images` | Google Images | Playwright | VIN, marka+model+rok+kolor, tablica |
| `yandex_images` | Yandex Images | Playwright | VIN, tablica (lepszy dla EU/RU zdjec) |
| `wayback` | Wayback Machine | API + Playwright | Archiwalne strony ogloszen z VIN/tablica |
| `forum_search` | Fora motoryzacyjne | Playwright | VIN, tablica na popularnych forach |

**Strategia wyszukiwania zdjec:**
1. Dekoduj VIN → uzyskaj marke, model, rok, kolor
2. Szukaj w Google/Yandex: `"<VIN>"` (dokladny match)
3. Szukaj: `"<tablica_rejestracyjna>"` (jesli podana)
4. Szukaj: `<marka> <model> <rok> <kolor>` (szerszy zasieg, wiecej false positives)
5. Filtruj wyniki — porownaj z danymi z dekodera

### 6.5 Archiwa ogloszen

| Plugin | Zrodlo | Metoda | Dane |
|--------|--------|--------|------|
| `otomoto` | OTOMOTO | Playwright | Archiwalne ogloszenia z PL (ceny, zdjecia, opisy) |
| `mobile_de` | mobile.de | Playwright | Archiwalne ogloszenia z DE |
| `autoscout24` | AutoScout24 | Playwright | Archiwalne ogloszenia pan-EU |

**Wartosc**: jesli auto bylo wczesniej sprzedawane na jednym z tych portali, mozna znalezc historyczne zdjecia, przebieg z tamtego okresu, cene — i porownac z obecnym ogloszeniem.

---

## 7. Baza danych (PostgreSQL)

### 7.1 Konfiguracja

- **Port**: 5434 (nie koliduje z n8n:5432, trading:5433)
- **User**: `vinhunter`
- **Password**: `vinhunterpass`
- **Database**: `vinhunter`

### 7.2 Schema

```sql
-- Sesje skanowania
CREATE TABLE scans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vin VARCHAR(17) NOT NULL,
    plate VARCHAR(20),
    status VARCHAR(20) NOT NULL DEFAULT 'running',  -- running, completed, failed
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    decoded_data JSONB,          -- Zmergowane dane z VIN decode
    metadata JSONB               -- Dodatkowe info (user agent, IP, etc.)
);

CREATE INDEX idx_scans_vin ON scans(vin);
CREATE INDEX idx_scans_created ON scans(created_at DESC);

-- Wyniki poszczegolnych zrodel
CREATE TABLE scan_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    source_name VARCHAR(50) NOT NULL,
    category VARCHAR(30) NOT NULL,
    status VARCHAR(20) NOT NULL,     -- done, error, no_data, captcha_timeout
    data JSONB,                      -- Ustrukturyzowane wyniki
    raw_html TEXT,                   -- Surowy HTML (debug)
    screenshots TEXT[],              -- Sciezki do zrzutow ekranu
    error_message TEXT,
    execution_time_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_results_scan ON scan_results(scan_id);
CREATE INDEX idx_results_source ON scan_results(source_name);

-- Znalezione zdjecia
CREATE TABLE found_photos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    source_name VARCHAR(50) NOT NULL,
    url TEXT NOT NULL,
    thumbnail_url TEXT,
    context TEXT,                    -- Skad pochodzi (forum, ogloszenie, aukcja)
    relevance_score FLOAT,          -- Jak bardzo pasuje do szukanego auta (0-1)
    downloaded BOOLEAN DEFAULT FALSE,
    local_path TEXT,                 -- Sciezka lokalna jesli pobrane
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_photos_scan ON found_photos(scan_id);

-- Wygenerowane raporty
CREATE TABLE reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    format VARCHAR(10) NOT NULL,    -- html_self, html_images
    file_path TEXT NOT NULL,
    file_size_bytes INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Konfiguracja pluginow (enable/disable, custom settings)
CREATE TABLE plugin_config (
    name VARCHAR(50) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    settings JSONB DEFAULT '{}',
    last_used TIMESTAMPTZ,
    total_queries INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0
);
```

---

## 8. Frontend (Vue 3) — UI/UX

### 8.1 Widoki

#### HomeView — strona glowna
- Duze pole wejsciowe na VIN (17 znakow, walidacja checksum)
- Opcjonalne pole na tablice rejestracyjna
- Przycisk "Skanuj" — uruchamia scan
- Pod spodem: lista ostatnich skanow (z DB)

#### ScanView — dashboard skanowania
- **Glowna sekcja**: siatka kart (SourceCard) — kazde zrodlo ma karte z:
  - Ikona flagi kraju
  - Nazwa zrodla
  - Status: spinner (running), zielona fajka (done), czerwony X (error), zolty klucz (captcha)
  - Po zakonczeniu: skrot wynikow (np. "Znaleziono 3 wpisy MOT")
  - Klik na karte → rozwijane szczegoly
- **Sekcja VIN Decoded**: na gorze, wyniki dekodowania (marka, model, rok, silnik, wyposazenie)
- **Sekcja Photo Gallery**: galeria znalezionych zdjec z miniaturkami
- **Sekcja Export**: przycisk "Generuj raport HTML" z opcjami (self-contained / z obrazkami)
- **CAPTCHA Modal**: wyskakuje gdy zrodlo wymaga CAPTCHA — pokazuje obrazek, pole na tekst, timeout counter

#### ReportsView — lista raportow
- Lista wygenerowanych raportow z data, VIN, rozmiarem
- Przycisk pobierania

### 8.2 Real-time updates (WebSocket)

Frontend laczy sie z backendem przez WebSocket po uruchomieniu skanu:

```typescript
// composables/useWebSocket.ts
const ws = new WebSocket(`ws://localhost:8200/ws/scan/${scanId}`)

ws.onmessage = (event) => {
    const update = JSON.parse(event.data)
    // update = { source: "uk_mot", status: "done", data: {...}, execution_time_ms: 1234 }
    scanStore.updateSource(update.source, update)
}
```

Kazda karta zrodla aktualizuje sie na zywo bez przeladowania strony.

### 8.3 Walidacja VIN

Frontend waliduje VIN przed wyslaniem:
- Dokladnie 17 znakow
- Tylko A-Z, 0-9 (bez I, O, Q — standard ISO 3779)
- Checksum (9-ta pozycja) — walidacja matematyczna
- Jesli walidacja nie przejdzie — wyswietl blad z wyjasnieniem

---

## 9. Raport HTML

### 9.1 Self-contained (domyslny)

Jeden plik `.html` z:
- CSS inline (Tailwind CSS build lub proste style)
- JS inline (rozwijanie sekcji, nawigacja)
- Dane inline w `<script>` tag jako JSON
- Zdjecia jako base64 data URIs (miniatury)
- Sekcje: VIN Decode, Rejestry, Szkody, Zdjecia, Archiwa ogloszen
- Kazda sekcja z oznaczeniem statusu zrodla (znaleziono / brak danych / blad)
- Znacznik czasu wygenerowania raportu

### 9.2 Z obrazkami (opcjonalny)

Plik `.html` + folder `<vin>_assets/`:
- Pelne zdjecia pobrane z internetu
- Zrzuty ekranu stron zrodlowych
- CSS/JS jako osobne pliki

### 9.3 Template engine

Jinja2 templates renderowane po stronie backendu. Dane z DB (scan_results + found_photos) wstrzykiwane do template.

---

## 10. Docker Compose

```yaml
# docker-compose.yml
services:
  vinhunter-db:
    image: postgres:16-alpine
    container_name: vinhunter-db
    environment:
      POSTGRES_USER: vinhunter
      POSTGRES_PASSWORD: vinhunterpass
      POSTGRES_DB: vinhunter
    volumes:
      - vinhunter-db-data:/var/lib/postgresql/data
      - ./backend/db-init:/docker-entrypoint-initdb.d
    ports:
      - "5434:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U vinhunter"]
      interval: 5s
      timeout: 3s
      retries: 5

  vinhunter-backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: vinhunter-backend
    depends_on:
      vinhunter-db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://vinhunter:vinhunterpass@vinhunter-db:5432/vinhunter
      PLAYWRIGHT_BROWSERS_PATH: /ms-playwright
    volumes:
      - vinhunter-reports:/app/reports
      - vinhunter-screenshots:/app/screenshots
    ports:
      - "8200:8200"

  vinhunter-frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: vinhunter-frontend
    depends_on:
      - vinhunter-backend
    ports:
      - "3000:80"

volumes:
  vinhunter-db-data:
  vinhunter-reports:
  vinhunter-screenshots:
```

### 10.1 Backend Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps for Playwright
RUN apt-get update && apt-get install -y \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libatspi2.0-0 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8200"]
```

### 10.2 Frontend Dockerfile

```dockerfile
# Build stage
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

---

## 11. API Endpoints

### 11.1 REST API

```
POST   /api/scan                    # Rozpocznij nowy skan (body: {vin, plate?})
GET    /api/scan/{id}               # Status skanu + wyniki
GET    /api/scan/{id}/results       # Wszystkie wyniki zrodel
DELETE /api/scan/{id}               # Usun skan i wyniki

GET    /api/vin/decode/{vin}        # Tylko dekodowanie VIN (bez pelnego skanu)
GET    /api/vin/validate/{vin}      # Walidacja VIN (checksum, format)

POST   /api/reports/{scan_id}       # Wygeneruj raport (body: {format: "html_self"|"html_images"})
GET    /api/reports/{id}/download   # Pobierz wygenerowany raport

GET    /api/plugins                 # Lista pluginow z statusami
PUT    /api/plugins/{name}          # Wlacz/wylacz plugin, zmien ustawienia

GET    /api/health                  # Health check
```

### 11.2 WebSocket

```
WS /ws/scan/{scan_id}

# Server -> Client messages:
{
    "type": "source_update",
    "source": "uk_mot",
    "status": "running" | "done" | "error" | "captcha_required" | "no_data",
    "data": { ... },
    "execution_time_ms": 1234
}

{
    "type": "captcha_request",
    "source": "pl_historia",
    "captcha_image_base64": "data:image/png;base64,...",
    "timeout_seconds": 120
}

{
    "type": "scan_complete",
    "total_sources": 15,
    "successful": 10,
    "errors": 2,
    "no_data": 3
}

# Client -> Server messages:
{
    "type": "captcha_response",
    "source": "pl_historia",
    "answer": "abc123"
}
```

---

## 12. Kluczowe zaleznosci Python (backend)

```
# requirements.txt
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
asyncpg>=0.29.0
sqlalchemy[asyncio]>=2.0.0
pydantic>=2.0.0
pydantic-settings>=2.0.0

# Scraping
crawlee[playwright]>=0.4.0
playwright>=1.40.0

# VIN decode
vininfo>=1.7.0
httpx>=0.27.0                     # Async HTTP client (NHTSA API, itp.)

# Report generation
jinja2>=3.1.0
pillow>=10.0.0                    # Obrazki (thumbnail, base64)

# WebSocket
websockets>=12.0

# Utilities
python-dotenv>=1.0.0
structlog>=24.0.0                 # Structured logging
```

---

## 13. Kluczowe zaleznosci Node (frontend)

```json
{
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.3.0",
    "pinia": "^2.2.0",
    "@vueuse/core": "^11.0.0"
  },
  "devDependencies": {
    "vite": "^5.4.0",
    "@vitejs/plugin-vue": "^5.0.0",
    "typescript": "^5.5.0",
    "tailwindcss": "^3.4.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0"
  }
}
```

---

## 14. Proxy Rotation (na przyszlosc)

Architektura gotowa na dodanie proxy:

```python
# core/proxy_manager.py (przygotowane, nie aktywne na start)
class ProxyManager:
    """Zarzadzanie proxy rotation — aktywowane gdy zrodla zaczynaja banowac."""

    def __init__(self, proxy_list: list[str]):
        self.proxies = proxy_list
        self.current_index = 0
        self.blacklisted: set[str] = set()

    def get_next(self) -> str | None:
        """Round-robin z pomijaniem zbanowanych."""
        ...

    def report_ban(self, proxy: str):
        """Oznacz proxy jako zbanowane."""
        self.blacklisted.add(proxy)
```

Konfiguracja w `.env`:
```
PROXY_ENABLED=false
PROXY_LIST=socks5://proxy1:1080,socks5://proxy2:1080
PROXY_ROTATION=round_robin
```

---

## 15. Obsluga bledow i resilience

### 15.1 Plugin-level

- Kazdy plugin ma timeout (domyslnie 30s, konfigurowalny)
- Playwright pages zamykane w `finally` (brak memory leaks)
- Retry logic: 1 retry z 3s delay dla bledow sieciowych
- Blad pluginu NIE zatrzymuje calego skanu — inne pluginy dzialaja dalej

### 15.2 Scan-level

- Skan konczy sie nawet jesli wszystkie pluginy zwroca blad (status: completed_with_errors)
- WebSocket reconnect po stronie frontendu (retry z exponential backoff)
- Mozliwosc ponownego uruchomienia pojedynczego pluginu bez restartu calego skanu

### 15.3 Logging

Structured logging (structlog) z poziomami:
- INFO: start/koniec skanu, wynik pluginu
- WARNING: CAPTCHA timeout, retry, brak danych
- ERROR: blad pluginu, blad DB, blad WebSocket
- DEBUG: surowe HTTP responses, HTML parsing details

---

## 16. Bezpieczenstwo

- **Brak przechowywania danych osobowych** osob trzecich (np. dane wlascicieli) — tylko dane techniczne pojazdu
- **Credentiale** (DB, API keys) w `.env`, nie w kodzie
- **CORS** skonfigurowany na localhost:3000 (frontend)
- **Rate limiting** na API (zapobieganie przypadkowemu DDoS)
- **Scraping ethics**: User-Agent identyfikujacy narzedzie, respektowanie robots.txt (konfigurowalne per plugin)

---

## 17. Znane ograniczenia i ryzyka

| Ryzyko | Prawdopodobienstwo | Wplyw | Mitygacja |
|--------|-------------------|-------|-----------|
| Strony zmieniaja HTML — scraper przestaje dzialac | Wysokie | Sredni | Plugin system — latwa aktualizacja jednego pluginu |
| Ban IP bez proxy | Srednie | Niski | Architektura gotowa na proxy, dodanie to zmiana configa |
| CAPTCHA zbyt czeste — UX cierpi | Srednie | Sredni | Grupowanie zrodel z CAPTCHA, mozliwosc pominiecia |
| Baza NHTSA nie ma danych dla starych EU aut | Srednie | Niski | Multi-source merge, offline decode jako fallback |
| Playwright w Docker zuzywa duzo RAM | Niskie | Sredni | Limitowanie concurrent Playwright pages (domyslnie 3) |
| Dane z OSINT moga byc nieaktualne | Wysokie | Niski | Wyrazne oznaczenie daty zrodla w raporcie |

---

## 18. Porty i dostep

| Serwis | Port | Opis |
|--------|------|------|
| Frontend (Vue 3) | 3000 | UI w przegladarce |
| Backend (FastAPI) | 8200 | REST API + WebSocket |
| PostgreSQL | 5434 | Baza danych |

**Nie koliduje z**: n8n (5432), trading (5433), ai-repo (5435, 8100)

---

## 19. Decyzje projektowe — uzasadnienia

| Decyzja | Alternatywa | Powod wyboru |
|---------|-------------|--------------|
| Vue 3 zamiast React | React | Prostszy start dla nowego uzytkownika, intuicyjny template syntax |
| Crawlee zamiast surowy Playwright | Scrapy, requests | Wbudowana anti-detekcja, retry, queueing — zero doswiadczenia w scrapingu |
| PostgreSQL zamiast SQLite | SQLite | Spojnosc z innymi projektami, lepsze wsparcie JSON/async |
| Plugin system zamiast monolitu | YAML config | Elastycznosc, izolacja bledow, latwe dodawanie zrodel |
| WebSocket zamiast polling | SSE, polling | Dwukierunkowa komunikacja (potrzebna dla CAPTCHA response) |
| HTML raport zamiast PDF | PDF | Interaktywny, latwiejszy do generowania, self-contained |
| Bez LLM w MVP | LLM od startu | Zmniejsza zlozonosc, LLM latwo dodac pozniej jako kolejny krok wizarda |
| Bez proxy na start | Proxy od startu | Pragmatyczne — wiele zrodel nie banuje przy niskim volumenie |

---

## 20. Przyszle rozszerzenia (post-MVP)

1. **LLM analiza** — przycisk "Analizuj z AI": ocena ryzyka, red flags, pytania do sprzedawcy (Ollama qwen3 / Claude API fallback)
2. **Proxy rotation** — dodanie po pierwszych banach IP
3. **Logowanie do zrodel** — credential store dla for, aukcji
4. **Aukcje USA** — Copart/IAAI przez agregatory (bidfax, stat.vin)
5. **Reverse image search** — upload zdjecia z ogloszenia, szukaj duplikatow w sieci
6. **Porownywanie aut** — side-by-side dwoch VIN (ktory lepszy?)
7. **Alerty** — monitoring VIN: jesli pojawia sie nowe dane, powiadom
8. **Mobile view** — responsywny frontend na telefon (ogloszenia przegladasz na telefonie)
9. **API dla n8n** — integracja z n8n workflows (automatyczne sprawdzanie nowych ogloszen)
10. **OCR dowodu rejestracyjnego** — upload zdjecia dowodu, automatyczne parsowanie danych
