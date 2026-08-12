# VINhunter VPS Deploy (Phase 1: prywatny) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Postawić VINhuntera (FastAPI + Vue 3 + Postgres + Playwright) jako kontenery Docker na istniejącym VPS (Contabo, publiczny IP `169.58.146.162`, tailnet IP `100.71.197.18` — VPS z migracji 2026-08-11/12, zastąpił utracony Oracle VPS `84.235.174.129`), dostępne wyłącznie przez Tailscale, działające 24/7 niezależnie od laptopa użytkownika.

**Architecture:** Osobny plik `docker-compose.vps.yml` obok lokalnego `docker-compose.yml` (ten sam wzorzec co `RAG/docker-compose.vps.yml`) — pełna, samodzielna definicja 3 serwisów (`vinhunter-db`, `vinhunter-backend`, `vinhunter-frontend`) z `restart: unless-stopped`, portami zbindowanymi na `${TAILSCALE_IP:-127.0.0.1}` i backendem uruchamianym bez `--reload`. Lokalny `docker-compose.yml` i `backend/Dockerfile` pozostają nietknięte — deployment VPS to nowy, równoległy plik, nie modyfikacja dev-setupu.

**Tech Stack:** Docker Compose, FastAPI/uvicorn, Vue 3 + nginx, Postgres 16, Playwright (Chromium + Firefox), npm.

## Global Constraints

- Żaden port VINhuntera nie może być otwarty na `0.0.0.0` na VPS — wyłącznie `${TAILSCALE_IP:-127.0.0.1}:PORT:PORT`, dotyczy też `vinhunter-db` (dziś jedyny serwis bez tej ochrony lokalnie).
- Zero zmian w logice aplikacji (`backend/`, `frontend/src/`) — to czysto operacyjny deployment.
- Zero migracji danych — DB na VPS startuje pusta (decyzja z `docs/superpowers/specs/2026-08-12-vinhunter-vps-deploy-design.md`).
- Sekrety (`.env` z kluczem Vincario) nigdy nie trafiają do gita.
- Referencyjny spec: `docs/superpowers/specs/2026-08-12-vinhunter-vps-deploy-design.md` — każde odstępstwo od niego w trakcie budowy wraca do tego dokumentu, nie jest cichą decyzją w kodzie.

---

### Task 1: `docker-compose.vps.yml`

**Files:**
- Create: `VIN OSINT/vinhunter/docker-compose.vps.yml`
- Reference (nie modyfikować): `VIN OSINT/vinhunter/docker-compose.yml`, `RAG/docker-compose.vps.yml` (wzorzec)

**Interfaces:**
- Consumes: obraz `postgres:16-alpine`; buildy `./backend` i `./frontend` (te same Dockerfile co lokalnie, backend z nadpisanym `command:`).
- Produces: plik gotowy do `docker compose -f docker-compose.vps.yml up -d --build` na VPS (Task 5).

- [ ] **Step 1: Napisz `docker-compose.vps.yml`**

```yaml
services:
  vinhunter-db:
    image: postgres:16-alpine
    container_name: vinhunter-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: vinhunter
      POSTGRES_PASSWORD: vinhunterpass
      POSTGRES_DB: vinhunter
    volumes:
      - vinhunter-db-data:/var/lib/postgresql/data
      - ./backend/db-init:/docker-entrypoint-initdb.d
    ports:
      - "${TAILSCALE_IP:-127.0.0.1}:5436:5432"
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
    restart: unless-stopped
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8200"]
    depends_on:
      vinhunter-db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://vinhunter:vinhunterpass@vinhunter-db:5432/vinhunter
      PLAYWRIGHT_BROWSERS_PATH: /ms-playwright
    env_file:
      - .env
    volumes:
      - vinhunter-reports:/app/reports
      - vinhunter-screenshots:/app/screenshots
    ports:
      - "${TAILSCALE_IP:-127.0.0.1}:8200:8200"

  vinhunter-frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: vinhunter-frontend
    restart: unless-stopped
    depends_on:
      - vinhunter-backend
    ports:
      - "${TAILSCALE_IP:-127.0.0.1}:3010:80"

volumes:
  vinhunter-db-data:
  vinhunter-reports:
  vinhunter-screenshots:
```

Różnice względem `docker-compose.yml` — dokładnie te i tylko te (patrz spec, sekcja Architektura):
1. `restart: unless-stopped` na wszystkich trzech serwisach.
2. Porty zbindowane na `${TAILSCALE_IP:-127.0.0.1}` zamiast domyślnego `0.0.0.0`.
3. `command:` na `vinhunter-backend` nadpisuje `CMD` z Dockerfile, usuwając `--reload`.
4. Nazwy wolumenów bez zmian (osobny host = osobny namespace Dockera, brak kolizji z lokalnymi wolumenami na Windows).

