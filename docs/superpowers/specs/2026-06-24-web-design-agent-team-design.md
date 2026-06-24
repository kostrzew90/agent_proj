# Web Design Agent Team — Design

**Data:** 2026-06-24
**Status:** zaakceptowany

## Kontekst

User chce zestaw wyspecjalizowanych subagentów Claude Code do budowy nowoczesnych, animowanych stron WWW (klasa Apple/Stripe/Linear/Vercel/Raycast), zamiast pojedynczego ogólnego "web dev" skilla. Źródło: notatka usera w `web deisgner/webb` opisująca 6 person eksperckich.

`npx skills find` (rejestr skills.sh) nie zwracał wyników z powodu korporacyjnego proxy łamiącego weryfikację TLS (zdiagnozowane: `curl --ssl-no-revoke` i `NODE_TLS_REJECT_UNAUTHORIZED=0` działają, normalne wywołanie nie). Po tym diagnozie user zdecydował zamiast instalować gotowe skille z rejestru — zbudować własny, dopasowany zestaw subagentów.

## Decyzja: subagenty + skill-router

Każda persona = trwały, nazwany subagent Claude Code (`~/.claude/agents/<nazwa>.md`), dispatchowany przez `Agent` tool z `subagent_type: "<nazwa>"`. Dodatkowo jeden skill-router (`~/.claude/skills/web-design-team/SKILL.md`, `/web-design-team`) — nie wykonuje pracy, tylko opisuje 6 specjalistów i pomaga zdecydować którego dispatchować.

**Lokalizacja: globalna** (`~/.claude/agents/`, `~/.claude/skills/`) — web design to umiejętność niezależna od konkretnego projektu, dostępna we wszystkich repo usera.

**Zakres: wszystkich 6 person na raz** (notatka usera już ma kompletne specyfikacje dla każdej, koszt dodania kolejnych jest niski przy identycznym wzorcu pliku).

## 6 agentów i ich uprawnienia narzędziowe

| Agent | Tools | Specjalizacja |
|---|---|---|
| `frontend-architect` | Read, Write, Edit, Bash, Grep, Glob | React 19, Next.js 16 App Router, TypeScript, Tailwind v4, shadcn/ui, architektura projektu, SSR/SSG, dostępność, performance |
| `motion-designer` | Read, Write, Edit, Bash, Grep, Glob | Framer Motion, GSAP + ScrollTrigger, Lenis smooth scroll, page transitions, parallax — animacje klasy Apple/Stripe/Linear |
| `ui-ux-designer` | Read, Write, Edit, Grep, Glob, WebFetch | Design systems, spacing/typography, dark mode, mobile-first, dashboardy, responsywność; WebFetch do researchu referencji wizualnych |
| `threejs-specialist` | Read, Write, Edit, Bash, Grep, Glob | Three.js, React Three Fiber, GLSL shadery, particles, interaktywne 3D |
| `landing-page-cro` | Read, Write, Edit, Grep, Glob, WebSearch | CTA, konwersja, copywriting, user flow dla SaaS/AI/startupów; WebSearch do benchmarków konkurencji |
| `accessibility-auditor` | Read, Grep, Glob, Bash, WebFetch | **Read-only.** Lighthouse, WCAG, SEO, Core Web Vitals — raportuje, nie naprawia |

**Kluczowa decyzja architektoniczna (dodatek względem notatki usera):** `accessibility-auditor` jest **read-only** — nie ma Write/Edit. Audytuje i raportuje findings (severity-tagged, file:line gdzie ma sens), ale nie modyfikuje kodu. Fix wraca do `frontend-architect`. To ten sam wzorzec separacji audytu od implementacji, co task-reviewer w pipeline SDD (Argus) — niezależność audytu od tego, kto pisał kod, jest tym, co czyni audyt wiarygodnym. Pozostałe 5 agentów mają pełne uprawnienia implementatora (Write/Edit/Bash), bo ich rola to budowanie, nie kontrola.

## Format pliku agenta

Każdy `~/.claude/agents/<nazwa>.md`:

```markdown
---
name: <nazwa>
description: <kiedy dispatchować — konkretne sygnały/zadania, nie ogólnik>
tools: <lista lub "*">
---

<system prompt — ekspercka persona, zakres, standardy jakości, czego NIE robić (poza-scope dla tej persony, np. frontend-architect nie pisze animacji — to motion-designer)>
```

`description` musi być specyficzny i akcjonowalny (wzorzec z istniejących `claude-code-guide`/`Explore`/`Plan`) — kontroler (główna sesja) czyta opisy wszystkich 6, żeby zdecydować kogo dispatchować, więc niejasne opisy = źle dobrany agent.

## Skill-router

`~/.claude/skills/web-design-team/SKILL.md` — krótki, wylicza 6 agentów z 1-linijkowym "kiedy użyć" każdego, instruuje Claude (lub usera) jak dispatchować przez `Agent` tool. Nie duplikuje treści person — odsyła do nich.

## Out of scope

- Nie instalujemy żadnych skilli z zewnętrznego rejestru (problem TLS pozostaje nierozwiązany na poziomie sieci — to osobny temat, jeśli user zechce naprawić proxy/CA na stałe).
- Nie tworzymy jeszcze konkretnego projektu strony — to czysto infrastruktura agentów, gotowa do użycia gdy user zacznie konkretny projekt (np. w `Arturborzewski/` lub nowym repo).
- Nie implementujemy automatycznego routingu (np. hooka wybierającego agenta) — `web-design-team` skill to pomoc decyzyjna dla człowieka/Claude, nie automatyzacja.

## Testowanie / weryfikacja

Brak testów jednostkowych (to pliki markdown definiujące prompty, nie kod). Weryfikacja: po stworzeniu, dispatch jednego agenta (np. `frontend-architect`) z prostym zadaniem testowym, potwierdzić że subagent się aktywuje z właściwą personą i ograniczonym zestawem tooli.
