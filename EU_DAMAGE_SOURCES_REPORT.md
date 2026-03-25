# EU Vehicle Damage/History Check Sources — Research Report

**Date**: 2026-03-01
**Methodology**: Direct HTTP testing, Cloudflare detection, HTML form analysis, API endpoint scanning
**Test VIN**: WBADT43452G808797 (real BMW)

---

## Executive Summary

**BLOCKED (Cloudflare)**: 2/7 sources
**REACHABLE BUT FREEMIUM**: 4/7 sources (require registration/payment)
**FREE & ACCESSIBLE**: 1/7 source (vin-info.com — minimal data)
**CONNECTION ERRORS**: 1/7 source (bezwypadkowy.com — unavailable)

**KEY FINDING**: No EU sources provide **free, damage-specific history data** via direct scraping.
All major damage history databases (bidfax, autoastat, statvin, carvertical, autodna) either:
1. Use Cloudflare protection (impossible to bypass with headless browser)
2. Require paid subscription/registration
3. Provide free preview only (teaser data, registration required for full report)

---

## Detailed Analysis

### 1. vin-info.com — REACHABLE, LIMITED FREE DATA

**Status**: Reachable without CF
**URL**: https://vin-info.com/en/
**Input**: VIN via POST form
**Data Returned**: Basic VIN decoding only (make/model/year)
**CF Protection**: NO
**Damage History**: NO

**Assessment**:
- Form: POST with fields `form_fields[wdgvininput]` for VIN input
- No Cloudflare detected (nginx server)
- Free version exists but provides **only basic VIN decoder** (no accident/damage history)
- Full history data requires registration/payment
- **NOT ACTIONABLE** for damage history

---

### 2. autodna.com — BLOCKED BY CLOUDFLARE

**Status**: Cloudflare blocked
**URL**: https://www.autodna.com/
**Input**: VIN
**CF Protection**: YES — strict Cloudflare enforcement
**Damage History**: Mentions in HTML suggest yes, but inaccessible

**Assessment**:
- Page loads with status 200 but contains Cloudflare markers
- HTML mentions "damage", "accident", "history" but content is CF-protected
- Free tier exists (mentions "free" in metadata)
- **NOT ACTIONABLE** — CF blocks all automated access

---

### 3. carvertical.com — REACHABLE, FREEMIUM MODEL

**Status**: Reachable, no CF protection
**URL**: https://www.carvertical.com/
**Input**: VIN via GET parameter `?identifier=VIN`
**CF Protection**: NO (Vercel server, no CF-Ray headers)
**Damage History**: YES — mentions in page

**Assessment**:
- Form found: simple GET form with single "identifier" input
- Server: Vercel (no Cloudflare)
- Successfully accepts VIN queries: `https://www.carvertical.com/?identifier=WBADT43452G808797`
- Response status 200, mentions "damage", "accident", "history", "write-offs" in HTML
- **FREEMIUM MODEL**: Free preview only; full report requires payment
- Says "Free mentions: 1" in test output (single "free" reference buried in JSON)
- **PARTIALLY ACTIONABLE**: Can scrape preview data but full damage report blocked by paywall

**Feasibility**: Medium — can fetch page with damage overview but not full data

---

### 4. otomoto.pl — REACHABLE, POLISH MARKET

**Status**: Reachable, no CF
**URL**: https://www.otomoto.pl/ (auto-historia/)
**Input**: License plate (Polish format DW 12345)
**CF Protection**: NO
**Damage History**: YES — mentions in HTML

**Assessment**:
- Status 200, nginx server
- Has login/registration forms
- Mentions damage/accident data in content
- Polish-focused market (for used car listings)
- **PARTIALLY ACTIONABLE**: Likely requires login to view full history, but free preview may exist

---

### 5. bezwypadkowy.com — UNREACHABLE

**Status**: Connection error
**URL**: https://bezwypadkowy.com/
**Input**: VIN
**Error**: Network connectivity issue

**Assessment**:
- Cannot reach endpoint (DNS/network error)
- Domain might be inactive or blocked at network level
- **NOT ACTIONABLE** — unavailable

---

### 6. check24.de — REACHABLE, NO VEHICLE DATA

**Status**: Reachable, no CF
**URL**: https://www.check24.de/unfallwagen-check/
**Input**: License plate (German format B-DK 9999)
**CF Protection**: NO
**Damage History**: YES — mentions "unfallwagen" (damaged cars) but no VIN decoder form found

**Assessment**:
- Search form exists but no VIN/plate input field found in initial page
- Mentions "damage" content but appears to be insurance comparison tool, not history database
- Requires registration/login for full access
- **NOT ACTIONABLE** — mislabeled; not a damage history tool but insurance comparison

---

### 7. totalcar.hu — BLOCKED BY CLOUDFLARE

