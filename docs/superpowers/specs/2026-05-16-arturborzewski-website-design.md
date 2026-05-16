# Design: Arturborzewski — strona wizytówkowa Next.js

**Data:** 2026-05-16  
**Autor:** Damian Kostrzewa + Claude  
**Status:** Zatwierdzony (rev 2 — po review Opus)

---

## Cel

Zbudowanie struktury projektu Next.js dla strony wizytówkowej kancelarii adwokackiej Artura Borzewskiego. Istniejący komponent React/Tailwind (`Arturborzewski/strona`) zostaje osadzony w pełnym projekcie gotowym do deploymentu na home.pl (hosting współdzielony, Apache, FTP).

---

## Stack

- **Framework:** Next.js 14+ z App Router
- **Styling:** Tailwind CSS
- **Język:** TypeScript
- **Formularz:** PHP mailer (`contact.php`) + Cloudflare Turnstile — dane nie opuszczają PL, RODO-compliant
- **Hosting:** home.pl serwer biznes (shared hosting, Apache, FTP upload)
- **Deploy workflow:** `npm run build` → folder `out/` → FTP do `public_html/`

---

## Struktura plików

```
Arturborzewski/
├── app/
│   ├── layout.tsx              ← <html>, metadata SEO, fonty (preload + display:swap), JSON-LD
│   ├── page.tsx                ← komponent strony, dane z content/site.json
│   └── globals.css             ← @tailwind directives
├── app/prawo-karne/
│   └── page.tsx                ← podstrona SEO (opcja — patrz Decyzje)
├── app/prawo-gospodarcze/
│   └── page.tsx
├── app/kontakt/
│   └── page.tsx
├── content/
│   └── site.json               ← teksty, dane kontaktowe, adres, godziny, NIP
├── public/
│   ├── images/
│   │   ├── logo.png
│   │   ├── hero-lawyer.jpg
│   │   ├── mecenas-artur.jpg
│   │   └── cases/
│   │       ├── case-1.jpg
│   │       ├── case-2.jpg
│   │       └── case-3.jpg
│   ├── favicon.ico
│   ├── apple-touch-icon.png
│   ├── site.webmanifest
│   ├── contact.php             ← PHP mailer (PHPMailer + SMTP), trafia do out/
│   ├── robots.txt
│   ├── sitemap.xml             ← ręcznie (jedna strona → kilka wpisów)
│   ├── .htaccess               ← HTTPS, www, 404, cache, security headers, CSP
│   └── .well-known/
│       └── security.txt        ← profesjonalny sygnał dla kancelarii
├── scripts/
│   └── optimize-images.mjs    ← pre-build: sharp → WebP + resize
├── next.config.js
├── package.json
├── tailwind.config.js
├── postcss.config.js
├── tsconfig.json
└── README.md                   ← instrukcja: zdjęcia, build, FTP upload
```

---

## Konfiguracja Next.js

```js
// next.config.js
const nextConfig = {
  output: 'export',
  images: { unoptimized: true },
  trailingSlash: true,               // Apache szuka /slug/index.html
  skipTrailingSlashRedirect: true,   // unika podwójnych redirectów Apache↔Next
}
```

---

## content/site.json

Artur edytuje JSON zamiast JSX. Zawiera wszystkie zmienne dane.

```json
{
  "kancelaria": {
    "nazwa": "Kancelaria Adwokacka Artur Borzewski",
    "email": "kontakt@borzewski-legal.pl",
    "biuro": "biuro@borzewski-legal.pl",
    "telefon": "+48 000 000 000",
    "nip": "000-000-00-00",
    "adres": "ul. Przykładowa 1, 00-000 Warszawa",
    "miasto": "Warszawa",
    "godziny": "Pon–Pt 9:00–17:00"
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

Formularz w JSX: `<form action="/contact.php" method="POST">`. Plik PHP w `public/` trafia do `out/` przy buildzie.

### Zabezpieczenia (w kolejności wdrożenia)

1. **Cloudflare Turnstile** — CAPTCHA bez irytacji, privacy-friendly, darmowa. Token z JS weryfikowany w PHP.
2. **CSRF token** — generowany w sesji PHP, osadzony w hidden input, walidowany przy POST.
3. **Honeypot field** — ukryte pole, wypełnione = bot.
4. **Rate limiting** — przez PHP session (max 3 wysyłki / 10 min).
5. **Server-side walidacja** — whitelist pól, sanityzacja.

### PHPMailer SMTP config

```php
$mail->Host       = 'smtp.home.pl';   // lub SMTP kancelarii
$mail->Port       = 587;
$mail->SMTPSecure = PHPMailer::ENCRYPTION_STARTTLS;
$mail->Timeout    = 10;
// Logowanie błędów do pliku (nie do output — produkcja)
$mail->SMTPDebug  = SMTP::DEBUG_OFF;
error_log($e->getMessage(), 3, __DIR__ . '/mail_error.log');
```

Brak logu = debugging koszmar na home.pl.

---

## .htaccess

```apache
# Force HTTPS
RewriteEngine On
RewriteCond %{HTTPS} off
RewriteRule ^(.*)$ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]

# www → non-www (dostosować do domeny)
RewriteCond %{HTTP_HOST} ^www\.(.+)$ [NC]
RewriteRule ^ https://%1%{REQUEST_URI} [R=301,L]

# 404
ErrorDocument 404 /404.html

# Ukryj wersję serwera
ServerSignature Off

