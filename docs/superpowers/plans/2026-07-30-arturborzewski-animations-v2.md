# Arturborzewski — Animacje v2 (motion + grafika) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodać drugą warstwę motion + grafiki (parallax hero, text-reveal nagłówków, underline-draw, gradient section transitions, hover-reveal case studies, scroll-progress bar, złoty ornament divider, tekstura papieru, ikony liniowe zamiast emoji) do już zaanimowanej strony kancelarii, zgodnie ze spec `docs/superpowers/specs/2026-07-30-arturborzewski-animations-v2-design.md`.

**Architecture:** Kontynuacja wzorca z poprzedniego planu animacji — małe, izolowane `"use client"` komponenty w `Arturborzewski/app/`, owijające istniejący RSC `page.tsx`. Zero zmian w kształcie `site.json` poza wartościami pola `ikona` (emoji string → klucz ikony).

**Tech Stack:** Next.js 14 (App Router, static export), Tailwind CSS, framer-motion (już w zależnościach), TypeScript.

## Global Constraints

- Nie dodawać nowych zależności npm (żadnej biblioteki ikon, żadnego dodatkowego pakietu animacji) — wszystko na framer-motion + ręcznym SVG, już obecnych w `package.json`.
- Tailwind: żadnych dynamicznie budowanych nazw klas (np. `` `from-${x}` ``) — JIT scanner Tailwinda wymaga literalnych stringów klas w kodzie źródłowym. Tam gdzie kolor zależy od propsa, użyć mapy `Record<string, string>` z pełnymi, literalnymi nazwami klas (patrz Task 3).
- Brak frameworka testowego w projekcie (brak jest/vitest w `package.json`) — weryfikacja per task to `npx tsc --noEmit` + wizualny check na `npm run dev` lub `npm run build && npx serve out`, zgodnie z konwencją poprzedniego planu animacji (`2026-05-19-arturborzewski-animations-redesign.md`).
- Recovery point: git tag `arturborzewski-pre-animations-v2` (commit `cecd48a`) — jeśli coś pójdzie nie tak, `git checkout arturborzewski-pre-animations-v2 -- Arturborzewski` przywraca stan sprzed tej rundy.
- Świadomie poza zakresem (nie implementować): animowane liczniki, custom cursor, page transitions między podstronami, zmiana treści/copy poza polem `ikona`.

---

## Task 1: Tekstura papieru na tle

**Files:**
- Modify: `Arturborzewski/app/globals.css`
- Modify: `Arturborzewski/app/page.tsx` (root div, linia z `className="min-h-screen bg-black text-white font-sans overflow-x-hidden"`)

**Interfaces:**
- Produces: CSS klasa `.paper-texture` używana bezpośrednio na root divie w `page.tsx`.

- [ ] **Krok 1: Dodaj klasę tekstury do globals.css**

Dopisz na końcu `Arturborzewski/app/globals.css`:

```css
.paper-texture {
  position: relative;
}

.paper-texture::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 1;
  opacity: 0.035;
  mix-blend-mode: overlay;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}
```

- [ ] **Krok 2: Zastosuj klasę na root divie**

W `Arturborzewski/app/page.tsx` znajdź:

```tsx
    <div className="min-h-screen bg-black text-white font-sans overflow-x-hidden">
```

Zamień na:

```tsx
    <div className="min-h-screen bg-black text-white font-sans overflow-x-hidden paper-texture">
```

- [ ] **Krok 3: Sprawdź wizualnie**

```bash
cd Arturborzewski && npm run dev
```

Otwórz `http://localhost:3000` — na czarnym tle powinna być ledwo widoczna ziarnista tekstura (bardzo subtelna, nie może "szumieć" ani rozpraszać). Header (`z-50`) i sticky mobile CTA (`z-50`) muszą pozostać czytelne nad teksturą (`z-1`).

- [ ] **Krok 4: Commit**

```bash
git add Arturborzewski/app/globals.css Arturborzewski/app/page.tsx
git commit -m "feat(arturborzewski): subtelna tekstura papieru na tle"
```

---

## Task 2: Ikony liniowe zamiast emoji

**Files:**
- Create: `Arturborzewski/app/LineIcons.tsx`
- Modify: `Arturborzewski/content/site.json` (pola `ikona` w `klienci` i `wyroznienia`)
- Modify: `Arturborzewski/app/page.tsx` (sekcje KLIENCI i WYRÓŻNIENIA)