- [ ] **Step 2: Zwaliduj składnię lokalnie**

Wymaga uruchomionego Docker Desktop. Uruchom Docker Desktop, potem:

Run: `cd "VIN OSINT/vinhunter" && docker compose -f docker-compose.vps.yml config --quiet`
Expected: brak output, exit code 0 (błąd składni YAML lub nieznana referencja da niezerowy exit code i komunikat błędu).

- [ ] **Step 3: Commit**

```bash
git add "VIN OSINT/vinhunter/docker-compose.vps.yml"
git commit -m "feat(vinhunter): docker-compose.vps.yml dla prywatnego deployu na VPS"
```

---

### Task 2: `package-lock.json` dla frontendu

**Files:**
- Create: `VIN OSINT/vinhunter/frontend/package-lock.json`
- Reference: `VIN OSINT/vinhunter/frontend/package.json`, `VIN OSINT/vinhunter/frontend/Dockerfile` (Step `COPY package*.json ./` już go podniesie automatycznie, gdy plik istnieje)

**Interfaces:**
- Consumes: nic z Task 1.
- Produces: zapięte wersje npm-zależności, których builduje `frontend/Dockerfile` w Task 5 na VPS — bez tego build na VPS robi `npm install` z dowolnymi najnowszymi wersjami zgodnymi z `package.json`, co może dać inny wynik niż lokalny build.

- [ ] **Step 1: Wygeneruj lockfile**

Run: `cd "VIN OSINT/vinhunter/frontend" && npm install`
Expected: tworzy `package-lock.json` w tym katalogu, `node_modules/` (już w `.gitignore` — zweryfikuj poniżej).

- [ ] **Step 2: Zweryfikuj, że `node_modules/` nie trafi do commita**

Run: `git status --short "VIN OSINT/vinhunter/frontend"`
Expected: widoczny tylko `package-lock.json` jako nowy plik (i ewentualnie zmiany w `package.json`, jeśli `npm install` coś przeliczył — nie powinno, bo nie dodajemy/zmieniamy zależności). Jeśli `node_modules/` się pojawia, dodaj `node_modules/` do `VIN OSINT/vinhunter/frontend/.gitignore` przed commitem.

- [ ] **Step 3: Zweryfikuj, że build lokalny nadal przechodzi z lockfile**

Wymaga uruchomionego Docker Desktop.
Run: `cd "VIN OSINT/vinhunter" && docker compose build vinhunter-frontend`
Expected: build kończy się sukcesem (exit code 0), bez błędów `npm ci`/`npm install`.

- [ ] **Step 4: Commit**

```bash
git add "VIN OSINT/vinhunter/frontend/package-lock.json"
git commit -m "chore(vinhunter): commituj package-lock.json dla powtarzalnych buildów"
```

---

### Task 3: `.env.example` — udokumentuj `TAILSCALE_IP`

**Files:**
- Modify: `VIN OSINT/vinhunter/.env.example`

**Interfaces:**
- Consumes: nic.
- Produces: dokumentację wymaganą przy tworzeniu `.env` na VPS w Task 6.

- [ ] **Step 1: Dodaj sekcję o `TAILSCALE_IP` na górze pliku**

Aktualna zawartość zaczyna się od:
```
# Database
DATABASE_URL=postgresql+asyncpg://vinhunter:vinhunterpass@vinhunter-db:5432/vinhunter
```

Dodaj przed tą linią:
```
# VPS only — Tailscale IP hosta, do bindowania portów w docker-compose.vps.yml.
# Lokalnie (Windows/Docker Desktop) nieużywane — zmienna zostaje pusta, porty
# domyślnie na 127.0.0.1.
TAILSCALE_IP=

```

- [ ] **Step 2: Zweryfikuj wizualnie**

Run: `cat "VIN OSINT/vinhunter/.env.example"` (lub odpowiednik na Windows)
Expected: nowa sekcja `TAILSCALE_IP` widoczna na górze, reszta pliku niezmieniona.

- [ ] **Step 3: Commit**

```bash
git add "VIN OSINT/vinhunter/.env.example"
git commit -m "docs(vinhunter): udokumentuj TAILSCALE_IP w .env.example"
```

---

### Task 4: `DEPLOY.md` — runbook

**Files:**
- Create: `VIN OSINT/vinhunter/DEPLOY.md`

**Interfaces:**
- Consumes: plik z Task 1 (`docker-compose.vps.yml`), sekcję `TAILSCALE_IP` z Task 3.
- Produces: dokument, z którego user ręcznie wykonuje Task 6 (SSH/deploy) — ten plik NIE jest wykonywany automatycznie przez agenta, bo sandbox agenta nie ma dostępu SSH do VPS (zweryfikowane podczas researchu do spec-a: `ssh ... ubuntu@84.235.174.129` timeoutuje z tego środowiska).

