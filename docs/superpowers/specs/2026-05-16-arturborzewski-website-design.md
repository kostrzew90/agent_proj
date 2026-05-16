# Design: Arturborzewski — strona wizytówkowa Next.js

**Data:** 2026-05-16  
**Autor:** Damian Kostrzewa + Claude  
**Status:** Zatwierdzony

---

## Cel

Zbudowanie struktury projektu Next.js dla strony wizytówkowej kancelarii adwokackiej Artura Borzewskiego. Istniejący komponent React/Tailwind (`Arturborzewski/strona`) zostaje osadzony w pełnym projekcie gotowym do deploymentu na home.pl (hosting współdzielony, Apache, FTP).

---

## Stack

- **Framework:** Next.js 14+ z App Router
- **Styling:** Tailwind CSS
- **Język:** TypeScript
- **Formularz:** PHP mailer (`contact.php`) na home.pl — dane nie opuszczają PL, RODO-compliant
- **Hosting:** home.pl serwer biznes (shared hosting, Apache, FTP upload)
- **Deploy workflow:** `npm run build` → folder `out/` → FTP do `public_html/`

---

## Struktura plików

```
Arturborzewski/
├── app/
│   ├── layout.tsx        ← <html>, metadata SEO, fonty, JSON-LD LegalService schema
│   ├── page.tsx          ← główny komponent strony, dane z content/site.json
│   └── globals.css       ← @tailwind directives
├── content/
│   └── site.json         ← wszystkie teksty, email, telefon, dane kancelarii
├── public/
│   ├── images/
│   │   ├── logo.png
│   │   ├── hero-lawyer.jpg
│   │   ├── mecenas-artur.jpg
│   │   └── cases/
│   │       ├── case-1.jpg
│   │       ├── case-2.jpg
│   │       └── case-3.jpg
│   ├── contact.php       ← PHP mailer, trafia do out/ przy buildzie
│   ├── robots.txt
│   └── .htaccess         ← HTTPS force, www redirect, 404, cache, security headers
├── next.config.js
├── package.json
├── tailwind.config.js
├── postcss.config.js
├── tsconfig.json
└── README.md             ← instrukcja: zdjęcia, build, FTP upload
```

---

## Konfiguracja Next.js

```js
// next.config.js
const nextConfig = {
  output: 'export',
  images: { unoptimized: true },
  trailingSlash: true,        // wymagane dla Apache (szuka /slug/index.html)
}
```

`trailingSlash: true` jest krytyczne — bez tego Apache zwraca 404 na podstronach szukając pliku zamiast katalogu.

---

## content/site.json

Plik JSON z wszystkimi edytowalnymi treściami. Artur edytuje JSON zamiast JSX.

```json
{
  "kancelaria": {
    "nazwa": "Kancelaria Adwokacka Artur Borzewski",
    "email": "kontakt@borzewski-legal.pl",
    "biuro": "biuro@borzewski-legal.pl",
    "telefon": "+48 000 000 000"
  },
  "specjalizacje": [
    "Prawo karne",
    "Prawo gospodarcze",
    "Prawo cywilne",
    "Negocjacje i umowy",
    "Compliance",
    "Cyberbezpieczeństwo"
  ],
  "realizacje": [
    "Reprezentacja przedsiębiorcy w sporze gospodarczym",
    "Negocjacje zakończone ugodą",
    "Stała obsługa prawna nowoczesnych przedsiębiorstw"
  ]
}
```

---

## Formularz kontaktowy — contact.php

Natywny HTML form w JSX z `action="/contact.php" method="POST"`. Plik `contact.php` siedzi w `public/` i trafia do `out/` przy buildzie.

`contact.php` implementuje:
- PHPMailer + SMTP kancelarii (nie natywny `mail()` — home.pl może blokować)
- Walidacja pól po stronie serwera
- Honeypot field (spam protection)
- Rate limiting przez PHP session
- Odpowiedź JSON (`success: true/false`) — redirect JS po submit

---

## .htaccess

```apache
# Force HTTPS
RewriteEngine On
RewriteCond %{HTTPS} off
RewriteRule ^(.*)$ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]

# www → non-www (lub odwrotnie — dostosować do domeny)
RewriteCond %{HTTP_HOST} ^www\.(.+)$ [NC]
RewriteRule ^ https://%1%{REQUEST_URI} [R=301,L]

# 404
ErrorDocument 404 /404.html

# Security headers
Header always set X-Content-Type-Options nosniff
Header always set X-Frame-Options SAMEORIGIN
Header always set Referrer-Policy strict-origin-when-cross-origin

# Cache dla statycznych assetów Next.js (1 rok)
<FilesMatch "\.(js|css|woff2|png|jpg|webp)$">
  Header set Cache-Control "public, max-age=31536000, immutable"
</FilesMatch>
```

---

## SEO

W `app/layout.tsx`:
- `<title>`, `<meta description>`, `og:*` tagi
- JSON-LD schema `LegalService` (pomaga w Google)
- `canonical` URL

Pliki w `public/`:
- `robots.txt` — `Allow: /`, `Sitemap:` pointer
- `sitemap.xml` — ręcznie (jedna strona, zero zależności)

---

## Workflow Artura

### Dodanie/zmiana zdjęcia
1. Wrzuć plik do `Arturborzewski/public/images/`
2. `npm run build`
3. FTP: wgraj `out/` do `public_html/`

### Zmiana tekstu (specjalizacje, telefon, email itp.)
1. Otwórz `Arturborzewski/content/site.json`
2. Zmień wartość
3. `npm run build` → FTP

### Zmiana wyglądu
1. Edytuj `app/page.tsx`
2. `npm run build` → FTP

---

## Decyzje projektowe

| Decyzja | Wybór | Powód |
|---------|-------|-------|
| Formularz | PHP mailer (nie Formspree) | RODO — dane klientów nie opuszczają PL |
| Static export | `output: 'export'` | home.pl = shared hosting, brak Node.js na serwerze |
| App Router | Tak | Spójność z istniejącym komponentem |
| Treści | content/site.json | Artur może edytować bez dotykania JSX |
| Analytics | Brak w v1 | Zero trackerów = zero bannera cookies |

---

## Poza zakresem v1

- CMS (TinaCMS, Decap) — można dołożyć w v2 jeśli Artur będzie często edytował
- GitHub Actions auto-deploy przez FTP — można dołożyć w v2
- Podstrony (blog, aktualności) — nie w tym projekcie
- Wielojęzyczność (EN) — nie w tym projekcie
