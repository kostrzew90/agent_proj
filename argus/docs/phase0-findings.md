# Argus Phase 0 — Spike Findings

## Task
Validate data source availability (free public JSON APIs) for Argus Phase 1 MVP (market-trend agent tracking watchlist).

## 1. Hyperdash API Availability

**Question:** Does Hyperdash (https://hyperdash.info/) expose a PUBLIC JSON API for trader positions / liquidation data (free, no paid key)?

**Finding:** ❌ **NO free public API exists**

**Details:**
- Hyperdash was acquired by pvp.trade and rebuilt into an analytics + execution dashboard
- The product DOES NOT provide programmatic API access for external applications
- No documentation available for public API key issuance
- Data access is restricted to the web dashboard only

**Decision:** Hyperdash **stays in Phase 1.5 backlog** (does NOT block Phase 1 MVP, which runs on RSS feeds). If we need trader position tracking later, consider alternatives:
  - HyperTracker public API (wallet PnL, funding rates, liquidation zones)
  - Hyperliquid's own public API (no key needed, covers leaderboard, positions, vault performance)

**Source:** WebSearch confirms no API; see Hyperliquid Data Providers comparison.

---

## 2. CoinGlass API Availability

**Question:** Does Coinglass (https://www.coinglass.com/ or https://open-api.coinglass.com) expose a PUBLIC JSON API for market data (free, no paid key)?

**Finding:** ❌ **NO free tier; API requires paid subscription**

**Details:**
- CoinGlass offers a FREE web platform tier with real-time data visualization (open interest, funding rates, liquidation data, spot prices, Bitcoin ETF flows)
- Programmatic JSON API access requires paid subscription:
  - **Hobbyist plan:** $29/month (entry level)
  - **Standard plan:** $299/month (commercial use)
  - No free API tier exists in 2026
- CoinGlass provides 160+ API endpoints covering futures, spot, options, ETF markets across 30+ exchanges
- Documentation: https://docs.coinglass.com/

**Decision:** CoinGlass is **Phase 3 market-context** (not Phase 1). We can use free web access for manual reference; programmatic integration requires budget approval.

**Cost:** ~$29-299/month if required later. Alternative: scrape free web tier (if ToS permits) or use free alternatives like TradingView API.

**Source:** CoinGlass pricing page; 2026 Crypto Data API reviews confirm no free tier.

---

## 3. CoinGecko API Availability (for price feeds)

**Status:** ✅ **FREE PUBLIC API (no key required)**

Used for Phase 1: real-time price data, market cap, volume. Rate limit: ~10-50 calls/minute for unauthenticated. Sufficient for MVP polling every 5-10 minutes.

---

## 4. RSS Feed Sources (Phase 1 MVP)

**Status:** ✅ **All confirmed accessible, no auth required**

| Source | URL | Status |
|--------|-----|--------|
| CoinDesk | https://www.coindesk.com/arc/outboundfeeds/rss/ | ✅ |
| CoinTelegraph | https://cointelegraph.com/rss | ✅ |
| Decrypt | https://decrypt.co/feed | ✅ |
| TheBlock | https://www.theblock.co/rss.xml | ✅ |

---

## 5. CoinGecko ID Resolution

### VERIFY candidates (found via CoinGecko search API):

#### **XAI (Binance: XAIUSDT)**
- **Resolved:** `xai-blockchain`
- **Rank:** 864 (by market cap)
- **Confidence:** ✅ HIGH
- **Rationale:** Only major XAI project, traded as XAIUSDT on Binance. The Xai L3 blockchain project (xai.games) is the well-known token.
- **Alternatives considered:** OpenxAI (rank 4344), xAI PreStocks (rank 4183) — much smaller, not the primary token.

#### **GROK (Binance: GROKUSDT)**
- **Resolved:** `grok-2`
- **Rank:** 2270 (by market cap)
- **Confidence:** ⚠️ MEDIUM-HIGH
- **Rationale:** Multiple "Grok" tokens exist. Grok-2 ranks highest at 2270 among Grok variants. Associated with xAI (Elon Musk's AI company). Most likely the official GROKUSDT listed on Binance.
- **Alternatives considered:** 
  - grok-4 (rank 5142) — labeled "GROK" but lower rank
  - grok-6 (rank 7804) — even lower rank
- **Note:** CoinGecko search did not explicitly identify xAI affiliation, inferred from timing (token launched post-xAI announcement). Recommend verifying on Binance that GROKUSDT maps to grok-2.

#### **ALU (Binance: ALUUSDT)**
- **Resolved:** `altura`
- **Rank:** 1802 (by market cap)
- **Confidence:** ✅ HIGH
- **Rationale:** Altura (ALU) is the primary token; symbol matches exactly. CoinGecko search returned `altura` as primary entry with correct rank.
- **Alternatives considered:** altura-2 (Altura Vault Tokens, lower relevance) — not the main token.

### Known-good IDs (verified, not requiring search):
- BTC → `bitcoin`
- ETH → `ethereum`
- XRP → `ripple`
- DOT → `polkadot`
- JUP → `jupiter-exchange-solana`
- HBAR → `hedera-hashgraph`
- RENDER → `render-token`
- AERO → `aerodrome-finance`
- ONDO → `ondo-finance`
- AEVO → `aevo-exchange`
- RUNE → `thorchain`

---

## 6. Summary: Phase 1 MVP Data Model

| Data Source | Type | Auth | Status | Phase |
|-------------|------|------|--------|-------|
| **CoinGecko** | Price + metadata | None (free API) | ✅ Ready | Phase 1 |
| **CoinDesk RSS** | News headlines | None | ✅ Ready | Phase 1 |
| **CoinTelegraph RSS** | News headlines | None | ✅ Ready | Phase 1 |
| **Decrypt RSS** | News headlines | None | ✅ Ready | Phase 1 |
| **TheBlock RSS** | News + market data | None | ✅ Ready | Phase 1 |
| **Hyperdash (positions)** | Trader positions, liquidations | Paid (pvp.trade) | ❌ Not available | Phase 1.5+ |
| **CoinGlass (market context)** | Futures, spot, options data | Paid ($29+/mo) | ⚠️ Free web only | Phase 3 |

---

## Decision for Phase 1

✅ **All Phase 1 MVP data sources are freely accessible:**
- Price feeds: CoinGecko API
- News sentiment: 4x RSS feeds
- No API keys, rate-limit concerns, or paid subscriptions required

**Blocked or deferred:**
- Hyperdash trader data → Phase 1.5 backlog (low priority, alternative APIs available)
- CoinGlass derivatives context → Phase 3 (requires budget or alternatives)

---

## Next Steps

1. Seed watchlist.yaml with confirmed coingecko_ids and binance symbols
2. Seed sources.yaml with RSS feed URLs
3. Phase 1 implementation: ingest RSS → parse sentiment → correlate with price moves → learn signal quality
4. Phase 1.5: evaluate Hyperliquid public API for trader position tracking (if needed)
5. Phase 3: decide CoinGlass budget or alternative market data source
