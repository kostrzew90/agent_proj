# VINhunter — deploy na VPS (Phase 1: prywatny)

## Kontekst

VINhunter (`VIN OSINT/vinhunter/`) to osobiste narzędzie OSINT do weryfikacji ~20-letnich
aut sprowadzanych z UE. Obecnie działa lokalnie na Windows/Docker Desktop — dostępne
tylko gdy laptop użytkownika jest włączony.

Cel tego etapu: przenieść VINhuntera na istniejący VPS (Contabo, `84.235.174.129`,
x86_64, 4 vCPU, 15GB RAM, Ubuntu 22.04 — hostname `ai-kosrv`), na którym już działa
Argus (`argus-app`, `argus-liq-listener`, `argus-guardian`, Grafana), żeby narzędzie
działało 24/7 niezależnie od laptopa.

To jest **Phase 1: deployment prywatny**, dostępny wyłącznie przez Tailscale, dokładnie
tak jak dziś działa `argus-app`. Publiczne udostępnienie (domena, TLS, auth,
rate-limiting, powiązanie z contentem wideo) to świadomie osobny, przyszły spec —
nie jest częścią tej pracy.

## Cele (Phase 1)

- VINhunter (backend + frontend + własny Postgres) działa jako kontenery Docker na VPS,
  `restart: unless-stopped`, dostępny 24/7.
- Dostęp wyłącznie przez Tailscale IP VPS — żaden port VINhuntera nie jest otwarty
  publicznie (w tym port DB, który dziś lokalnie jest zmapowany na `0.0.0.0:5436`).
- Deploy przez `git pull` z istniejącego mono-repo (remote:
  `github.com/kostrzew90/agent_proj`) — bez nowej infrastruktury CI/CD.
- Sekrety (`.env`: klucz Vincario, dane DB) trafiają na VPS ręcznie przez `scp`,
  nigdy nie są commitowane.

## Poza zakresem (explicite)

- Publiczna domena / TLS / reverse proxy dla ruchu z internetu.
- Auth, rate-limiting, ochrona przed nadużyciem płatnego API (Vincario).
- Landing page / CTA / jakiekolwiek powiązanie z eksperymentem content-owym (shorty).
- Odblokowywanie 6 pluginów zablokowanych przez Cloudflare — nie jest celem tego etapu
  i nie oczekujemy poprawy (patrz Ryzyka).
- Aktywacja proxy rotation (`proxy/README.md`) — pozostaje wyłączona jak dziś.
- Zmiany w logice aplikacji (backend/frontend) — to czysto operacyjny deployment.

## Architektura

Osobny stack `docker-compose.yml` obok Argusa na tym samym VPS — **nie** scalanie do
jednego pliku compose z Argusem. Powód: Argus i VINhunter to niezależne projekty;
wspólny compose sprzęgłby ich cykl życia (restart/rebuild jednego ryzykowałby drugi).

Trzy kontenery, 1:1 z obecnym lokalnym `docker-compose.yml`:

- `vinhunter-db` — Postgres 16-alpine, wolumen `vinhunter-db-data`.
- `vinhunter-backend` — FastAPI + Playwright (Chromium + Firefox), wolumeny na
  `reports`/`screenshots`.
- `vinhunter-frontend` — Vue 3 SPA za nginx.

Jedyna zmiana względem lokalnego compose: mapowanie portów. Dziś wszystkie trzy porty
(`3010`, `8200`, `5436`) są zbindowane na `0.0.0.0` (wszystkie interfejsy) — na VPS
to musi się zmienić na wzorzec już używany przez `argus-app`:

```yaml
ports: ["${TAILSCALE_IP:-127.0.0.1}:PORT:PORT"]
```

zastosowane do wszystkich trzech serwisów, łącznie z `vinhunter-db` (dziś jedyny
kontener bez tej ochrony — na VPS otwarty Postgres na porcie 5436 byłby dostępny
z całego internetu).

## Deploy — przebieg

1. Na VPS: `git pull` w istniejącym klonie mono-repo (ten sam, z którego działa Argus).
2. `scp` pliku `.env` z sekretami do `VIN OSINT/vinhunter/.env` na VPS (ręcznie, nigdy
   przez git).
3. `docker compose -f "VIN OSINT/vinhunter/docker-compose.yml" up -d --build`.
4. Weryfikacja (patrz niżej).

## Ryzyka i decyzje

- **Zasoby współdzielone z Argusem.** VPS ma 4 vCPU/15GB, na których już działają
  Argus + Guardian + Grafana + ich Postgres. Playwright z dwoma silnikami przeglądarki
  (Chromium + Firefox) jest relatywnie ciężki pamięciowo. **Przed buildem** trzeba
  sprawdzić na żywo (`free -h`, `docker stats`) czy jest zapas — nie zakładamy tego
  z góry. Jeśli zapasu brakuje, opcje do rozważenia w Build: ograniczenie do jednego
  silnika przeglądarki, albo limity pamięci w compose (`mem_limit`) — decyzja
  odroczona do czasu zmierzenia realnego zużycia.
- **Cloudflare i IP datacenter.** 6 z 16 pluginów jest dziś zablokowanych na domowym
  IP użytkownika. IP datacenter (Contabo) statystycznie ma gorszą reputację niż IP
  domowe u dostawcy residential/ISP — nie oczekujemy poprawy wykrywalności, może być
  gorzej. To akceptowalne dla Phase 1 (cel to dostępność narzędzia, nie naprawa CF) —
  ale użytkownik powinien nie być zaskoczony, że blokady się nie zmienią lub urosną.
- **Sekrety.** `.env` z płatnym kluczem Vincario trafia na VPS ręcznie. Ponieważ
  dostęp jest ograniczony do Tailscale (zaufana sieć), nie ma dodatkowego ryzyka
  nadużycia w Phase 1 — to zagadnienie wraca w Phase 2 przy publicznym udostępnieniu.

## Weryfikacja (definicja "działa")

- `docker compose ps` — wszystkie 3 kontenery `healthy`/`running`.
- Health-check backendu przez `curl` z VPS (przez Tailscale IP), nie tylko "kontener
  wstał".
- Jeden realny skan VIN-a (znany, wcześniej testowany VIN) — potwierdza, że pluginy
  faktycznie się wykonują i zwracają wyniki, nie tylko że proces backendu żyje.
- Frontend dostępny w przeglądarce pod Tailscale IP VPS.

## Otwarte pytania (do zmierzenia w Build, nie do zgadywania teraz)

- Realny wolny RAM/CPU na VPS po uruchomieniu VINhuntera obok Argusa.
- Czy `.env` produkcyjny (Vincario key) już istnieje gotowy do `scp`, czy trzeba go
  odtworzyć.