- [ ] **Step 1: Napisz runbook**

```markdown
# VINhunter — deploy na VPS (Phase 1: prywatny)

Prerekwizyty: `docker-compose.vps.yml` i zaktualizowany `.env.example` są już
zmergowane (Task 1-3 tego planu). Ten runbook wykonujesz ręcznie, z własnego
terminala — SSH do VPS nie działa z sandboksa agenta.

VPS: Contabo, publiczny IP `169.58.146.162`, tailnet IP `100.71.197.18`, 6 vCPU,
11GB RAM, 193GB dysk, Ubuntu 24.04.4 LTS. Login: `root` (klucz w
`authorized_keys`, `PasswordAuthentication no`).

## 0. Sprawdź, jak kod trafił na VPS dla Argusa/RAG

Zanim zdecydujesz jak dostarczyć VINhuntera, sprawdź istniejący wzorzec — nie jest
pewne z dokumentacji, czy `~/argus` i `~/rag` to podkatalogi jednego sklonowanego
mono-repo, czy osobno wgrane drzewa:

```bash
ssh root@169.58.146.162 "ls -la ~ && echo --- && cat ~/argus/.git/config 2>&1 | head -5 && echo --- && cat ~/rag/.git/config 2>&1 | head -5"
```

- Jeśli `~/argus/.git/config` pokazuje remote `agent_proj` i `~/argus` to w
  rzeczywistości symlink/subdirectory sklonowanego mono-repo — zrób to samo dla
  VINhuntera (patrz krok 2a).
- Jeśli to osobne drzewa bez `.git` (albo `.git` bez remote) — kod trafił tam przez
  `scp`/`rsync`, nie `git clone`. Zrób to samo dla VINhuntera (krok 2b).

## 1. Sprawdź zasoby PRZED buildem

```bash
ssh root@169.58.146.162 "free -h && echo --- && df -h /"
```

VPS ma 11GB RAM na trzy projekty (Argus + RAG + teraz VINhunter) — mniej niż
pierwotnie sądzone 15GB, więc realnie sprawdź zapas, nie zakładaj że starczy.
Obraz backendu VINhuntera z Playwright Chromium+Firefox to ~2-3GB, plus runtime
dwóch silników przeglądarki. Dysk: VPS ma 193GB, powinno wystarczyć z zapasem, ale
potwierdź. Jeśli zapasu RAM brakuje — STOP, wróć do sekcji "Ryzyka" w
`docs/superpowers/specs/2026-08-12-vinhunter-vps-deploy-design.md` zamiast
kontynuować.

## 2a. Wariant: mono-repo już sklonowane na VPS

```bash
ssh root@169.58.146.162
cd <ścieżka mono-repo znaleziona w kroku 0>
git pull
```

## 2b. Wariant: osobne drzewa per projekt (jak sugerują `~/argus`, `~/rag`)

Z lokalnej maszyny (Windows), prześlij katalog VINhuntera na VPS:

```bash
rsync -avz --exclude 'node_modules' --exclude '.env' \
  "VIN OSINT/vinhunter/" root@169.58.146.162:~/vinhunter/
```

(`.env` celowo wykluczony z rsync — trafia tam ręcznie w kroku 3, nigdy przez
sync/git.)

## 3. Przygotuj `.env` na VPS

Na VPS, w katalogu VINhuntera (`~/vinhunter` lub odpowiednik z kroku 0):

```bash
cp .env.example .env
```

Uzupełnij ręcznie w `.env`:
- `TAILSCALE_IP=100.71.197.18` (tailnet IP tego VPS — ten sam wzorzec, co w
  `~/argus/.env` i `~/rag/.env`).
- `VINCARIO_API_KEY`, `VINCARIO_SECRET_KEY` — jeśli chcesz mieć aktywny ten
  plugin na VPS (skopiuj z lokalnego `.env`, NIE commituj).
- Pozostałe wartości mogą zostać domyślne z `.env.example`.

## 4. Zbuduj i uruchom

```bash
cd ~/vinhunter   # lub odpowiednik ścieżki z kroku 0
docker compose -f docker-compose.vps.yml up -d --build
```

## 5. Zweryfikuj

```bash
docker compose -f docker-compose.vps.yml ps
# oczekiwane: vinhunter-db "healthy", pozostałe dwa "running"

curl http://100.71.197.18:8200/api/health
# oczekiwane: HTTP 200

curl -X POST http://100.71.197.18:8200/api/scan \
  -H "Content-Type: application/json" \
  -d '{"vin": "WBADE6302V1234567"}'
