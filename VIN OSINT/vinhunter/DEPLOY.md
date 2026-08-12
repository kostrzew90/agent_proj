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

Sprawdź też, czy porty 3010/8200/5436 nie są już zajęte przez Argusa/RAG na tym
samym VPS — kolizja portów ujawniłaby się dopiero jako myląca porażka
`docker compose up -d` w połowie builda (po ściągnięciu obrazu Playwright ~2-3GB),
więc lepiej złapać to teraz:

```bash
ssh root@169.58.146.162 "ss -tlnp | grep -E ':(3010|8200|5436)' || echo 'porty wolne'"
```

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

Uwaga: `rsync` nie jest domyślnie dostępny w Git Bash na Windows. Doinstaluj go
(np. przez MSYS2/Git for Windows z pakietem rsync) albo użyj fallbacku `scp`
(mniej precyzyjny — brak `--exclude`, więc `node_modules` trzeba usunąć ręcznie
przed wysyłką albo posprzątać po stronie VPS):

```bash
scp -r "VIN OSINT/vinhunter" root@169.58.146.162:~/vinhunter
```

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

Dla wariantu 2a (mono-repo) ta ścieżka to podkatalog `VIN OSINT/vinhunter` w
klonie mono-repo, NIE `~/vinhunter` — to WAŻNE, bo stamtąd compose czyta `.env`
(czyli `TAILSCALE_IP`); pomyłka w katalogu daje cichy fallback na `127.0.0.1`
(błąd, który spec już nazwał jako główny foot-gun).

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

Z maszyny POZA tailnetem (np. telefon na LTE, nie urządzenie z Tailscale), sprawdź publiczny IP NIE
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