**Interfaces:**
- Produces: `LineIcons: Record<string, (props: { className?: string }) => JSX.Element>` z kluczami `user`, `building`, `scale`, `handshake`, `bolt`, `lock`, `phone`, `bulb`, `map`.
- Consumes (w `page.tsx`): `item.ikona` jako string-klucz zamiast emoji, lookup przez `LineIcons[item.ikona]`.

- [ ] **Krok 1: Utwórz `Arturborzewski/app/LineIcons.tsx`**

```tsx
import { ReactElement, ReactNode } from 'react'

function Icon({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className ?? 'w-6 h-6'}
    >
      {children}
    </svg>
  )
}

type IconProps = { className?: string }

export const LineIcons: Record<string, (props: IconProps) => ReactElement> = {
  user: ({ className }) => (
    <Icon className={className}>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20c1.5-4 4-6 7-6s5.5 2 7 6" />
    </Icon>
  ),
  building: ({ className }) => (
    <Icon className={className}>
      <rect x="6" y="3" width="12" height="18" rx="1" />
      <path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2" />
    </Icon>
  ),
  scale: ({ className }) => (
    <Icon className={className}>
      <path d="M12 3v18M6 7l-3 6a3 3 0 006 0l-3-6zM18 7l-3 6a3 3 0 006 0l-3-6zM6 7h12M9 21h6" />
    </Icon>
  ),
  handshake: ({ className }) => (
    <Icon className={className}>
      <path d="M3 11l4-4 5 3 5-3 4 4M7 10l4 5 3-2M13 15l2 2" />
    </Icon>
  ),
  bolt: ({ className }) => (
    <Icon className={className}>
      <path d="M13 3L5 14h5l-1 7 8-11h-5l1-7z" />
    </Icon>
  ),
  lock: ({ className }) => (
    <Icon className={className}>
      <rect x="5" y="11" width="14" height="9" rx="1.5" />
      <path d="M8 11V8a4 4 0 018 0v3" />
    </Icon>
  ),
  phone: ({ className }) => (
    <Icon className={className}>
      <path d="M6 3h3l2 5-2.5 2a12 12 0 006.5 6.5l2-2.5 5 2v3a2 2 0 01-2 2A16 16 0 014 5a2 2 0 012-2z" />
    </Icon>
  ),
  bulb: ({ className }) => (
    <Icon className={className}>
      <path d="M9 18h6M10 21h4M12 3a6 6 0 00-3 11.2c.6.5 1 1.2 1 2.1v.7h4v-.7c0-.9.4-1.6 1-2.1A6 6 0 0012 3z" />
    </Icon>
  ),
  map: ({ className }) => (
    <Icon className={className}>
      <path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2z" />
      <path d="M9 4v14M15 6v14" />
    </Icon>
  ),
}
```

- [ ] **Krok 2: Zaktualizuj `Arturborzewski/content/site.json`**

W tablicy `klienci` zamień wartości pola `ikona`:

```json
  "klienci": [
    { "ikona": "user", "nazwa": "Klienci indywidualni", "opis": "Osoby fizyczne potrzebujące obrony, reprezentacji lub porady prawnej w sprawach karnych i cywilnych." },
    { "ikona": "building", "nazwa": "Przedsiębiorcy", "opis": "Właściciele firm wymagający obsługi prawnej w zakresie prawa gospodarczego, umów i sporów." },
    { "ikona": "scale", "nazwa": "Spółki i korporacje", "opis": "Podmioty gospodarcze potrzebujące stałej obsługi prawnej, compliance i restrukturyzacji." },
    { "ikona": "handshake", "nazwa": "Instytucje", "opis": "Organizacje i instytucje wymagające reprezentacji lub opinii prawnych w złożonych sprawach." }
  ],
```

W tablicy `wyroznienia` zamień wartości pola `ikona`:

```json
  "wyroznienia": [
    { "ikona": "bolt", "tytul": "Skuteczność", "opis": "Każda sprawa traktowana indywidualnie. Strategia dostosowana do celu, nie do szablonu." },
    { "ikona": "lock", "tytul": "Dyskrecja", "opis": "Pełna poufność obsługi. Bezpieczna komunikacja i ochrona danych klientów na każdym etapie." },
    { "ikona": "phone", "tytul": "Dostępność", "opis": "Bezpośredni kontakt z adwokatem. Bez sekretariatów i pośredników — klient zawsze wie, co się dzieje." },
    { "ikona": "bulb", "tytul": "Nowoczesne narzędzia", "opis": "Cyfrowy obieg dokumentów, bezpieczna komunikacja online i wsparcie technologiczne usprawniające obsługę." },
    { "ikona": "map", "tytul": "Kompleksowość", "opis": "Pełen zakres obsługi prawnej pod jednym dachem — od porady po reprezentację sądową." },
    { "ikona": "handshake", "tytul": "Partnerskie podejście", "opis": "Długoterminowe relacje z klientami oparte na zaufaniu, przejrzystości i wzajemnym szacunku." }
  ],
```

