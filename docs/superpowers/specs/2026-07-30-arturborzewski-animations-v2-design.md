# Arturborzewski — Animacje v2 (motion + grafika) — Design Spec

**Status:** approved, do implementacji
**Recovery point:** git tag `arturborzewski-pre-animations-v2` → commit `cecd48a`

## Kontekst

Strona kancelarii (`Arturborzewski/`, Next.js 14 + Tailwind + Framer Motion, static export) ma już
podstawowe animacje z planu `2026-05-19-arturborzewski-animations-redesign.md`:
fade+slide sekcji (`AnimatedSection`), stagger kart (`AnimatedCards`), stagger linia-po-linii w hero
(`AnimatedHero`).

Ten spec dodaje kolejną warstwę motion + grafiki, żeby strona wyróżniała się na tle typowych,
sztywnych/korporacyjnych stron kancelarii prawnych — bez wchodzenia w gimmicky/"appkowy" styl,
bo temat (kancelaria adwokacka) wymaga powagi i zaufania.

Pomysły wypracowane w konsultacji z modelem Fable (brainstorm), przefiltrowane do tego, co ma sens
bez wymyślania danych (np. licznik statystyk odrzucony — brak prawdziwych liczb w `site.json`)
i bez ryzyka dla tonu strony (custom cursor odrzucony na życzenie użytkownika).

## Zakres — 9 elementów

### Motion
1. **Parallax na tle hero** — subtelny (10-15px) drift radial-gradientu w tle hero, reagujący na scroll
   (lub mysz — do ustalenia w Build na podstawie tego co wygląda lepiej).
2. **Text reveal przez `clip-path`** dla nagłówków sekcji (`h2`) — zastępuje obecny plain fade
   z `AnimatedSection` dla samych nagłówków, efekt bardziej redakcyjny/premium.
3. **SVG "underline draw"** pod nazwiskiem adwokata / cytatem w hero-card — kreska rysująca się
   od lewej do prawej przy wejściu w viewport.
4. **Zmiękczenie przejść między sekcjami** — obecne `border-y border-white/5` między sekcjami
   (naprzemiennie `bg-black` / `bg-zinc-950`) zamienione na gradient fade zamiast twardej linii.
5. **Hover-reveal na kartach case studies** (`realizacje`) — stała linia CTA
   ("Zobacz zakres współpracy →") wjeżdża (height/opacity) przy hover. Bez wymyślania wyników spraw —
   dane w `site.json` się nie zmieniają.
6. **Scroll-progress indicator** — cienka (2px) złota linia fixed na górze strony, szerokość = postęp
   scrolla.

### Grafika
7. **Złoty ornament `§`** jako motyw separatora sekcji — mały, powtarzający się element graficzny
   zamiast/obok istniejących linii-dividerów.
8. **Tekstura papieru/lnu na tle** — CSS `background-blend-mode` + subtelny SVG/noise pattern,
   ~2-3% opacity, na czarnym tle. Zero dodatkowego ciężkiego assetu.
9. **Cienkie ikony liniowe SVG zamiast emoji** — zastępują emoji w `klienci`
   (👤🏢⚖️🤝) i `wyroznienia` (⚡🔒📞💡🗺️🤝).

### Świadomie pominięte
- **Animowane liczniki** — brak prawdziwych danych liczbowych w `site.json`; nie wymyślamy liczb.
  Do rozważenia w przyszłości, jeśli klient dostarczy realne statystyki.
- **Custom cursor** — sam Fable ocenił jako ryzykowne dla powagi kancelarii prawnej; użytkownik
  potwierdził pominięcie.

## Architektura

Kontynuacja wzorca z poprzedniego planu — małe, izolowane client-komponenty (`"use client"`)
owijające istniejący RSC content, zero zmian w strukturze danych (`site.json` schema się nie zmienia,
poza zamianą wartości pola `ikona` z emoji na klucz ikony — patrz niżej).

**Nowe komponenty (`Arturborzewski/app/`):**
- `TextReveal.tsx` — wrapper na nagłówki `h2`, `clip-path` reveal `whileInView`, analogiczny w API
  do `AnimatedSection` (`children`, `className`).
- `SectionDivider.tsx` — renderuje złoty ornament `§`, używany zamiast/w ramach istniejących
  `border-y` separatorów między sekcjami.
- `ScrollProgress.tsx` — fixed top bar, `useScroll` + `useSpring` z Framer Motion, montowany raz
  w layout/page root.
- `LineIcons.tsx` — eksportuje mapę `{ key: SvgComponent }` dla ikon liniowych; `site.json` pola
  `ikona` w `klienci`/`wyroznienia` zamieniają wartość emoji na klucz tekstowy (np. `"user"`,
  `"building"`, `"scale"`, `"handshake"`, `"bolt"`, `"lock"`, `"phone"`, `"tool"`, `"map"`).
  `page.tsx` renderuje `<LineIcons.user />` zamiast `{item.ikona}`.

**Zmiany inline (bez nowych plików, bo single-use):**
- Parallax hero (#1) i underline-draw (#3) — bezpośrednio w `page.tsx`/`AnimatedHero.tsx`,
  za mało reużywalne żeby uzasadniać osobny komponent.
- Hover-reveal case studies (#5) — inline w bloku `realizacje` w `page.tsx`.
- Zmiękczenie przejść (#4) i tekstura (#8) — `globals.css` + zmiana klas `border-y` na gradient
  utility w `page.tsx`.

**Dane:** `content/site.json` — jedyna zmiana to wartości pola `ikona` w `klienci` i `wyroznienia`
(emoji string → icon-key string). Kształt struktury bez zmian.

## Testowanie / weryfikacja

Czysto wizualna/motion zmiana — bez unit testów. Weryfikacja:
1. `cd Arturborzewski && npx tsc --noEmit` — brak błędów typów po każdym komponencie.
2. `npm run build` — build produkcyjny (static export) bez błędów.
3. `npx serve out -p <port>` — lokalny podgląd, checklist:
   - Parallax w hero widoczny, subtelny, nie powoduje layout shift
   - Nagłówki sekcji reveal'ują się przez clip-path (nie plain fade)
   - Underline draw pod cytatem/nazwiskiem w hero
   - Przejścia między sekcjami są gradientowe, nie ostre linie
   - Hover na kartach realizacji pokazuje CTA
   - Scroll-progress bar na górze rośnie ze scrollem
   - Ornament `§` widoczny przy separatorach sekcji
   - Tekstura tła widoczna przy bliższym spojrzeniu, nie rozprasza
   - Ikony liniowe zamiast emoji w klienci/wyróżnieniach
   - Brak regresji: istniejące animacje (fade sekcji, stagger kart, stagger hero) nadal działają
   - Mobile viewport — brak nowych efektów łamiących layout

## Out of scope

- Animowane liczniki (brak danych)
- Custom cursor (odrzucone)
- Page transitions między podstronami specjalizacji (nie było w zakresie tej rundy — osobny temat)
- Zmiana treści/copy strony poza polem `ikona`
