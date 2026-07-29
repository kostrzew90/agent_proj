# DEVELOPMENT.md — praca lokalna nad stroną

Ten plik opisuje **tylko lokalne uruchomienie i edycję**. Wdrożenie na home.pl (FTPS, formularz, sekrety, pułapki) jest w **`DEPLOY.md`** — to źródło prawdy dla deployu.

## Wymagania

- Node.js 18+
- npm

---

## Instalacja zależności

```bash
cd Arturborzewski
npm install
```

> Jeśli wystąpi błąd SSL (`UNABLE_TO_VERIFY_LEAF_SIGNATURE`) — proxy przechwytujące certyfikaty:
> ```bash
> npm config set strict-ssl false
> npm install
> ```

---

## Podgląd w przeglądarce (tryb dev)

```bash
npm run dev
```

Otwórz: http://localhost:3000 — zmiany widać od razu.

W trybie dev **nie działa formularz kontaktowy** — to PHP (`public/contact.php`), które żyje dopiero na serwerze home.pl. Lokalnie testujesz sam wygląd i walidację po stronie przeglądarki.

---

## Build produkcyjny + podgląd statyku

```bash
npm run build
npx serve out -p 3333
```

Otwórz: http://localhost:3333

`npm run build` odpala najpierw `prebuild` (`scripts/optimize-images.mjs` — optymalizacja zdjęć do WebP), a potem `next build` w trybie `output: 'export'`. Wynik ląduje w **`out/`** — to dokładnie to, co idzie na serwer.

> Jeśli build wywala błąd SSL przy pobieraniu Google Fonts (proxy przechwytujące SSL):
> ```bash
> NODE_TLS_REJECT_UNAUTHORIZED=0 npm run build
> ```
> Tylko na takiej maszynie — **nie** wpisuj tego na stałe.

---

## Struktura plików do edycji

| Plik | Co zmienić |
|------|-----------|
| `content/site.json` | dane kancelarii, kontakt, lista specjalizacji, `url` (canonical/SEO) |
| `public/images/` | zdjęcia i logo (build sam robi WebP) |
| `app/page.tsx` | strona główna |
| `app/prawo-karne/page.tsx`, `app/prawo-gospodarcze/page.tsx` | podstrony specjalizacji |
| `app/polityka-prywatnosci/page.tsx`, `app/w-przygotowaniu/page.tsx` | strony pomocnicze |
| `app/ContactForm.tsx` | front formularza (backend: `public/contact.php`, patrz `DEPLOY.md` §5) |
| `public/.htaccess` | HTTPS, nagłówki, **CSP** (patrz pułapka w `DEPLOY.md` §6) |

### Dodajesz nową podstronę specjalizacji?

Karty na stronie głównej linkują do `/{slug}/` **tylko** dla slugów wymienionych w `SPEC_PAGES` (`app/page.tsx`); pozostałe prowadzą na `/w-przygotowaniu/`. Tworząc `app/{slug}/page.tsx` **dopisz slug do `SPEC_PAGES`**, inaczej karta dalej będzie kierować na „w przygotowaniu".

---

## Deploy

Nie jest częścią tego pliku. Pełny runbook: **`DEPLOY.md`**. W skrócie, po sprawdzeniu zmian lokalnie:

```bash
npm run build
node --env-file=.env scripts/deploy.mjs
```