Reszta pliku bez zmian.

- [ ] **Krok 3: Podłącz ikony w `Arturborzewski/app/page.tsx` — sekcja KLIENCI**

Znajdź:

```tsx
          <AnimatedCardGrid className="grid md:grid-cols-2 xl:grid-cols-4 gap-6">
            {site.klienci.map((item) => (
              <AnimatedCardItem key={item.nazwa}>
                <div className="rounded-[28px] border border-white/10 bg-white/[0.02] p-8 h-full">
                  <div className="text-3xl mb-6">{item.ikona}</div>
                  <h3 className="text-xl font-serif mb-3">{item.nazwa}</h3>
                  <p className="text-zinc-400 leading-7 text-sm">{item.opis}</p>
                </div>
              </AnimatedCardItem>
            ))}
          </AnimatedCardGrid>
```

Zamień na:

```tsx
          <AnimatedCardGrid className="grid md:grid-cols-2 xl:grid-cols-4 gap-6">
            {site.klienci.map((item) => {
              const Icon = LineIcons[item.ikona]
              return (
                <AnimatedCardItem key={item.nazwa}>
                  <div className="rounded-[28px] border border-white/10 bg-white/[0.02] p-8 h-full">
                    <Icon className="w-8 h-8 mb-6 text-yellow-400" />
                    <h3 className="text-xl font-serif mb-3">{item.nazwa}</h3>
                    <p className="text-zinc-400 leading-7 text-sm">{item.opis}</p>
                  </div>
                </AnimatedCardItem>
              )
            })}
          </AnimatedCardGrid>
```

- [ ] **Krok 4: Podłącz ikony w `Arturborzewski/app/page.tsx` — sekcja WYRÓŻNIENIA**

Znajdź:

```tsx
          <AnimatedCardGrid className="grid md:grid-cols-2 xl:grid-cols-3 gap-8">
            {site.wyroznienia.map((item) => (
              <AnimatedCardItem key={item.tytul}>
                <div className="rounded-[30px] border border-white/10 bg-white/[0.02] p-10 h-full">
                  <div className="text-2xl mb-6">{item.ikona}</div>
                  <h3 className="text-2xl font-serif mb-4">{item.tytul}</h3>
                  <p className="text-zinc-400 leading-7">{item.opis}</p>
                </div>
              </AnimatedCardItem>
            ))}
          </AnimatedCardGrid>
```

Zamień na:

```tsx
          <AnimatedCardGrid className="grid md:grid-cols-2 xl:grid-cols-3 gap-8">
            {site.wyroznienia.map((item) => {
              const Icon = LineIcons[item.ikona]
              return (
                <AnimatedCardItem key={item.tytul}>
                  <div className="rounded-[30px] border border-white/10 bg-white/[0.02] p-10 h-full">
                    <Icon className="w-7 h-7 mb-6 text-yellow-400" />
                    <h3 className="text-2xl font-serif mb-4">{item.tytul}</h3>
                    <p className="text-zinc-400 leading-7">{item.opis}</p>
                  </div>
                </AnimatedCardItem>
              )
            })}
          </AnimatedCardGrid>
```

- [ ] **Krok 5: Dodaj import**

Na górze `Arturborzewski/app/page.tsx`, obok innych importów komponentów, dodaj:

```tsx
import { LineIcons } from './LineIcons'
```

- [ ] **Krok 6: Sprawdź TypeScript**

```bash
cd Arturborzewski && npx tsc --noEmit
```

Oczekiwane: brak błędów.

- [ ] **Krok 7: Sprawdź wizualnie**

```bash
npm run dev
```

Sekcje "Klienci" i "Co wyróżnia kancelarię" pokazują cienkie ikony liniowe (kolor `text-yellow-400`) zamiast emoji.

- [ ] **Krok 8: Commit**

```bash
git add Arturborzewski/app/LineIcons.tsx Arturborzewski/content/site.json Arturborzewski/app/page.tsx
git commit -m "feat(arturborzewski): ikony liniowe SVG zamiast emoji w klienci/wyroznienia"
```

