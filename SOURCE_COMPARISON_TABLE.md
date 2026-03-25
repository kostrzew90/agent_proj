# EU Vehicle Damage/History Sources — Comparison Matrix

## Quick Reference Table

| Source | Country | Type | Accessible | CF | Damage Data | Free | Login | API | Cost | Recommendation |
|--------|---------|------|-----------|----|----|------|-------|-----|------|-----------------|
| **NHTSA** | US/Global | REST API | ✓ YES | NO | RECALLS + COMPLAINTS + SAFETY | ✓ FREE | NO | ✓ YES | No auth | **USE THIS** |
| vin-info.com | EU | Web Form | ✓ YES | NO | NONE (VIN decode only) | ✓ LIMITED | YES | NO | Free tier | **SKIP** |
| autodna.com | EU | Web Form | ✗ NO | YES | ✓ YES | Limited | YES | PAID | €/year | **SKIP** |
| carvertical.com | EU/Global | Web Form | ✓ YES | NO | ✓ YES (preview) | FREEMIUM | YES | PAID | €/month | **LOW PRIORITY** |
| otomoto.pl | Poland | Web Form | ✓ YES | NO | ✓ YES | FREEMIUM | YES | NO | Free tier + paid | **LOW PRIORITY** |
| bezwypadkowy.com | Poland | Web Form | ✗ NO | ? | ✓ MAYBE | ? | ? | ? | ? | **UNREACHABLE** |
| check24.de | Germany | Web Form | ✓ YES | NO | ✗ NO (insurance tool) | Limited | YES | NO | N/A | **WRONG TYPE** |
| totalcar.hu | Hungary | Web Form | ✗ NO | YES | ✓ YES | ? | ? | ? | ? | **SKIP** |
| **AutoRef.eu** | EU | REST API | ✓ YES | NO | ✓ YES | LIMITED | NO | ✓ YES | €20/5k or 50/mo | **MEDIUM PRIORITY** |
| **Vincario** | EU | REST API | ✓ YES | NO | ✓ YES | NO | NO | ✓ YES | $0.25/query | **MEDIUM PRIORITY** |

---

## Detailed Scoring

### NHTSA (Best Free Option)

```
Accessibility:    [████████] 10/10 — No CF, public API
Data Quality:     [████████] 9/10  — Recalls, complaints, safety ratings
Cost:             [██████████] 10/10 — FREE
API Availability: [████████] 10/10 — Fully documented
Damage Specificity: [██████  ] 6/10  — Recalls + complaints (not direct damage reports)
EU Coverage:      [██████  ] 6/10  — US-focused but global VIN acceptance

OVERALL SCORE:    8.5/10 ⭐ RECOMMENDED
STATUS:           Already working in VINhunter
ACTION:           Keep using as-is
```

### AutoRef.eu

```
Accessibility:    [████████] 9/10  — No CF, REST API
Data Quality:     [████████] 9/10  — Full history including damage
Cost:             [██████  ] 6/10  — €20/5k (~$0.004/query) or 50 free/month
API Availability: [████████] 9/10  — Documented, RESTful
Damage Specificity: [██████████] 10/10 — Complete damage history
EU Coverage:      [██████████] 10/10 — European focus

OVERALL SCORE:    8.8/10 ⭐ RECOMMENDED (if budget available)
STATUS:           Skeleton plugin exists (autoref.py)
ACTION:           Register, get API key, test integration
COST:             €20/month OR €100/year (50 free queries might not be enough)
```

### Vincario API

```
Accessibility:    [████████] 9/10  — No CF, REST API
Data Quality:     [████████] 9/10  — Damage history + valuation
Cost:             [████    ] 4/10  — $0.25/query (high per-query cost)
API Availability: [████████] 9/10  — Well-documented
Damage Specificity: [██████████] 10/10 — Damage specialist
EU Coverage:      [██████████] 10/10 — European focus

OVERALL SCORE:    8.3/10 ⭐ GOOD (if low volume or budget exists)
STATUS:           Skeleton plugin exists (vincario.py)
ACTION:           Register, get credentials, test integration
COST:             $0.25/query — expensive for high volume (100 scans = $25)
```

### carvertical.com

