# Arturborzewski — strona wizytówkowa Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zbudować kompletny projekt Next.js static-export w `Arturborzewski/` gotowy do wgrania przez FTP na home.pl — strona wizytówkowa kancelarii adwokackiej z formularzem PHP, zabezpieczeniami, SEO i podstronami specjalizacji.

**Architecture:** Next.js 14 App Router z `output: 'export'` generuje statyczne pliki HTML/CSS/JS do folderu `out/`. Treści edytowalne przechowywane w `content/site.json` (Artur edytuje JSON, nie JSX). Formularz kontaktowy przez `contact.php` (PHPMailer + Turnstile + CSRF) — dane nie opuszczają PL. Trzy podstrony SEO (`/prawo-karne/`, `/prawo-gospodarcze/`, `/kontakt/`) jako szkielety.

**Tech Stack:** Next.js 14, React 18, TypeScript, Tailwind CSS 3, PHPMailer 6, Cloudflare Turnstile, sharp (optymalizacja obrazów)

---

## Mapa plików

| Plik | Rola |
|------|------|
| `Arturborzewski/package.json` | Zależności i skrypty npm |
| `Arturborzewski/next.config.js` | `output: 'export'`, trailingSlash, skipTrailingSlashRedirect |
| `Arturborzewski/tsconfig.json` | TypeScript config |
| `Arturborzewski/tailwind.config.js` | Tailwind — scan app/ |
| `Arturborzewski/postcss.config.js` | PostCSS dla Tailwind |
| `Arturborzewski/app/globals.css` | @tailwind directives |
| `Arturborzewski/app/layout.tsx` | HTML shell, metadata SEO, JSON-LD, fonty |
| `Arturborzewski/app/page.tsx` | Strona główna (z pliku `strona`), dane z site.json |
| `Arturborzewski/app/prawo-karne/page.tsx` | Podstrona SEO — szkielet |
| `Arturborzewski/app/prawo-gospodarcze/page.tsx` | Podstrona SEO — szkielet |
| `Arturborzewski/app/kontakt/page.tsx` | Podstrona kontakt — szkielet |
| `Arturborzewski/content/site.json` | Wszystkie edytowalne dane kancelarii |
| `Arturborzewski/public/contact.php` | PHPMailer + Turnstile + CSRF + honeypot |
| `Arturborzewski/public/get-csrf.php` | Generuje CSRF token (PHP session) |
| `Arturborzewski/public/.htaccess` | HTTPS, www, 404, headers, cache, CSP |
| `Arturborzewski/public/robots.txt` | Allow all + sitemap |
| `Arturborzewski/public/sitemap.xml` | Strona główna + podstrony |
| `Arturborzewski/public/.well-known/security.txt` | Security contact |
| `Arturborzewski/public/site.webmanifest` | PWA manifest |
| `Arturborzewski/scripts/optimize-images.mjs` | Pre-build: sharp → WebP + resize |
| `Arturborzewski/README.md` | Instrukcja dla Artura |

---

## Task 1: Scaffold projektu Next.js

**Files:**
- Create: `Arturborzewski/package.json`
- Create: `Arturborzewski/next.config.js`
- Create: `Arturborzewski/tsconfig.json`
- Create: `Arturborzewski/tailwind.config.js`
- Create: `Arturborzewski/postcss.config.js`

- [ ] **Step 1: Utwórz `package.json`**

```json
{
  "name": "borzewski-legal",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "prebuild": "node scripts/optimize-images.mjs",
    "build": "next build",
    "start": "next start"
  },
  "dependencies": {
    "next": "^14.2.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0"
  },
  "devDependencies": {
    "@types/node": "^20",
    "@types/react": "^18",
    "@types/react-dom": "^18",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0",
    "sharp": "^0.33.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5"
  }
}
```

- [ ] **Step 2: Utwórz `next.config.js`**

```js
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  images: { unoptimized: true },
  trailingSlash: true,
  skipTrailingSlashRedirect: true,
}

module.exports = nextConfig
```

- [ ] **Step 3: Utwórz `tsconfig.json`**

```json
{
  "compilerOptions": {
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 4: Utwórz `tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: { extend: {} },
  plugins: [],
}
```

- [ ] **Step 5: Utwórz `postcss.config.js`**

```js
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

- [ ] **Step 6: Zainstaluj zależności**

```bash
cd Arturborzewski
npm install
```

Oczekiwane: instalacja bez błędów, pojawi się `node_modules/`.

- [ ] **Step 7: Commit**

```bash
git add Arturborzewski/package.json Arturborzewski/package-lock.json Arturborzewski/next.config.js Arturborzewski/tsconfig.json Arturborzewski/tailwind.config.js Arturborzewski/postcss.config.js
git commit -m "feat(borzewski): scaffold Next.js project"
```

---

## Task 2: content/site.json — dane kancelarii

**Files:**
- Create: `Arturborzewski/content/site.json`

- [ ] **Step 1: Utwórz `content/site.json`**