---

## Task 3: Gradientowe przejścia + złoty ornament między sekcjami

**Files:**
- Create: `Arturborzewski/app/SectionDivider.tsx`
- Modify: `Arturborzewski/app/page.tsx` (usunięcie `border-t`/`border-y`, wstawienie dividerów między sekcjami)

**Interfaces:**
- Produces: `SectionDivider({ from, to }: { from: 'black' | 'zinc-950'; to: 'black' | 'zinc-950' })` — renderuje pasmo gradientu + złoty ornament `§`, bez animacji (statyczny, server component, brak `"use client"`).

- [ ] **Krok 1: Utwórz `Arturborzewski/app/SectionDivider.tsx`**

```tsx
type Bg = 'black' | 'zinc-950'

const gradients: Record<string, string> = {
  'black-black': 'bg-gradient-to-b from-black to-black',
  'black-zinc-950': 'bg-gradient-to-b from-black to-zinc-950',
  'zinc-950-black': 'bg-gradient-to-b from-zinc-950 to-black',
  'zinc-950-zinc-950': 'bg-gradient-to-b from-zinc-950 to-zinc-950',
}

export function SectionDivider({ from, to }: { from: Bg; to: Bg }) {
  const gradient = gradients[`${from}-${to}`]
  return (
    <div className={`relative h-20 ${gradient}`} aria-hidden="true">
      <div className="absolute inset-0 flex items-center justify-center gap-4">
        <span className="h-px w-16 bg-gradient-to-r from-transparent via-yellow-500/40 to-transparent" />
        <span className="text-yellow-500/60 text-lg font-serif">§</span>
        <span className="h-px w-16 bg-gradient-to-r from-transparent via-yellow-500/40 to-transparent" />
      </div>
    </div>
  )
}
```

Uwaga: nazwy klas gradientu są w pełni literalne w mapie `gradients` (nie budowane dynamicznie przez template string w `className`), żeby Tailwind JIT scanner je wykrył — patrz Global Constraints.

- [ ] **Krok 2: Dodaj import w `Arturborzewski/app/page.tsx`**

```tsx
import { SectionDivider } from './SectionDivider'
```

- [ ] **Krok 3: Usuń klasy border z sekcji i wstaw dividery**

Znajdź (sekcja ABOUT):

```tsx
      {/* ABOUT */}
      <section id="about" className="py-32 border-t border-white/5">
```

Zamień na:

```tsx
      <SectionDivider from="black" to="black" />

      {/* ABOUT */}
      <section id="about" className="py-32">
```

Znajdź (sekcja LAWYER):

```tsx
      {/* O ADWOKACIE */}
      <section id="lawyer" className="py-32 bg-zinc-950 border-y border-white/5">
```

Zamień na:

```tsx
      <SectionDivider from="black" to="zinc-950" />

      {/* O ADWOKACIE */}
      <section id="lawyer" className="py-32 bg-zinc-950">
```

Znajdź (sekcja SERVICES):

```tsx
      {/* SERVICES */}
      <section id="services" className="py-32 border-y border-white/5">
```

Zamień na:

```tsx
      <SectionDivider from="zinc-950" to="black" />

      {/* SERVICES */}
      <section id="services" className="py-32">
```

Znajdź (sekcja KLIENCI):

```tsx
      {/* KLIENCI */}
      <section id="clients" className="py-32 bg-zinc-950 border-y border-white/5">
```

Zamień na:

```tsx
      <SectionDivider from="black" to="zinc-950" />

      {/* KLIENCI */}
      <section id="clients" className="py-32 bg-zinc-950">
```

Znajdź (sekcja WYRÓŻNIENIA):

```tsx
      {/* WYRÓŻNIENIA */}
      <section id="distinctions" className="py-32 border-y border-white/5">
```

Zamień na:

```tsx
      <SectionDivider from="zinc-950" to="black" />

      {/* WYRÓŻNIENIA */}
      <section id="distinctions" className="py-32">
```

Znajdź (sekcja CASES):

```tsx
      {/* CASES */}
      <section id="cases" className="py-32 bg-zinc-950 border-y border-white/5">
```

Zamień na:

```tsx
      <SectionDivider from="black" to="zinc-950" />

      {/* CASES */}
      <section id="cases" className="py-32 bg-zinc-950">
```

Znajdź (sekcja CONTACT):

```tsx
      {/* CONTACT */}
      <section id="contact" className="py-32 pb-40 lg:pb-32">
```

Zamień na:

