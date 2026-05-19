# Spec: Arturborzewski — animacje + restrukturyzacja sekcji

**Data:** 2026-05-19  
**Projekt:** `Arturborzewski/` — Next.js 14, static export, Tailwind CSS, deploy FTP → home.pl

---

## Cel

Dodać animacje wejścia (scroll-triggered) i rozszerzyć strukturę sekcji wzorując się na lagocka-kancelaria.pl. Usunąć temat cyberbezpieczeństwa.

---

## Zmiany w treści (`site.json`)

- Usunąć specjalizację `cyberbezpieczenstwo` z tablicy `specjalizacje`
- Dodać sekcję `oAdwokacie` z polami: `tytul`, `bio` (2–3 akapity), `doswiadczenie` (lista 3–4 punktów)
- Dodać sekcję `klienci` — tablica typów klientów (indywidualni, przedsiębiorcy, spółki, instytucje)
- Dodać sekcję `wyróznienia` — tablica 4–6 punktów wyróżniających kancelarię

---

## Nowa struktura sekcji (`page.tsx`)

| Kolejność | ID | Obecna? | Zmiana |
|---|---|---|---|
| 1 | hero | ✅ | animacja wejścia (stagger headline) |
| 2 | about | ✅ | bez zmian treści |
| 3 | lawyer | ❌ nowa | "O adwokacie" — bio + lista doświadczeń |
| 4 | services | ✅ | usuń cyberbezpieczeństwo, stagger kart |
| 5 | clients | ❌ nowa | "Z kim współpracuję" — 4 typy klientów |
| 6 | distinctions | ❌ nowa | "Co wyróżnia kancelarię" — 4–6 punktów |
| 7 | cases | ✅ | bez zmian |
| 8 | contact | ✅ | bez zmian |

Nawigacja w headerze: zaktualizować linki do nowych sekcji.

---

## Animacje — biblioteka i wzorzec

**Biblioteka:** `framer-motion` (dodać do `package.json`)

**Wzorzec:** jeden klientowy wrapper `AnimatedSection` + klientowy wrapper `AnimatedCard` dla kart.

```
AnimatedSection — fade-in + slide-up, whileInView, once: true
AnimatedCard    — to samo + stagger przez `variants` z `delayChildren`
```

Wszystkie istniejące sekcje (RSC) pozostają RSC — wrappers są jedynymi plikami `"use client"`.

### Animacje per sekcja

| Sekcja | Animacja |
|---|---|
| Hero headline | Stagger linia po linii (fade-in + slide-up, 0.2s delay między liniami) |
| Hero CTA buttons | fade-in po headline, delay 0.6s |
| About | fade-in + slide-up sekcji |
| O adwokacie | fade-in lewo (tekst) + fade-in prawo (lista) |
| Specjalizacje karty | stagger — każda karta 0.1s po poprzedniej |
| Z kim współpracuję | stagger kart |
| Co wyróżnia | stagger punktów |
| Realizacje | stagger kart |

---

## Nowe pliki

| Plik | Opis |
|---|---|
| `app/AnimatedSection.tsx` | `"use client"`, `motion.div` fade-in+slide-up, `whileInView` |
| `app/AnimatedCard.tsx` | `"use client"`, stagger wrapper dla dzieci |
| `app/AnimatedHero.tsx` | `"use client"`, stagger dla headline i CTA |

---

## Pliki do modyfikacji

| Plik | Zmiana |
|---|---|
| `content/site.json` | usunąć cyberbezpieczeństwo, dodać oAdwokacie/klienci/wyróznienia |
| `app/page.tsx` | owinąć sekcje w AnimatedSection, dodać 3 nowe sekcje, zaktualizować nav |
| `package.json` | dodać `framer-motion` |

Podstrony (`prawo-karne/`, `prawo-gospodarcze/`) — bez zmian w tej iteracji.

---

## Static export / home.pl

Framer Motion jest SSR-safe. `whileInView` używa IntersectionObserver wyłącznie po stronie klienta — nie odpali się podczas `next build`. Folder `out/` buduje się normalnie. Deploy przez FTP bez zmian w procedurze.

---

## Poza zakresem

- Zmiany w podstronach specjalizacji
- Hamburger menu (mobile nav)
- Nowe zdjęcia (placeholder hero-lawyer.jpg zostaje)
- Formularz kontaktowy