# Security headers
Header always set X-Content-Type-Options "nosniff"
Header always set X-Frame-Options "SAMEORIGIN"
Header always set Referrer-Policy "strict-origin-when-cross-origin"
Header always set Permissions-Policy "camera=(), microphone=(), geolocation=()"
Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"
Header set Content-Security-Policy "default-src 'self'; script-src 'self' https://challenges.cloudflare.com; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; frame-src https://challenges.cloudflare.com;"

# Cache: statyczne assety Next.js (1 rok)
<FilesMatch "\.(js|css|woff2|webp|png|jpg|ico)$">
  Header set Cache-Control "public, max-age=31536000, immutable"
</FilesMatch>

# Nie cache'uj HTML
<FilesMatch "\.html$">
  Header set Cache-Control "no-cache, must-revalidate"
</FilesMatch>
```

CSP zawiera `challenges.cloudflare.com` dla Turnstile.

---

## SEO

### layout.tsx — metadata

```ts
export const metadata: Metadata = {
  title: 'Adwokat Artur Borzewski | Kancelaria Adwokacka Warszawa',
  description: 'Kancelaria adwokacka w Warszawie. Prawo karne, gospodarcze, cywilne...',
  keywords: 'adwokat Warszawa, prawo gospodarcze, prawo karne, kancelaria adwokacka',
}
```

### JSON-LD — LegalService (rozszerzony)

```json
{
  "@type": "LegalService",
  "name": "Kancelaria Adwokacka Artur Borzewski",
  "areaServed": "Warszawa",
  "address": { "@type": "PostalAddress", "addressLocality": "Warszawa", "addressCountry": "PL" },
  "geo": { "@type": "GeoCoordinates", "latitude": "52.2297", "longitude": "21.0122" },
  "openingHours": "Mo-Fr 09:00-17:00",
  "telephone": "+48000000000",
  "url": "https://borzewski-legal.pl"
}
```

### Pliki w public/

- `robots.txt` — Allow all + Sitemap pointer
- `sitemap.xml` — strona główna + podstrony specjalizacji (jeśli wdrożone)
- `.well-known/security.txt` — profesjonalny sygnał

---

## Optymalizacja obrazów — scripts/optimize-images.mjs

Pre-build script (sharp):
- Konwersja do WebP
- Resize hero → max 1920px
- Resize cases → max 800px
- Zachowanie oryginałów

```json
// package.json scripts
"prebuild": "node scripts/optimize-images.mjs",
"build": "next build"
```

---

## Fonty — performance

W `layout.tsx` lub `globals.css`:
```css
@font-face {
  font-display: swap;   /* tekst widoczny przed załadowaniem fonta */
}
```

W `<head>` (layout.tsx):
```html
<link rel="preload" href="/fonts/serif.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
```

---

## UX — sticky CTA mobile

Na mobile (< lg) przyklejony pasek na dole:

```jsx
<div className="fixed bottom-0 left-0 right-0 lg:hidden z-50 bg-black border-t border-white/10 p-4 flex gap-3">
  <a href="tel:+48000000000" className="flex-1 bg-yellow-500 text-black text-center py-3 rounded-full font-semibold">
    Zadzwoń
  </a>
  <a href="#contact" className="flex-1 border border-yellow-500/40 text-center py-3 rounded-full">
    Napisz
  </a>
</div>
```

---

## Deployment

### v1 — ręczny FTP
1. `npm run build` → `out/`
2. FTP: wgraj `out/` → `public_html/`

### v2 — GitHub Actions (opcja po uruchomieniu)

```yaml
# .github/workflows/deploy.yml
on: push: branches: [main]
jobs:
  deploy:
    steps:
      - npm run build
      - FTP upload out/ → home.pl (via SamKirkland/FTP-Deploy-Action)
```

Daje: rollback przez git, wersjonowanie, staging branch.

---

## Decyzje projektowe

| Decyzja | Wybór | Powód |
|---------|-------|-------|
| Formularz | PHP mailer (nie Formspree) | RODO — dane klientów nie opuszczają PL |
| CAPTCHA | Cloudflare Turnstile | Privacy-friendly, darmowy, UX lepszy niż reCAPTCHA |
| Static export | `output: 'export'` | home.pl = shared hosting, brak Node.js na serwerze |
| skipTrailingSlashRedirect | true | Unika podwójnych redirectów Apache↔Next |
| App Router | Tak | Spójność z istniejącym komponentem |
| Treści | content/site.json | Artur edytuje bez dotykania JSX |
| Analytics | Brak w v1 | Zero trackerów = zero bannera cookies |
| Podstrony SEO | v1 — szkielety | Lepsze pozycjonowanie od razu, content rozbudowany w v2 |

---

## Otwarta decyzja: podstrony SEO

Opus wskazał, że dla kancelarii lokalne SEO przez podstrony (`/prawo-karne/`, `/prawo-gospodarcze/`, `/kontakt/`) może mieć większy wpływ niż frontend.

**Za v1 z podstronami:** lepsze pozycjonowanie od razu, Google indeksuje specjalizacje osobno.  
**Za v1 bez podstron:** szybszy start, treści można rozbudować w v2 gdy Artur dostarczy content.

**Decyzja:** szkielety podstron w v1 (`/prawo-karne/`, `/prawo-gospodarcze/`, `/kontakt/`). Content rozbudowany w v2 gdy Artur dostarczy teksty.

---

## Poza zakresem v1

- CMS (TinaCMS, Decap) — v2 jeśli Artur często edytuje
- GitHub Actions auto-deploy — v2
- Wielojęzyczność (EN) — nie w tym projekcie
- Blog / aktualności — nie w tym projekcie
- Plausible Analytics — opcja v2