```tsx
      <SectionDivider from="zinc-950" to="black" />

      {/* CONTACT */}
      <section id="contact" className="py-32 pb-40 lg:pb-32">
```

- [ ] **Krok 4: Sprawdź TypeScript**

```bash
cd Arturborzewski && npx tsc --noEmit
```

Oczekiwane: brak błędów.

- [ ] **Krok 5: Sprawdź wizualnie**

```bash
npm run dev
```

Między każdą sekcją powinno być widoczne miękkie gradientowe przejście koloru tła z małym złotym ornamentem `§` na środku, zamiast dawnej ostrej linii `border-y`.

- [ ] **Krok 6: Commit**

```bash
git add Arturborzewski/app/SectionDivider.tsx Arturborzewski/app/page.tsx
git commit -m "feat(arturborzewski): gradientowe przejscia miedzy sekcjami + zloty ornament divider"
```

---

## Task 4: Text-reveal (clip-path) dla nagłówków sekcji

**Files:**
- Create: `Arturborzewski/app/TextReveal.tsx`
- Modify: `Arturborzewski/app/page.tsx` (7 nagłówków `h2`)

**Interfaces:**
- Produces: `TextReveal({ children, className }: { children: ReactNode; className?: string })` — renderuje `motion.h2` z `clip-path` reveal, API zgodne z `AnimatedSection`.

- [ ] **Krok 1: Utwórz `Arturborzewski/app/TextReveal.tsx`**

```tsx
"use client"
import { motion, Variants } from "framer-motion"
import { ReactNode } from "react"

const variants: Variants = {
  hidden: { clipPath: "inset(0 100% 0 0)", opacity: 0 },
  visible: {
    clipPath: "inset(0 0% 0 0)",
    opacity: 1,
    transition: { duration: 0.8, ease: [0.25, 0.46, 0.45, 0.94] as const },
  },
}

export function TextReveal({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <motion.h2
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, amount: 0.3 }}
      variants={variants}
      className={className}
    >
      {children}
    </motion.h2>
  )
}
```

- [ ] **Krok 2: Dodaj import w `Arturborzewski/app/page.tsx`**

```tsx
import { TextReveal } from './TextReveal'
```

- [ ] **Krok 3: Zamień h2 na TextReveal — sekcja ABOUT**

Znajdź:

```tsx
              <h2 className="text-4xl md:text-6xl font-serif leading-tight">
                Nowoczesne podejście do obsługi prawnej.
              </h2>
```

Zamień na:

```tsx
              <TextReveal className="text-4xl md:text-6xl font-serif leading-tight">
                Nowoczesne podejście do obsługi prawnej.
              </TextReveal>
```

- [ ] **Krok 4: Zamień h2 na TextReveal — sekcja LAWYER**

Znajdź:

```tsx
            <h2 className="text-4xl md:text-6xl font-serif leading-tight mb-10">
              {site.oAdwokacie.tytul}
            </h2>
```

Zamień na:

```tsx
            <TextReveal className="text-4xl md:text-6xl font-serif leading-tight mb-10">
              {site.oAdwokacie.tytul}
            </TextReveal>
```

- [ ] **Krok 5: Zamień h2 na TextReveal — sekcja SERVICES**

Znajdź:

```tsx
            <h2 className="text-4xl md:text-6xl font-serif">Zakres obsługi kancelarii</h2>
```

Zamień na:

```tsx
            <TextReveal className="text-4xl md:text-6xl font-serif">Zakres obsługi kancelarii</TextReveal>
```

- [ ] **Krok 6: Zamień h2 na TextReveal — sekcja KLIENCI**

Znajdź:

```tsx
            <h2 className="text-4xl md:text-6xl font-serif">Z kim współpracuję</h2>
```

Zamień na:

```tsx
            <TextReveal className="text-4xl md:text-6xl font-serif">Z kim współpracuję</TextReveal>
```

- [ ] **Krok 7: Zamień h2 na TextReveal — sekcja WYRÓŻNIENIA**

Znajdź:

```tsx
            <h2 className="text-4xl md:text-6xl font-serif">Co wyróżnia kancelarię</h2>
```

Zamień na:

```tsx
            <TextReveal className="text-4xl md:text-6xl font-serif">Co wyróżnia kancelarię</TextReveal>
```

- [ ] **Krok 8: Zamień h2 na TextReveal — sekcja CASES**

Znajdź:

```tsx
            <h2 className="text-4xl md:text-6xl font-serif">Wybrane obszary działań</h2>
```