**Status**: Cloudflare blocked
**URL**: https://totalcar.hu/vin/
**Input**: VIN
**CF Protection**: YES — Cloudflare detected via headers
**Damage History**: Mentions in HTML but inaccessible

**Assessment**:
- Cloudflare protection active (standard CF headers present)
- Content mentions damage/accident keywords but CF blocks access
- Hungarian market
- **NOT ACTIONABLE** — CF blocks all automated access

---

## Alternative Approaches: Free API Sources

### NHTSA (US/Global, Free API)

**API**: https://vpic.nhtsa.dot.gov/api/
**Region**: Primarily US, but works for international vehicles
**Endpoints**:
- `DecodeVIN` — basic make/model/year
- `GetRecalls` — safety recalls (free, no auth)
- `GetComplaints` — complaint history (free, no auth)
- `SafetyRatings` — crash test ratings (free, no auth)

**Actionable**: YES — Currently used in VINhunter project (working plugin: `nhtsa.py`)

---

### VINhunter Project Findings

Your project already has implementations:

**Working damage sources**:
- `nhtsa_recalls.py` — Free NHTSA API
- `nhtsa_complaints.py` — Free NHTSA API
- `nhtsa_safety.py` — Free NHTSA crash ratings

**Non-working damage sources (Cloudflare blocked)**:
- `bidfax.py` — US auction aggregator (CF blocked even with Firefox+stealth)
- `statvin.py` — (CF blocked)
- `autoastat.py` — (CF blocked)

**Paid API plugins (not configured)**:
- `autoref.py` — requires AutoRef.eu API key (50 free/month)
- `vincario.py` — requires Vincario API key ($0.25/decode)

---

## Recommendations

### IMMEDIATE: What's actually accessible for free scraping

1. **NHTSA APIs** (already in use) — RECOMMENDED
   - Free, no authentication
   - Covers recalls, complaints, safety ratings
   - **Limitation**: US market focus (but works for any VIN globally)
   - **Status**: Working in VINhunter

2. **vin-info.com** — NOT RECOMMENDED
   - Only provides basic VIN decoder (make/model/year)
   - No damage history in free tier
   - Not worth dedicated plugin

3. **carvertical.com** — PARTIAL
   - Reachable without CF
   - Freemium model (preview only)
   - Would require payment for full damage reports
   - Could scrape limited preview data if needed

### MEDIUM TERM: Recommended paid API integrations

1. **AutoRef.eu** — €20/5000 queries or 50 free/month
   - European data
   - Documented API
   - Already has plugin skeleton (`autoref.py`)
   - **Action**: Register at https://autoref.eu/en/contact, get API key, test plugin

2. **Vincario API** — $0.25/decode
   - Damage history specialist
   - Pay-per-use model
   - Already has plugin skeleton (`vincario.py`)
   - **Action**: Register at https://vincario.com, get API credentials, test plugin

### NOT RECOMMENDED: Don't waste time on these

- **Cloudflare sources** (bidfax, autodna, totalcar.hu, statvin, autoastat)
  - Firefox + stealth doesn't help (Cloudflare detects headless regardless)
  - Would require browser automation library with real browser (too slow for API)
  - Decision: Keep disabled in VINhunter

- **Polish sources** (otomoto.pl, bezwypadkowy.com)
  - Require registration/login
  - Would need session management, CAPTCHA handling
  - Not worth dedicated effort

---

## Summary Table

| Source | Accessible | CF Protected | Damage Data | Free | Actionable | Recommendation |
|--------|-----------|--------------|------------|------|-----------|-----------------|
| vin-info.com | YES | NO | NO (basic VIN only) | YES | NO | Skip |
| autodna.com | NO | YES | Presumed YES | YES | NO | Skip |
| carvertical.com | YES | NO | YES (preview) | PARTIAL | MAYBE | Low priority |
| otomoto.pl | YES | NO | YES | PARTIAL | MAYBE | Low priority |
| bezwypadkowy.com | NO | ? | ? | ? | NO | Skip |
| check24.de | YES | NO | NO (insurance tool) | PARTIAL | NO | Wrong category |
| totalcar.hu | NO | YES | YES | ? | NO | Skip |
| **NHTSA** | **YES** | **NO** | **YES** | **YES** | **YES** | **USE THIS** |
| **AutoRef.eu** | YES (API) | NO | YES | PARTIAL (free tier) | YES | Implement |
| **Vincario** | YES (API) | NO | YES | NO | YES | Implement |

---

## Next Steps for VINhunter

1. **Test rebuild** with new plugins (autoref, vincario) — no CF blocking
2. **Register API keys** if you want damage history beyond NHTSA recalls
3. **Keep existing plugins** as-is (NHTSA working well)
4. **Don't pursue Cloudflare sources** — time better spent elsewhere

**Conclusion**: EU free damage history is not widely available. NHTSA (US API) is your best bet for free, actionable data. For EU-specific damage history, prepare budget for AutoRef or Vincario APIs.