```json
{
  "kancelaria": {
    "nazwa": "Kancelaria Adwokacka Artur Borzewski",
    "email": "kontakt@borzewski-legal.pl",
    "biuro": "biuro@borzewski-legal.pl",
    "telefon": "+48 000 000 000",
    "telefonRaw": "+48000000000",
    "nip": "000-000-00-00",
    "adres": "ul. Przykładowa 1, 00-000 Warszawa",
    "miasto": "Warszawa",
    "godziny": "Pon–Pt 9:00–17:00",
    "url": "https://borzewski-legal.pl",
    "lat": "52.2297",
    "lng": "21.0122"
  },
  "specjalizacje": [
    { "slug": "prawo-karne", "nazwa": "Prawo karne", "opis": "Obrona w postępowaniu karnym, reprezentacja pokrzywdzonych, sprawy gospodarcze z elementem karnym." },
    { "slug": "prawo-gospodarcze", "nazwa": "Prawo gospodarcze", "opis": "Obsługa prawna przedsiębiorców, spory gospodarcze, umowy handlowe, restrukturyzacje." },
    { "slug": "prawo-cywilne", "nazwa": "Prawo cywilne", "opis": "Sprawy majątkowe, odszkodowania, spory z zakresu prawa cywilnego." },
    { "slug": "negocjacje-i-umowy", "nazwa": "Negocjacje i umowy", "opis": "Przygotowanie i opiniowanie umów, negocjacje kontraktów, ugody pozasądowe." },
    { "slug": "compliance", "nazwa": "Compliance", "opis": "Wdrożenia procedur compliance, AML, RODO, audyty prawne przedsiębiorstw." },
    { "slug": "cyberbezpieczenstwo", "nazwa": "Cyberbezpieczeństwo", "opis": "Obsługa prawna incydentów cybernetycznych, ochrona danych osobowych, regulacje IT." }
  ],
  "aiFeatures": [
    "AI-assisted workflow",
    "Bezpieczny obieg dokumentów",
    "Konsultacje online",
    "Szyfrowana komunikacja"
  ],
  "realizacje": [
    "Reprezentacja przedsiębiorcy w sporze gospodarczym",
    "Negocjacje zakończone ugodą",
    "Stała obsługa prawna nowoczesnych przedsiębiorstw"
  ],
  "seo": {
    "tytul": "Adwokat Artur Borzewski | Kancelaria Adwokacka Warszawa",
    "opis": "Kancelaria adwokacka w Warszawie. Prawo karne, gospodarcze, cywilne. Profesjonalna i dyskretna obsługa prawna klientów indywidualnych i przedsiębiorców.",
    "slowa": "adwokat Warszawa, prawo gospodarcze Warszawa, prawo karne, kancelaria adwokacka, obsługa prawna przedsiębiorców"
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add Arturborzewski/content/site.json
git commit -m "feat(borzewski): add site.json with all editable content"
```

---

## Task 3: app/globals.css + app/layout.tsx

**Files:**
- Create: `Arturborzewski/app/globals.css`
- Create: `Arturborzewski/app/layout.tsx`

- [ ] **Step 1: Utwórz `app/globals.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 2: Utwórz `app/layout.tsx`**

```tsx
import type { Metadata } from 'next'
import { Playfair_Display, Inter } from 'next/font/google'
import './globals.css'
import site from '../content/site.json'

const inter = Inter({
  subsets: ['latin', 'latin-ext'],
  variable: '--font-inter',
  display: 'swap',
})

const playfair = Playfair_Display({
  subsets: ['latin', 'latin-ext'],
  variable: '--font-playfair',
  display: 'swap',
})

export const metadata: Metadata = {
  title: site.seo.tytul,
  description: site.seo.opis,
  keywords: site.seo.slowa,
  metadataBase: new URL(site.kancelaria.url),
  openGraph: {
    title: site.seo.tytul,
    description: site.seo.opis,
    url: site.kancelaria.url,
    siteName: site.kancelaria.nazwa,
    locale: 'pl_PL',
    type: 'website',
  },
  alternates: {
    canonical: site.kancelaria.url,
  },
}

const jsonLd = {
  '@context': 'https://schema.org',
  '@type': 'LegalService',
  name: site.kancelaria.nazwa,
  url: site.kancelaria.url,
  telephone: site.kancelaria.telefonRaw,
  email: site.kancelaria.email,
  areaServed: site.kancelaria.miasto,
  address: {
    '@type': 'PostalAddress',
    streetAddress: site.kancelaria.adres,
    addressLocality: site.kancelaria.miasto,
    addressCountry: 'PL',
  },
  geo: {
    '@type': 'GeoCoordinates',
    latitude: site.kancelaria.lat,
    longitude: site.kancelaria.lng,
  },
  openingHours: 'Mo-Fr 09:00-17:00',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pl" className={`${inter.variable} ${playfair.variable}`}>
      <head>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <link rel="manifest" href="/site.webmanifest" />
      </head>
      <body className={`${inter.className} antialiased`}>{children}</body>
    </html>
  )
}
```

- [ ] **Step 3: Zaktualizuj `tailwind.config.js` — zmapuj fonty**

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-inter)', 'ui-sans-serif', 'system-ui'],
        serif: ['var(--font-playfair)', 'ui-serif', 'Georgia'],
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 4: Sprawdź TypeScript**

```bash
cd Arturborzewski && npx tsc --noEmit
```

Oczekiwane: brak błędów.

- [ ] **Step 5: Commit**

```bash
git add Arturborzewski/app/globals.css Arturborzewski/app/layout.tsx Arturborzewski/tailwind.config.js
git commit -m "feat(borzewski): layout with metadata, JSON-LD, Google Fonts"
```

---

## Task 4: app/page.tsx — strona główna

**Files:**
- Create: `Arturborzewski/app/page.tsx`

Portujemy komponent z `Arturborzewski/strona`. Zmiany:
- Dane z `site.json` zamiast hardkodowanych tablic
- `font-serif` i `font-sans` działają przez zmapowane zmienne (Task 3)
- Dodajemy sticky CTA na mobile
- Formularz kontaktowy przekształcamy na natywny HTML z Turnstile + CSRF

- [ ] **Step 1: Utwórz `app/page.tsx`**

```tsx
import site from '../content/site.json'
import ContactForm from './ContactForm'