Zamień na:

```tsx
            <TextReveal className="text-4xl md:text-6xl font-serif">Wybrane obszary działań</TextReveal>
```

- [ ] **Krok 9: Zamień h2 na TextReveal — sekcja CONTACT**

Znajdź:

```tsx
            <h2 className="text-4xl md:text-6xl font-serif mb-10 leading-tight">
              Skontaktuj się z kancelarią.
            </h2>
```

Zamień na:

```tsx
            <TextReveal className="text-4xl md:text-6xl font-serif mb-10 leading-tight">
              Skontaktuj się z kancelarią.
            </TextReveal>
```

- [ ] **Krok 10: Sprawdź TypeScript**

```bash
cd Arturborzewski && npx tsc --noEmit
```

Oczekiwane: brak błędów.

- [ ] **Krok 11: Sprawdź wizualnie**

```bash
npm run dev
```

Każdy nagłówek sekcji powinien "odsłaniać się" przez clip-path (jakby maska przesuwała się od lewej), a nie zwykłym fade — przy przewijaniu do każdej sekcji.

- [ ] **Krok 12: Commit**

```bash
git add Arturborzewski/app/TextReveal.tsx Arturborzewski/app/page.tsx
git commit -m "feat(arturborzewski): text-reveal clip-path dla naglowkow sekcji"
```

---

## Task 5: Underline-draw pod hasłem adwokata

**Files:**
- Create: `Arturborzewski/app/AnimatedUnderline.tsx`
- Modify: `Arturborzewski/app/page.tsx` (sekcja LAWYER)

**Interfaces:**
- Produces: `AnimatedUnderline({ className }: { className?: string })` — pozioma linia, `scaleX` 0→1 od lewej, wyzwalana `whileInView`.

**Uwaga implementacyjna:** Spec mówił o underline pod "nazwiskiem adwokata / cytatem w hero-card", ale hero-card od commita `d531aaf` pokazuje logo (`LogoImage`), nie tekst z nazwiskiem — ten tekst już tam nie istnieje. Najbliższy odpowiednik to `site.oAdwokacie.tytul` ("Skuteczna obrona wymaga wiedzy i doświadczenia.") w sekcji "O adwokacie" — to faktyczny cytat/hasło o adwokacie. Underline idzie tam. Efekt zrealizowany jako `scaleX` transform na `div`, nie jako SVG `stroke-dashoffset` — wizualnie identyczny (linia "rysuje się" od lewej), dużo mniej kodu.

- [ ] **Krok 1: Utwórz `Arturborzewski/app/AnimatedUnderline.tsx`**

```tsx
"use client"
import { motion } from "framer-motion"

export function AnimatedUnderline({ className }: { className?: string }) {
  return (
    <motion.div
      initial={{ scaleX: 0 }}
      whileInView={{ scaleX: 1 }}
      viewport={{ once: true, amount: 0.5 }}
      transition={{ duration: 0.8, ease: [0.25, 0.46, 0.45, 0.94] as const, delay: 0.3 }}
      style={{ transformOrigin: "left" }}
      className={`h-px bg-gradient-to-r from-yellow-500 via-yellow-500/60 to-transparent ${className ?? ""}`}
    />
  )
}
```

- [ ] **Krok 2: Dodaj import w `Arturborzewski/app/page.tsx`**

```tsx
import { AnimatedUnderline } from './AnimatedUnderline'
```

- [ ] **Krok 3: Wstaw underline pod hasłem adwokata**

Znajdź (po zmianach z Task 4, sekcja LAWYER):

```tsx
            <TextReveal className="text-4xl md:text-6xl font-serif leading-tight mb-10">
              {site.oAdwokacie.tytul}
            </TextReveal>
            <div className="space-y-6 text-zinc-400 leading-8 text-lg">
```

Zamień na:

```tsx
            <TextReveal className="text-4xl md:text-6xl font-serif leading-tight mb-6">
              {site.oAdwokacie.tytul}
            </TextReveal>
            <AnimatedUnderline className="w-24 mb-10" />
            <div className="space-y-6 text-zinc-400 leading-8 text-lg">
```

- [ ] **Krok 4: Sprawdź TypeScript**

```bash
cd Arturborzewski && npx tsc --noEmit
```

Oczekiwane: brak błędów.

- [ ] **Krok 5: Sprawdź wizualnie**

```bash
npm run dev
```

W sekcji "O adwokacie" pod hasłem powinna narysować się krótka złota linia od lewej do prawej, z lekkim opóźnieniem po nagłówku.