# oczekiwane: skan startuje (dokładny kształt requestu/response — zweryfikuj
# w backend/routes/ jeśli endpoint się nie zgadza; ten VIN to placeholder z
# frontend/src/components/VinInput.vue, użyj VIN-a, który wcześniej testowałeś
# lokalnie, jeśli chcesz porównać wynik)
```

Z maszyny podłączonej do tej samej sieci Tailscale, sprawdź publiczny IP NIE
odpowiada (potwierdzenie, że binding na `TAILSCALE_IP` faktycznie działa, tak jak
zweryfikowano dla Argusa/RAG):

```bash
curl --max-time 5 http://169.58.146.162:8200/api/health
# oczekiwane: timeout / connection refused, NIE odpowiedź 200
```

W przeglądarce, z maszyny podłączonej do tej samej sieci Tailscale, otwórz
`http://100.71.197.18:3010` i potwierdź, że frontend się ładuje i wywołania
`/api` (network tab) przechodzą przez `vinhunter-frontend`'s nginx bez błędów
CORS.

## 6. Rollback (jeśli VINhunter zaczyna dławić Argusa/RAG)

```bash
docker compose -f docker-compose.vps.yml down
```

Argus i RAG działają w osobnych stackach compose i nie są tym dotknięte.
```

- [ ] **Step 2: Commit**

```bash
git add "VIN OSINT/vinhunter/DEPLOY.md"
git commit -m "docs(vinhunter): runbook deployu na VPS"
```

---

### Task 5: Aktualizacja `VIN OSINT/CLAUDE.md`

**Files:**
- Modify: `VIN OSINT/CLAUDE.md`

**Interfaces:**
- Consumes: nic.
- Produces: aktualny wskaźnik dla przyszłych sesji, że VINhunter ma tryb VPS.

- [ ] **Step 1: Dodaj linię w sekcji "Project Overview"**

Znajdź linię:
```
- **Docker**: `docker compose up -d --build` in `VIN OSINT/vinhunter/`
```

Dodaj bezpośrednio po niej:
```
- **VPS deploy (Phase 1, prywatny)**: `docker-compose.vps.yml` + `DEPLOY.md` w tym samym katalogu; dostęp wyłącznie przez Tailscale, bez publicznej ekspozycji
```

- [ ] **Step 2: Commit**

```bash
git add "VIN OSINT/CLAUDE.md"
git commit -m "docs(vinhunter): wspomnij o VPS deploy w CLAUDE.md"
```

---

### Task 6: Wykonanie deploymentu na VPS (ręczne, poza agentem)

**Files:** brak zmian w repo — ten task to wykonanie `DEPLOY.md` z Task 4.

**Interfaces:**
- Consumes: `docker-compose.vps.yml` (Task 1), `.env.example` (Task 3), `DEPLOY.md` (Task 4) — wszystkie muszą być już zmergowane.
- Produces: działający VINhunter na VPS, dostępny przez Tailscale.

To NIE jest task do delegowania subagentowi — wymaga SSH do `169.58.146.162`,
co nie działa z sandboksa agenta (potwierdzone podczas researchu do spec-a, na
starym adresie VPS; nowy adres nie był jeszcze testowany z tego sandboksa, ale
założenie o braku wychodzącego dostępu do sieci dotyczy sandboksa jako takiego,
nie konkretnego IP). Wykonuje go użytkownik ręcznie, z własnego terminala (np.
przez `!` w Claude Code, albo bezpośrednio).

**Uwaga do kroku SSH:** lokalny plik klucza dla tego VPS nie został jednoznacznie
zidentyfikowany podczas researchu (w odróżnieniu od starego Oracle VPS, gdzie
klucz to `C:\ai\ssh-key-2026-05-19.key`). Najbardziej prawdopodobny kandydat to
domyślny `~/.ssh/id_ed25519` (memory wspomina publiczny klucz oznaczony jako
`vps-contabo` w `authorized_keys` na serwerze, bez podania lokalnej ścieżki private
key) — jeśli `ssh root@169.58.146.162` bez `-i` nie zadziała, sprawdź który klucz
lokalny odpowiada temu w `authorized_keys` na serwerze.

- [ ] **Step 1: Wykonaj kroki 1-5 z `VIN OSINT/vinhunter/DEPLOY.md`**
- [ ] **Step 2: Wklej output kroku "Zweryfikuj" (Task 4, sekcja 5) z powrotem do sesji**, żeby potwierdzić `docker compose ps`, `curl /api/health` i wynik skanu VIN-a — to jest definicja "działa" ze spec-a, nie samo uruchomienie kontenerów.
- [ ] **Step 3: Jeśli coś nie działa** — wróć do sekcji "Ryzyka i decyzje" w spec-u (`docs/superpowers/specs/2026-08-12-vinhunter-vps-deploy-design.md`) przed próbą samodzielnego fixa; większość prawdopodobnych awarii (brak `TAILSCALE_IP`, brak zapasu RAM/dysku, brak `.env`) jest tam już nazwana.