export default function HomePage() {
  return (
    <div className="min-h-screen bg-black text-white font-sans overflow-x-hidden">

      {/* STICKY MOBILE CTA */}
      <div className="fixed bottom-0 left-0 right-0 lg:hidden z-50 bg-black/95 border-t border-white/10 p-4 flex gap-3">
        <a
          href={`tel:${site.kancelaria.telefonRaw}`}
          className="flex-1 bg-yellow-500 text-black text-center py-3 rounded-full font-semibold text-sm"
        >
          Zadzwoń
        </a>
        <a
          href="#contact"
          className="flex-1 border border-yellow-500/40 text-center py-3 rounded-full text-sm"
        >
          Napisz
        </a>
      </div>

      {/* HEADER */}
      <header className="fixed top-0 left-0 w-full z-50 backdrop-blur-xl bg-black/60 border-b border-white/5">
        <div className="max-w-7xl mx-auto px-6 h-24 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <img
              src="/images/logo.png"
              alt={site.kancelaria.nazwa}
              className="h-16 w-auto object-contain"
              onError={(e) => { e.currentTarget.style.display = 'none' }}
            />
            <div className="w-14 h-14 rounded-full border border-yellow-500/40 flex items-center justify-center text-yellow-400 text-2xl font-serif bg-black">
              AB
            </div>
          </div>

          <nav className="hidden lg:flex items-center gap-10 text-sm tracking-wide">
            <a href="#about" className="hover:text-yellow-400 transition duration-300">O kancelarii</a>
            <a href="#services" className="hover:text-yellow-400 transition duration-300">Specjalizacje</a>
            <a href="#technology" className="hover:text-yellow-400 transition duration-300">Technologie</a>
            <a href="#cases" className="hover:text-yellow-400 transition duration-300">Realizacje</a>
            <a href="#contact" className="hover:text-yellow-400 transition duration-300">Kontakt</a>
          </nav>

          <div className="flex items-center gap-4">
            <a
              href="#contact"
              className="hidden lg:block bg-yellow-500 text-black px-6 py-3 rounded-full font-medium hover:scale-105 transition duration-300 shadow-[0_0_40px_rgba(234,179,8,0.15)]"
            >
              Konsultacja
            </a>
            <button className="lg:hidden flex flex-col gap-1.5" aria-label="Menu">
              <span className="w-7 h-[2px] bg-yellow-400 rounded-full"></span>
              <span className="w-7 h-[2px] bg-yellow-400 rounded-full"></span>
              <span className="w-7 h-[2px] bg-yellow-400 rounded-full"></span>
            </button>
          </div>
        </div>
      </header>

      {/* HERO */}
      <section className="relative min-h-screen flex items-center pt-32">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(234,179,8,0.15),transparent_35%)]"></div>
        <div className="max-w-7xl mx-auto px-6 grid lg:grid-cols-2 gap-20 items-center relative z-10">
          <div>
            <div className="text-yellow-500 tracking-[0.4em] uppercase text-sm mb-8">
              Nowoczesna kancelaria prawna
            </div>
            <h1 className="text-5xl md:text-7xl font-serif leading-none mb-8">
              Strategia.<br />Dyskrecja.<br />Skuteczność.
            </h1>
            <p className="text-zinc-400 text-lg leading-8 max-w-xl mb-10">
              {site.kancelaria.nazwa} zapewnia kompleksową obsługę prawną klientów
              indywidualnych oraz przedsiębiorców.
            </p>
            <div className="flex flex-col sm:flex-row gap-5">
              <a href="#contact" className="bg-yellow-500 text-black px-8 py-4 rounded-full font-semibold hover:scale-105 transition duration-300 text-center">
                Skontaktuj się
              </a>
              <a href="#services" className="border border-white/10 px-8 py-4 rounded-full hover:border-yellow-500/40 transition duration-300 text-center">
                Zakres usług
              </a>
            </div>
          </div>

          <div className="relative flex justify-center">
            <div className="absolute w-96 h-96 bg-yellow-500/10 blur-3xl rounded-full"></div>
            <div className="relative border border-yellow-500/20 bg-white/5 backdrop-blur-2xl rounded-[40px] p-6 shadow-2xl max-w-xl w-full hover:scale-[1.01] transition duration-700">
              <img
                src="/images/hero-lawyer.jpg"
                alt={site.kancelaria.nazwa}
                className="rounded-[32px] w-full h-[700px] object-cover"
              />
              <div className="absolute inset-0 rounded-[32px] bg-gradient-to-t from-black/60 via-transparent to-transparent"></div>
              <div className="absolute bottom-10 left-10">
                <div className="text-yellow-400 tracking-[0.3em] uppercase text-sm mb-3">Kancelaria Adwokacka</div>
                <div className="text-4xl font-serif">Artur Borzewski</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ABOUT */}
      <section id="about" className="py-32 border-t border-white/5">
        <div className="max-w-7xl mx-auto px-6 grid lg:grid-cols-2 gap-20 items-start">
          <div>
            <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">O kancelarii</div>
            <h2 className="text-4xl md:text-6xl font-serif leading-tight">
              Nowoczesne podejście do obsługi prawnej.
            </h2>
          </div>
          <div className="space-y-8 text-zinc-400 leading-8 text-lg">
            <p>
              Kancelaria została zaprojektowana z myślą o klientach oczekujących
              skuteczności, transparentności i sprawnej komunikacji.
            </p>
            <p>
              Wykorzystujemy nowoczesne rozwiązania technologiczne wspierające
              analizę dokumentów oraz bezpieczny obieg informacji.
            </p>
            <div className="text-zinc-500 text-sm space-y-1">
              <div>{site.kancelaria.adres}</div>
              <div>{site.kancelaria.godziny}</div>
              <div>NIP: {site.kancelaria.nip}</div>
            </div>
          </div>
        </div>
      </section>

      {/* SERVICES */}
      <section id="services" className="py-32 bg-zinc-950 border-y border-white/5">
        <div className="max-w-7xl mx-auto px-6">
          <div className="mb-20">
            <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Specjalizacje</div>
            <h2 className="text-4xl md:text-6xl font-serif">Zakres obsługi kancelarii</h2>
          </div>
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-8">
            {site.specjalizacje.map((item) => (
              <a
                key={item.slug}
                href={`/${item.slug}/`}
                className="group rounded-[30px] border border-white/5 bg-white/[0.02] p-10 hover:border-yellow-500/30 hover:-translate-y-2 transition duration-500"
              >
                <div className="w-14 h-14 rounded-2xl bg-yellow-500/10 border border-yellow-500/20 mb-8 flex items-center justify-center text-yellow-400 text-xl">
                  ✦
                </div>
                <h3 className="text-2xl font-serif mb-5 group-hover:text-yellow-400 transition">
                  {item.nazwa}
                </h3>
                <p className="text-zinc-400 leading-7">{item.opis}</p>
              </a>
            ))}
          </div>
        </div>
      </section>

      {/* TECHNOLOGY */}
      <section id="technology" className="py-32 relative overflow-hidden">
        <div className="absolute right-0 top-0 w-[500px] h-[500px] bg-yellow-500/10 blur-3xl rounded-full"></div>
        <div className="max-w-7xl mx-auto px-6 relative z-10 grid lg:grid-cols-2 gap-20 items-center">
          <div>
            <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Technologie AI</div>
            <h2 className="text-4xl md:text-6xl font-serif mb-10 leading-tight">
              Kancelaria wspierana nowoczesnymi rozwiązaniami.
            </h2>
            <p className="text-zinc-400 text-lg leading-8">
              Bezpieczna analiza dokumentów, cyfrowy obieg spraw, szyfrowana komunikacja
              oraz rozwiązania AI wspierające efektywność obsługi klientów.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 gap-6">
            {site.aiFeatures.map((item) => (
              <div
                key={item}
                className="rounded-[28px] border border-yellow-500/10 bg-gradient-to-b from-white/[0.03] to-white/[0.01] p-8 min-h-[180px] flex items-end text-xl font-light"
              >
                {item}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CASES */}
      <section id="cases" className="py-32 bg-zinc-950 border-y border-white/5">
        <div className="max-w-7xl mx-auto px-6">
          <div className="mb-20">
            <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Realizacje</div>
            <h2 className="text-4xl md:text-6xl font-serif">Wybrane obszary działań</h2>
          </div>
          <div className="grid lg:grid-cols-3 gap-8">
            {site.realizacje.map((item, index) => (
              <div key={item} className="rounded-[30px] overflow-hidden border border-white/5 bg-black">
                <img
                  src={`/images/cases/case-${index + 1}.jpg`}
                  alt={item}
                  className="w-full h-72 object-cover"
                />
                <div className="p-8">
                  <div className="text-yellow-500 uppercase tracking-[0.3em] text-xs mb-4">Case Study</div>
                  <h3 className="text-2xl font-serif leading-relaxed">{item}</h3>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CONTACT */}
      <section id="contact" className="py-32 pb-40 lg:pb-32">
        <div className="max-w-7xl mx-auto px-6 grid lg:grid-cols-2 gap-20 items-start">
          <div>
            <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Kontakt</div>
            <h2 className="text-4xl md:text-6xl font-serif mb-10 leading-tight">
              Skontaktuj się z kancelarią.
            </h2>
            <div className="space-y-10 text-lg">
              <div>
                <div className="text-yellow-500 mb-2 uppercase tracking-[0.2em] text-sm">Email kancelarii</div>
                <a href={`mailto:${site.kancelaria.email}`} className="text-zinc-300 hover:text-yellow-400 transition">
                  {site.kancelaria.email}
                </a>
              </div>
              <div>
                <div className="text-yellow-500 mb-2 uppercase tracking-[0.2em] text-sm">Biuro</div>
                <a href={`mailto:${site.kancelaria.biuro}`} className="text-zinc-300 hover:text-yellow-400 transition">
                  {site.kancelaria.biuro}
                </a>
              </div>
              <div>
                <div className="text-yellow-500 mb-2 uppercase tracking-[0.2em] text-sm">Telefon</div>
                <a href={`tel:${site.kancelaria.telefonRaw}`} className="text-zinc-300 hover:text-yellow-400 transition">
                  {site.kancelaria.telefon}
                </a>
              </div>
            </div>
          </div>

          <ContactForm />
        </div>
      </section>

      {/* FOOTER */}
      <footer className="border-t border-white/5 py-10 text-zinc-500">
        <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row justify-between gap-6 text-sm">
          <div>© {new Date().getFullYear()} {site.kancelaria.nazwa}</div>
          <div>Nowoczesna obsługa prawna klientów indywidualnych i biznesowych.</div>
        </div>
      </footer>

    </div>
  )
}
```

- [ ] **Step 2: Utwórz `app/ContactForm.tsx` — formularz z Turnstile + CSRF**

```tsx
'use client'

import { useEffect, useRef, useState } from 'react'
import Script from 'next/script'

export default function ContactForm() {
  const csrfRef = useRef<HTMLInputElement>(null)
  const [status, setStatus] = useState<'idle' | 'sending' | 'success' | 'error'>('idle')

  useEffect(() => {
    // Pobierz CSRF token z PHP przy montowaniu komponentu
    fetch('/get-csrf.php')
      .then(r => r.json())
      .then(data => {
        if (csrfRef.current) csrfRef.current.value = data.token
      })
      .catch(() => {}) // Nie blokuj formularza jeśli PHP niedostępne (dev)
  }, [])

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setStatus('sending')
    const form = e.currentTarget
    const data = new FormData(form)

    try {
      const res = await fetch('/contact.php', { method: 'POST', body: data })
      const json = await res.json()
      setStatus(json.success ? 'success' : 'error')
    } catch {
      setStatus('error')
    }
  }

  return (
    <div className="rounded-[40px] border border-white/5 bg-white/[0.02] p-8 md:p-12 backdrop-blur-xl">
      {status === 'success' ? (
        <div className="text-center py-12">
          <div className="text-yellow-400 text-4xl mb-4">✓</div>
          <p className="text-xl font-serif">Wiadomość wysłana.</p>
          <p className="text-zinc-400 mt-2">Odezwiemy się wkrótce.</p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="grid gap-6">
          {/* CSRF */}
          <input type="hidden" name="csrf_token" ref={csrfRef} />
          {/* Honeypot — ukryte dla ludzi, widoczne dla botów */}
          <input type="text" name="website" className="hidden" tabIndex={-1} autoComplete="off" />

          <input
            name="imie"
            required
            placeholder="Imię i nazwisko"
            className="h-16 rounded-2xl bg-black border border-white/10 px-6 outline-none focus:border-yellow-500/40 text-white"
          />
          <input
            name="email"
            type="email"
            required
            placeholder="Adres e-mail"
            className="h-16 rounded-2xl bg-black border border-white/10 px-6 outline-none focus:border-yellow-500/40 text-white"
          />
          <textarea
            name="wiadomosc"
            required
            rows={6}
            placeholder="Opisz swoją sprawę"
            className="rounded-2xl bg-black border border-white/10 px-6 py-5 outline-none focus:border-yellow-500/40 text-white resize-none"
          />

          {/* Cloudflare Turnstile — sitekey zastąp rzeczywistym po rejestracji */}
          <div
            className="cf-turnstile"
            data-sitekey="0x4AAAAAAA_REPLACE_WITH_REAL_SITEKEY"
            data-theme="dark"
          ></div>

          {/* Checkbox RODO */}
          <label className="flex items-start gap-3 text-sm text-zinc-400 cursor-pointer">
            <input type="checkbox" name="rodo" required className="mt-1 accent-yellow-500" />
            <span>
              Wyrażam zgodę na przetwarzanie moich danych osobowych w celu odpowiedzi na zapytanie,
              zgodnie z{' '}
              <a href="/polityka-prywatnosci/" className="text-yellow-500 hover:underline">
                polityką prywatności
              </a>
              .
            </span>
          </label>

          {status === 'error' && (
            <p className="text-red-400 text-sm">Wystąpił błąd. Proszę spróbować ponownie lub napisać bezpośrednio na email.</p>
          )}

          <button
            type="submit"
            disabled={status === 'sending'}
            className="h-16 rounded-full bg-yellow-500 text-black font-semibold hover:scale-[1.02] transition duration-300 disabled:opacity-60"
          >
            {status === 'sending' ? 'Wysyłanie...' : 'Wyślij wiadomość'}
          </button>
        </form>
      )}

      <Script
        src="https://challenges.cloudflare.com/turnstile/v0/api.js"
        strategy="lazyOnload"
      />
    </div>
  )
}
```

- [ ] **Step 3: Zaktualizuj mapę plików**

Dodaj do `Arturborzewski/app/ContactForm.tsx` w mapie plików. Plik `ContactForm.tsx` jest Client Component (`'use client'`) bo używa `useEffect`/`useState`.

- [ ] **Step 4: Sprawdź TypeScript**

```bash
cd Arturborzewski && npx tsc --noEmit
```

Oczekiwane: brak błędów.

- [ ] **Step 5: Commit**

```bash
git add Arturborzewski/app/page.tsx Arturborzewski/app/ContactForm.tsx
git commit -m "feat(borzewski): main page + ContactForm with Turnstile + CSRF"
```

---

## Task 5: SEO subpages — prawo-karne, prawo-gospodarcze, kontakt

**Files:**
- Create: `Arturborzewski/app/prawo-karne/page.tsx`
- Create: `Arturborzewski/app/prawo-gospodarcze/page.tsx`
- Create: `Arturborzewski/app/kontakt/page.tsx`

Wszystkie trzy strony mają identyczną strukturę. Różnią się tylko danymi — pobieranymi z `site.json`.

- [ ] **Step 1: Utwórz `app/prawo-karne/page.tsx`**

```tsx
import type { Metadata } from 'next'
import site from '../../content/site.json'

const spec = site.specjalizacje.find(s => s.slug === 'prawo-karne')!

export const metadata: Metadata = {
  title: `${spec.nazwa} | ${site.kancelaria.nazwa}`,
  description: `${spec.opis} Kancelaria adwokacka w ${site.kancelaria.miasto}.`,
  alternates: { canonical: `${site.kancelaria.url}/prawo-karne/` },
}

export default function PrawoKarnePage() {
  return (
    <div className="min-h-screen bg-black text-white font-sans">
      <div className="max-w-4xl mx-auto px-6 py-40">
        <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Specjalizacja</div>
        <h1 className="text-5xl md:text-7xl font-serif leading-tight mb-10">{spec.nazwa}</h1>
        <p className="text-zinc-400 text-xl leading-9 mb-16">{spec.opis}</p>

        <div className="border-t border-white/5 pt-16">
          <p className="text-zinc-500 mb-8">
            Kancelaria {site.kancelaria.nazwa} obsługuje sprawy z zakresu {spec.nazwa.toLowerCase()} w{' '}
            {site.kancelaria.miasto} i okolicach.
          </p>
          <a
            href="/#contact"
            className="inline-block bg-yellow-500 text-black px-8 py-4 rounded-full font-semibold hover:scale-105 transition duration-300"
          >
            Umów konsultację
          </a>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Utwórz `app/prawo-gospodarcze/page.tsx`**

```tsx
import type { Metadata } from 'next'
import site from '../../content/site.json'

const spec = site.specjalizacje.find(s => s.slug === 'prawo-gospodarcze')!

export const metadata: Metadata = {
  title: `${spec.nazwa} | ${site.kancelaria.nazwa}`,
  description: `${spec.opis} Kancelaria adwokacka w ${site.kancelaria.miasto}.`,
  alternates: { canonical: `${site.kancelaria.url}/prawo-gospodarcze/` },
}

export default function PrawoGospodarczePage() {
  return (
    <div className="min-h-screen bg-black text-white font-sans">
      <div className="max-w-4xl mx-auto px-6 py-40">
        <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Specjalizacja</div>
        <h1 className="text-5xl md:text-7xl font-serif leading-tight mb-10">{spec.nazwa}</h1>
        <p className="text-zinc-400 text-xl leading-9 mb-16">{spec.opis}</p>

        <div className="border-t border-white/5 pt-16">
          <p className="text-zinc-500 mb-8">
            Kancelaria {site.kancelaria.nazwa} obsługuje sprawy z zakresu {spec.nazwa.toLowerCase()} w{' '}
            {site.kancelaria.miasto} i okolicach.
          </p>
          <a
            href="/#contact"
            className="inline-block bg-yellow-500 text-black px-8 py-4 rounded-full font-semibold hover:scale-105 transition duration-300"
          >
            Umów konsultację
          </a>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Utwórz `app/kontakt/page.tsx`**

```tsx
import type { Metadata } from 'next'
import site from '../../content/site.json'
import ContactForm from '../ContactForm'

export const metadata: Metadata = {
  title: `Kontakt | ${site.kancelaria.nazwa}`,
  description: `Skontaktuj się z kancelarią adwokacką w ${site.kancelaria.miasto}. ${site.kancelaria.telefon}`,
  alternates: { canonical: `${site.kancelaria.url}/kontakt/` },
}

export default function KontaktPage() {
  return (
    <div className="min-h-screen bg-black text-white font-sans">
      <div className="max-w-7xl mx-auto px-6 py-40 grid lg:grid-cols-2 gap-20 items-start">
        <div>
          <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Kontakt</div>
          <h1 className="text-5xl md:text-6xl font-serif mb-10 leading-tight">
            Skontaktuj się z kancelarią.
          </h1>
          <div className="space-y-8 text-lg">
            <div>
              <div className="text-yellow-500 mb-2 uppercase tracking-[0.2em] text-sm">Adres</div>
              <div className="text-zinc-300">{site.kancelaria.adres}</div>
            </div>
            <div>
              <div className="text-yellow-500 mb-2 uppercase tracking-[0.2em] text-sm">Godziny</div>
              <div className="text-zinc-300">{site.kancelaria.godziny}</div>
            </div>
            <div>
              <div className="text-yellow-500 mb-2 uppercase tracking-[0.2em] text-sm">Telefon</div>
              <a href={`tel:${site.kancelaria.telefonRaw}`} className="text-zinc-300 hover:text-yellow-400 transition">
                {site.kancelaria.telefon}
              </a>
            </div>
            <div>
              <div className="text-yellow-500 mb-2 uppercase tracking-[0.2em] text-sm">Email</div>
              <a href={`mailto:${site.kancelaria.email}`} className="text-zinc-300 hover:text-yellow-400 transition">
                {site.kancelaria.email}
              </a>
            </div>
          </div>
        </div>
        <ContactForm />
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Sprawdź TypeScript**

```bash
cd Arturborzewski && npx tsc --noEmit
```

Oczekiwane: brak błędów.

- [ ] **Step 5: Commit**

```bash
git add Arturborzewski/app/prawo-karne Arturborzewski/app/prawo-gospodarcze Arturborzewski/app/kontakt
git commit -m "feat(borzewski): SEO subpages — prawo-karne, prawo-gospodarcze, kontakt"
```

---

## Task 6: PHP backend — contact.php + get-csrf.php

**Files:**
- Create: `Arturborzewski/public/contact.php`
- Create: `Arturborzewski/public/get-csrf.php`

PHPMailer instalujemy przez Composer. Na home.pl Composer jest dostępny. Alternatywnie można dołączyć PHPMailer ręcznie (patrz README).

- [ ] **Step 1: Utwórz `public/get-csrf.php`**

```php
<?php
session_start();

if (empty($_SESSION['csrf_token'])) {
    $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
}

header('Content-Type: application/json');
header('Cache-Control: no-store');
echo json_encode(['token' => $_SESSION['csrf_token']]);
```

- [ ] **Step 2: Utwórz `public/contact.php`**

```php
<?php
session_start();

header('Content-Type: application/json');
header('Cache-Control: no-store');

function respond(bool $success, string $message = ''): void {
    echo json_encode(['success' => $success, 'message' => $message]);
    exit;
}

// Rate limiting — max 3 wysyłki na 10 minut
$now = time();
$window = 600;
$max = 3;
if (!isset($_SESSION['contact_times'])) $_SESSION['contact_times'] = [];
$_SESSION['contact_times'] = array_filter($_SESSION['contact_times'], fn($t) => ($now - $t) < $window);
if (count($_SESSION['contact_times']) >= $max) {
    respond(false, 'Zbyt wiele wiadomości. Spróbuj za chwilę.');
}

// Honeypot
if (!empty($_POST['website'])) respond(false);

// CSRF
if (
    empty($_POST['csrf_token']) ||
    empty($_SESSION['csrf_token']) ||
    !hash_equals($_SESSION['csrf_token'], $_POST['csrf_token'])
) {
    respond(false, 'Błąd weryfikacji. Odśwież stronę i spróbuj ponownie.');
}
// Unieważnij token po użyciu
unset($_SESSION['csrf_token']);

// Turnstile
$turnstileSecret = 'YOUR_TURNSTILE_SECRET_KEY'; // Zastąp po rejestracji na dash.cloudflare.com
$turnstileToken = $_POST['cf-turnstile-response'] ?? '';
$verify = file_get_contents('https://challenges.cloudflare.com/turnstile/v0/siteverify', false, stream_context_create([
    'http' => [
        'method' => 'POST',
        'header' => 'Content-Type: application/x-www-form-urlencoded',
        'content' => http_build_query(['secret' => $turnstileSecret, 'response' => $turnstileToken]),
        'timeout' => 5,
    ],
]));
$verifyData = json_decode($verify, true);
if (empty($verifyData['success'])) {
    respond(false, 'Weryfikacja antyspamowa nieudana.');
}

// Walidacja pól
$imie = trim(strip_tags($_POST['imie'] ?? ''));
$email = filter_var(trim($_POST['email'] ?? ''), FILTER_VALIDATE_EMAIL);
$wiadomosc = trim(strip_tags($_POST['wiadomosc'] ?? ''));

if (!$imie || !$email || !$wiadomosc) {
    respond(false, 'Proszę wypełnić wszystkie pola.');
}
if (strlen($imie) > 100 || strlen($wiadomosc) > 5000) {
    respond(false, 'Dane przekraczają dozwoloną długość.');
}

// PHPMailer
// Wymaga: composer require phpmailer/phpmailer
// lub ręczne wrzucenie PHPMailer do public/PHPMailer/
require_once __DIR__ . '/vendor/autoload.php';

use PHPMailer\PHPMailer\PHPMailer;
use PHPMailer\PHPMailer\SMTP;
use PHPMailer\PHPMailer\Exception;

$mail = new PHPMailer(true);
try {
    $mail->isSMTP();
    $mail->Host       = 'smtp.home.pl';     // Lub SMTP kancelarii
    $mail->SMTPAuth   = true;
    $mail->Username   = 'kontakt@borzewski-legal.pl'; // Zastąp
    $mail->Password   = 'SMTP_PASSWORD';              // Zastąp (zmień w .env lub config)
    $mail->SMTPSecure = PHPMailer::ENCRYPTION_STARTTLS;
    $mail->Port       = 587;
    $mail->Timeout    = 10;
    $mail->SMTPDebug  = SMTP::DEBUG_OFF;
    $mail->CharSet    = 'UTF-8';

    $mail->setFrom('kontakt@borzewski-legal.pl', 'Formularz — Kancelaria Borzewski');
    $mail->addAddress('kontakt@borzewski-legal.pl', 'Kancelaria Borzewski');
    $mail->addReplyTo($email, $imie);

    $mail->Subject = "Zapytanie ze strony — {$imie}";
    $mail->Body    = "Imię i nazwisko: {$imie}\nEmail: {$email}\n\nWiadomość:\n{$wiadomosc}";

    $mail->send();

    $_SESSION['contact_times'][] = $now;
    respond(true);

} catch (Exception $e) {
    error_log($e->getMessage() . "\n", 3, __DIR__ . '/mail_error.log');
    respond(false, 'Błąd wysyłania. Proszę napisać bezpośrednio na email kancelarii.');
}
```

- [ ] **Step 3: Utwórz `public/composer.json` (dla PHPMailer na home.pl)**

```json
{
  "require": {
    "phpmailer/phpmailer": "^6.9"
  }
}
```

Po wgraniu na home.pl uruchom przez SSH lub panel: `composer install --no-dev`

- [ ] **Step 4: Dodaj `public/vendor/` do `.gitignore`**

Utwórz `Arturborzewski/.gitignore`:
```
node_modules/
.next/
out/
public/vendor/
public/mail_error.log
```

- [ ] **Step 5: Commit**

```bash
git add Arturborzewski/public/contact.php Arturborzewski/public/get-csrf.php Arturborzewski/public/composer.json Arturborzewski/.gitignore
git commit -m "feat(borzewski): PHP contact form — PHPMailer + Turnstile + CSRF + rate limiting"
```

---

## Task 7: Pliki statyczne — .htaccess, robots, sitemap, security, manifest

**Files:**
- Create: `Arturborzewski/public/.htaccess`
- Create: `Arturborzewski/public/robots.txt`
- Create: `Arturborzewski/public/sitemap.xml`
- Create: `Arturborzewski/public/.well-known/security.txt`
- Create: `Arturborzewski/public/site.webmanifest`

- [ ] **Step 1: Utwórz `public/.htaccess`**

```apache
Options -Indexes
ServerSignature Off

# Force HTTPS
RewriteEngine On
RewriteCond %{HTTPS} off
RewriteRule ^(.*)$ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]

# www → non-www (dostosować do domeny Artura)
RewriteCond %{HTTP_HOST} ^www\.(.+)$ [NC]
RewriteRule ^ https://%1%{REQUEST_URI} [R=301,L]

# 404
ErrorDocument 404 /404.html

# Security headers
Header always set X-Content-Type-Options "nosniff"
Header always set X-Frame-Options "SAMEORIGIN"
Header always set Referrer-Policy "strict-origin-when-cross-origin"
Header always set Permissions-Policy "camera=(), microphone=(), geolocation=()"
Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"
Header set Content-Security-Policy "default-src 'self'; script-src 'self' https://challenges.cloudflare.com; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; frame-src https://challenges.cloudflare.com; connect-src 'self';"

# Cache — assety Next.js (1 rok, immutable)
<FilesMatch "\.(js|css|woff2|webp|png|jpg|jpeg|ico|svg)$">
  Header set Cache-Control "public, max-age=31536000, immutable"
</FilesMatch>

# Nie cache'uj HTML
<FilesMatch "\.html$">
  Header set Cache-Control "no-cache, must-revalidate"
</FilesMatch>

# Ukryj logi i pliki PHP config
<FilesMatch "(mail_error\.log|composer\.json|composer\.lock)$">
  Order deny,allow
  Deny from all
</FilesMatch>
```

- [ ] **Step 2: Utwórz `public/robots.txt`**

```
User-agent: *
Allow: /

Sitemap: https://borzewski-legal.pl/sitemap.xml
```

- [ ] **Step 3: Utwórz `public/sitemap.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://borzewski-legal.pl/</loc>
    <changefreq>monthly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://borzewski-legal.pl/prawo-karne/</loc>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://borzewski-legal.pl/prawo-gospodarcze/</loc>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://borzewski-legal.pl/kontakt/</loc>
    <changefreq>yearly</changefreq>
    <priority>0.7</priority>
  </url>
</urlset>
```

Zastąp `borzewski-legal.pl` rzeczywistą domeną.

- [ ] **Step 4: Utwórz `public/.well-known/security.txt`**

```
Contact: mailto:kontakt@borzewski-legal.pl
Expires: 2027-05-16T00:00:00.000Z
Preferred-Languages: pl, en
```

- [ ] **Step 5: Utwórz `public/site.webmanifest`**

```json
{
  "name": "Kancelaria Adwokacka Artur Borzewski",
  "short_name": "Borzewski Legal",
  "description": "Kancelaria adwokacka w Warszawie",
  "start_url": "/",
  "display": "browser",
  "background_color": "#000000",
  "theme_color": "#eab308",
  "icons": [
    { "src": "/apple-touch-icon.png", "sizes": "180x180", "type": "image/png" }
  ]
}
```

- [ ] **Step 6: Utwórz placeholder `public/images/.gitkeep`**

```bash
mkdir -p Arturborzewski/public/images/cases
touch Arturborzewski/public/images/.gitkeep
touch Arturborzewski/public/images/cases/.gitkeep
```

- [ ] **Step 7: Commit**

```bash
git add Arturborzewski/public/
git commit -m "feat(borzewski): static files — htaccess, robots, sitemap, security.txt, webmanifest"
```

---

## Task 8: Image optimization script

**Files:**
- Create: `Arturborzewski/scripts/optimize-images.mjs`

Script uruchamiany przez `npm run prebuild`. Konwertuje obrazy w `public/images/` do WebP i zapisuje obok oryginałów. Oryginały zostają (fallback dla starych przeglądarek).

- [ ] **Step 1: Utwórz `scripts/optimize-images.mjs`**

```js
import sharp from 'sharp'
import { readdir, stat } from 'fs/promises'
import { join, extname, basename } from 'path'

const IMAGES_DIR = new URL('../public/images', import.meta.url).pathname
const SIZES = {
  'hero-lawyer': 1920,
  'mecenas-artur': 1200,
  'default': 800,
}

async function getFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) {
      files.push(...await getFiles(full))
    } else if (['.jpg', '.jpeg', '.png'].includes(extname(entry.name).toLowerCase())) {
      files.push(full)
    }
  }
  return files
}

async function optimize(file) {
  const ext = extname(file)
  const name = basename(file, ext)
  const webpPath = file.replace(ext, '.webp')

  // Nie nadpisuj istniejącego WebP jeśli oryginalny nie jest nowszy
  try {
    const [origStat, webpStat] = await Promise.all([stat(file), stat(webpPath)])
    if (webpStat.mtimeMs > origStat.mtimeMs) return
  } catch {
    // WebP nie istnieje — kontynuuj
  }

  const width = Object.entries(SIZES).find(([key]) => name.includes(key))?.[1] ?? SIZES.default
  await sharp(file).resize(width, null, { withoutEnlargement: true }).webp({ quality: 85 }).toFile(webpPath)
  console.log(`✓ ${name}${ext} → ${name}.webp (max ${width}px)`)
}

async function main() {
  let files
  try {
    files = await getFiles(IMAGES_DIR)
  } catch {
    console.log('ℹ️  Brak folderu public/images — pomijam optymalizację')
    return
  }

  if (files.length === 0) {
    console.log('ℹ️  Brak obrazów do optymalizacji')
    return
  }

  await Promise.all(files.map(optimize))
  console.log(`✅ Optymalizacja zakończona (${files.length} plików)`)
}

main().catch(console.error)
```

- [ ] **Step 2: Weryfikacja — uruchom script ręcznie**

```bash
cd Arturborzewski && node scripts/optimize-images.mjs
```

Oczekiwane: `ℹ️  Brak folderu public/images — pomijam optymalizację` (bo jeszcze nie ma zdjęć) — to OK.

- [ ] **Step 3: Commit**

```bash
git add Arturborzewski/scripts/optimize-images.mjs
git commit -m "feat(borzewski): image optimization script — sharp WebP pre-build"
```

---

## Task 9: README

**Files:**
- Create: `Arturborzewski/README.md`

- [ ] **Step 1: Utwórz `README.md`**

```markdown
# Kancelaria Adwokacka Artur Borzewski — strona www

## Jak dodać zdjęcie

1. Wrzuć plik (JPG lub PNG) do folderu `public/images/`
2. Uruchom `npm run build`
3. Wgraj folder `out/` na serwer przez FTP

Zdjęcia zostaną automatycznie zoptymalizowane do WebP przy każdym buildzie.

### Nazwy plików

| Plik | Gdzie się pojawia |
|------|------------------|
| `public/images/logo.png` | Nagłówek |
| `public/images/hero-lawyer.jpg` | Zdjęcie główne |
| `public/images/mecenas-artur.jpg` | Sekcja "O kancelarii" |
| `public/images/cases/case-1.jpg` | Realizacja 1 |
| `public/images/cases/case-2.jpg` | Realizacja 2 |
| `public/images/cases/case-3.jpg` | Realizacja 3 |

## Jak zmienić tekst / dane kontaktowe

Otwórz plik `content/site.json` i zmień wartości. Następnie zbuduj i wgraj na serwer.

```

## Jak uruchomić lokalnie

```bash
# Wymagany Node.js 18+
# Pobranie: https://nodejs.org

npm install        # tylko przy pierwszym uruchomieniu
npm run dev        # http://localhost:3000
```

## Jak wgrać na home.pl (deploy)

```bash
npm run build      # generuje folder out/
```

Następnie przez FTP (np. FileZilla):
1. Połącz się z serwerem home.pl
2. Wgraj całą zawartość folderu `out/` do katalogu `public_html/`

## Formularz kontaktowy — konfiguracja po wgraniu

1. Zaloguj się na [Cloudflare Turnstile](https://dash.cloudflare.com) i utwórz widget dla swojej domeny
2. W pliku `public/contact.php` zastąp:
   - `YOUR_TURNSTILE_SECRET_KEY` — secretem z Cloudflare
   - `SMTP_PASSWORD` — hasłem do konta email kancelarii
3. W pliku `app/ContactForm.tsx` zastąp `0x4AAAAAAA_REPLACE_WITH_REAL_SITEKEY` — sitekeym z Cloudflare
4. Zainstaluj PHPMailer przez SSH: `composer install --no-dev`

## Konfiguracja SMTP na home.pl

- Host: `smtp.home.pl`  
- Port: `587` (TLS)
- Login: adres email kancelarii
- Hasło: hasło do skrzynki

## Struktura projektu

```
app/          — kod strony (React/TypeScript)
content/      — teksty i dane (edytowalny JSON)
public/       — pliki statyczne (obrazy, PHP, konfiguracja)
scripts/      — narzędzia pomocnicze
out/          — wygenerowana strona (po npm run build)
```
```

- [ ] **Step 2: Commit**

```bash
git add Arturborzewski/README.md
git commit -m "docs(borzewski): README — instrukcja dla Artura"
```

---

## Task 10: Build verification

- [ ] **Step 1: Uruchom build**

```bash
cd Arturborzewski && npm run build
```

Oczekiwane: brak błędów, folder `out/` zostaje utworzony.

- [ ] **Step 2: Sprawdź strukturę `out/`**

```bash
ls Arturborzewski/out/
```

Oczekiwane pliki:
- `index.html`
- `prawo-karne/index.html`
- `prawo-gospodarcze/index.html`
- `kontakt/index.html`
- `_next/` (CSS, JS)
- `.htaccess`
- `robots.txt`
- `sitemap.xml`
- `contact.php`
- `get-csrf.php`
- `site.webmanifest`
- `.well-known/security.txt`

- [ ] **Step 3: Sprawdź dev server**

```bash
cd Arturborzewski && npm run dev
```

Otwórz http://localhost:3000 i sprawdź:
- [ ] Strona główna ładuje się
- [ ] `/prawo-karne/` — podstrona działa
- [ ] `/prawo-gospodarcze/` — podstrona działa
- [ ] `/kontakt/` — formularz widoczny
- [ ] Sticky CTA widoczne na wąskim oknie (< 1024px)
- [ ] Linki w menu nawigacyjnym działają (#about, #services itd.)

- [ ] **Step 4: Sprawdź TypeScript końcowo**

```bash
cd Arturborzewski && npx tsc --noEmit
```

Oczekiwane: brak błędów.

- [ ] **Step 5: Dodaj `out/` do `.gitignore`**

Upewnij się że `.gitignore` zawiera `out/`:
```
node_modules/
.next/
out/
public/vendor/
public/mail_error.log
```

- [ ] **Step 6: Commit końcowy**

```bash
git add Arturborzewski/
git commit -m "feat(borzewski): complete website — build verified, ready for FTP deploy"
```

---

## Checklist po wgraniu na home.pl

Po pierwszym FTP upload:
- [ ] Zainstaluj PHPMailer: `composer install --no-dev` (przez SSH lub panel home.pl)
- [ ] Ustaw Turnstile sitekey w `ContactForm.tsx` i przebuduj
- [ ] Ustaw Turnstile secret + hasło SMTP w `contact.php`
- [ ] Przetestuj formularz (wyślij wiadomość testową)
- [ ] Sprawdź HTTPS redirect
- [ ] Zgłoś sitemap do Google Search Console