- [ ] **Krok 6: Commit**

```bash
git add Arturborzewski/app/AnimatedUnderline.tsx Arturborzewski/app/page.tsx
git commit -m "feat(arturborzewski): animowana linia pod haslem adwokata"
```

---

## Task 6: Scroll-progress bar

**Files:**
- Create: `Arturborzewski/app/ScrollProgress.tsx`
- Modify: `Arturborzewski/app/layout.tsx`

**Interfaces:**
- Produces: `ScrollProgress()` — fixed 2px pasek na górze strony, `scaleX` napędzany `useScroll` + `useSpring`.

- [ ] **Krok 1: Utwórz `Arturborzewski/app/ScrollProgress.tsx`**

```tsx
"use client"
import { motion, useScroll, useSpring } from "framer-motion"

export function ScrollProgress() {
  const { scrollYProgress } = useScroll()
  const scaleX = useSpring(scrollYProgress, { stiffness: 200, damping: 30, restDelta: 0.001 })
  return (
    <motion.div
      style={{ scaleX, transformOrigin: "left" }}
      className="fixed top-0 left-0 right-0 h-[2px] bg-yellow-500 z-[60]"
    />
  )
}
```

- [ ] **Krok 2: Zamontuj w `Arturborzewski/app/layout.tsx`**

Znajdź:

```tsx
import type { Metadata } from 'next'
import { Playfair_Display, Inter } from 'next/font/google'
import './globals.css'
import site from '../content/site.json'
```

Zamień na:

```tsx
import type { Metadata } from 'next'
import { Playfair_Display, Inter } from 'next/font/google'
import './globals.css'
import site from '../content/site.json'
import { ScrollProgress } from './ScrollProgress'
```

Znajdź:

```tsx
      <body className={`${inter.className} antialiased`}>{children}</body>
```

Zamień na:

```tsx
      <body className={`${inter.className} antialiased`}>
        <ScrollProgress />
        {children}
      </body>
```

- [ ] **Krok 3: Sprawdź TypeScript**

```bash
cd Arturborzewski && npx tsc --noEmit
```

Oczekiwane: brak błędów.

- [ ] **Krok 4: Sprawdź wizualnie**

```bash
npm run dev
```

Cienki złoty pasek u samej góry strony (nad headerem, `z-60` > header `z-50`) powinien rosnąć wraz z przewijaniem strony, od 0% do 100%.

- [ ] **Krok 5: Commit**

```bash
git add Arturborzewski/app/ScrollProgress.tsx Arturborzewski/app/layout.tsx
git commit -m "feat(arturborzewski): scroll-progress bar u gory strony"
```

---

## Task 7: Parallax tła hero

**Files:**
- Create: `Arturborzewski/app/HeroParallaxBg.tsx`
- Modify: `Arturborzewski/app/page.tsx` (sekcja HERO)

**Interfaces:**
- Produces: `HeroParallaxBg()` — absolutnie pozycjonowany div z radial-gradientem, przesuwający się w pionie (0→15px) wraz ze scrollem przez hero.

- [ ] **Krok 1: Utwórz `Arturborzewski/app/HeroParallaxBg.tsx`**

```tsx
"use client"
import { motion, useScroll, useTransform } from "framer-motion"
import { useRef } from "react"

export function HeroParallaxBg() {
  const ref = useRef<HTMLDivElement>(null)
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start start", "end start"],
  })
  const y = useTransform(scrollYProgress, [0, 1], [0, 15])

  return (
    <motion.div
      ref={ref}
      style={{ y }}
      className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(234,179,8,0.15),transparent_35%)]"
    />
  )
}
```

- [ ] **Krok 2: Dodaj import w `Arturborzewski/app/page.tsx`**

```tsx
import { HeroParallaxBg } from './HeroParallaxBg'
```

- [ ] **Krok 3: Zamień statyczne tło hero na parallax**

Znajdź:

```tsx
      <section className="relative min-h-screen flex items-center pt-32">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(234,179,8,0.15),transparent_35%)]"></div>
```

Zamień na:

```tsx
      <section className="relative min-h-screen flex items-center pt-32">
        <HeroParallaxBg />
```

- [ ] **Krok 4: Sprawdź TypeScript**

```bash
cd Arturborzewski && npx tsc --noEmit
```

Oczekiwane: brak błędów.

- [ ] **Krok 5: Sprawdź wizualnie**

```bash
npm run dev
```