```
Accessibility:    [████████] 9/10  — No CF, form-based
Data Quality:     [██████  ] 6/10  — Full report requires payment
Cost:             [████    ] 4/10  — Paid subscription required
API Availability: [        ] 0/10  — No public API (would need reverse engineering)
Damage Specificity: [██████████] 10/10 — Comprehensive when available
EU Coverage:      [████████] 8/10  — EU + Global

OVERALL SCORE:    6.1/10 — NOT RECOMMENDED
STATUS:           Freemium (preview accessible, full report behind paywall)
ACTION:           Consider only for one-off manual checks
COST:             €9-20/month for full access
LIMITATION:       Full report blocked by login/payment wall
```

### vin-info.com

```
Accessibility:    [████████] 9/10  — No CF, form-based
Data Quality:     [██      ] 2/10  — VIN decode only (no damage)
Cost:             [██████████] 10/10 — FREE
API Availability: [████    ] 4/10  — Minimal API (redirects)
Damage Specificity: [        ] 0/10  — None
EU Coverage:      [████████] 8/10  — EU

OVERALL SCORE:    4.3/10 — NOT RECOMMENDED
STATUS:           Basic VIN decoder, no damage history
ACTION:           Skip (not useful for damage research)
COST:             Free (registration required for history)
```

### Cloudflare-Protected Sources (autodna.com, totalcar.hu, bidfax, statvin, autoastat)

```
Accessibility:    [    ████] 1/10  — Cloudflare blocks headless access
Data Quality:     [████████] 8/10  — Would be good if accessible
Cost:             [████████] 9/10  — Free or paid (irrelevant if blocked)
API Availability: [        ] 0/10  — No public API
Damage Specificity: [████████] 8/10  — Comprehensive (if accessible)
EU Coverage:      [████████] 8/10  — EU/International

OVERALL SCORE:    2.6/10 — NOT RECOMMENDED
STATUS:           Blocked by Cloudflare (impossible without paid bypass service)
ACTION:           SKIP entirely (not worth the cost/effort)
COST:             Cloudflare bypass service = $50-500/month
DECISION:         Keep disabled in VINhunter
```

---

## Cost-Benefit Analysis

### Scenario 1: Budget = €0 (Free only)

**Use**: NHTSA APIs
- Pros: Free, no auth, working
- Cons: US-focused, recall data only (not direct damage)
- Volume: Unlimited
- Cost: €0

**Result**: Good baseline for recalls; no direct damage history

### Scenario 2: Budget = €50/month

**Option A**: AutoRef.eu (50 free queries/month)
- Cost: €0 (free tier)
- Volume: 50 scans/month
- Data: Full EU damage history
- Result: BEST for EU focus, limited volume

**Option B**: Vincario API (200 queries at $0.25 each)
- Cost: ~€50/month
- Volume: 200 scans/month
- Data: Damage history + valuation
- Result: Good for higher volume, expensive per query

### Scenario 3: Budget = €100+/month

**Combination**: NHTSA (free) + AutoRef (€20) + Vincario (€80)
- US recalls: NHTSA (free)
- EU damage: AutoRef or Vincario (€100/month)
- Data coverage: Global + EU-specific
- Cost: €100/month
- Result: COMPREHENSIVE but expensive

---

## Implementation Priority Matrix

### Must Do (Immediate)
1. Keep NHTSA plugins enabled (already working)
2. Keep CF-blocked plugins disabled (no bypass worth the cost)

### Should Do (Short term, < 2 weeks)
1. Register for AutoRef API (50 free/month to test)
2. Test autoref.py plugin integration
3. Register for Vincario API (test $0.25 query cost)
4. Test vincario.py plugin integration

### Nice to Have (If time/budget permits)
1. Scrape carvertical free preview data (minimal value)
2. Evaluate Polish market via otomoto (regional focus)
3. Monitor new EU regulations for open damage registries

### Don't Do (Never)
1. Attempt Cloudflare bypass (expensive, unreliable)
2. Automated login/session management (credential storage risk)
3. Browser-based scraping at scale (too slow for automation)

---

## Bottom Line

| Need | Best Solution | Cost | Status |
|------|---------------|------|--------|
| **Free global vehicle data** | NHTSA | €0 | ✓ Working |
| **Free EU damage history** | None available | — | ✗ Doesn't exist |
| **Affordable EU damage (low volume)** | AutoRef free tier | €0 (50/mo) | Needs setup |
| **Affordable EU damage (high volume)** | AutoRef paid | €20/mo | Needs setup |
| **Damage specialist (high cost)** | Vincario | $0.25/query | Needs setup |
| **Quick one-off checks** | Manual carvertical.com | €9-20/mo | Not automated |

**Conclusion**: For free damage history = **NHTSA only**. For EU-specific = **budget required** (AutoRef or Vincario).