Przy przewijaniu przez hero, żółty radial-gradient w tle powinien delikatnie przesuwać się w pionie (subtelnie, bez efektu "odklejania się" od reszty treści).

- [ ] **Krok 6: Commit**

```bash
git add Arturborzewski/app/HeroParallaxBg.tsx Arturborzewski/app/page.tsx
git commit -m "feat(arturborzewski): subtelny parallax tla hero"
```

---

## Task 8: Hover-reveal CTA na kartach case studies

**Files:**
- Modify: `Arturborzewski/app/page.tsx` (sekcja CASES)

**Interfaces:** brak nowych — czysto CSS/markup zmiana istniejącego bloku.

- [ ] **Krok 1: Dodaj hover-reveal overlay**

Znajdź:

```tsx
              <AnimatedCardItem key={item}>
                <div className="rounded-[30px] overflow-hidden border border-white/10 bg-black h-full">
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
              </AnimatedCardItem>
```

Zamień na:

```tsx
              <AnimatedCardItem key={item}>
                <div className="group relative rounded-[30px] overflow-hidden border border-white/10 bg-black h-full">
                  <img
                    src={`/images/cases/case-${index + 1}.jpg`}
                    alt={item}
                    className="w-full h-72 object-cover"
                  />
                  <div className="p-8">
                    <div className="text-yellow-500 uppercase tracking-[0.3em] text-xs mb-4">Case Study</div>
                    <h3 className="text-2xl font-serif leading-relaxed">{item}</h3>
                  </div>
                  <div className="absolute inset-x-0 bottom-0 translate-y-full group-hover:translate-y-0 transition-transform duration-500 bg-gradient-to-t from-black via-black/95 to-transparent p-8 pt-16">
                    <span className="text-yellow-400 font-medium">Zobacz zakres współpracy →</span>
                  </div>
                </div>
              </AnimatedCardItem>
```

- [ ] **Krok 2: Sprawdź TypeScript**

```bash
cd Arturborzewski && npx tsc --noEmit
```

Oczekiwane: brak błędów.

- [ ] **Krok 3: Sprawdź wizualnie**

```bash
npm run dev
```

Hover nad kartą w sekcji "Wybrane obszary działań" powinien pokazać wjeżdżający od dołu pasek z tekstem "Zobacz zakres współpracy →", bez przesuwania layoutu innych kart.

- [ ] **Krok 4: Commit**

```bash
git add Arturborzewski/app/page.tsx
git commit -m "feat(arturborzewski): hover-reveal CTA na kartach case studies"
```

---

## Task 9: Finalna weryfikacja build + checklist

**Files:** brak zmian kodu.

- [ ] **Krok 1: Build produkcyjny (static export)**

```bash
cd Arturborzewski && npm run build
```

Oczekiwane: `✓ Compiled successfully`, brak błędów TypeScript/build. Jeśli SSL błąd przy Google Fonts (proxy), użyj `NODE_TLS_REJECT_UNAUTHORIZED=0 npm run build` tylko lokalnie.

- [ ] **Krok 2: Uruchom lokalny podgląd statyku**

```bash
npx serve out -p 3456
```

Otwórz `http://localhost:3456` i przejdź checklistę:

- [ ] Tekstura papieru widoczna przy bliższym spojrzeniu na czarnym tle, nie rozprasza
- [ ] Ikony liniowe (nie emoji) w sekcjach "Klienci" i "Co wyróżnia kancelarię"
- [ ] Gradientowe przejścia między wszystkimi sekcjami + złoty ornament `§` widoczny na każdym
- [ ] Nagłówki sekcji (h2) odsłaniają się przez clip-path, nie plain fade
- [ ] Złota linia rysuje się pod hasłem w sekcji "O adwokacie"
- [ ] Złoty pasek scroll-progress u góry rośnie wraz z przewijaniem
- [ ] Parallax w tle hero widoczny przy scrollu, subtelny
- [ ] Hover na kartach "Wybrane obszary działań" pokazuje CTA "Zobacz zakres współpracy →"
- [ ] Brak regresji: fade+slide sekcji, stagger kart, stagger hero z poprzedniego planu nadal działają
- [ ] Mobile viewport (DevTools responsive mode) — brak złamanego layoutu przez nowe efekty
- [ ] Nawigacja i formularz kontaktowy nadal działają

- [ ] **Krok 3: Commit końcowy**

```bash
git add -A
git commit -m "build(arturborzewski): verify static export — animacje v2 (parallax, text-reveal, dividers, ikony, scroll-progress)"
```
