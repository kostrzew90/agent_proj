# Hyperliquid Spike Findings — Argus Increment 3

## Overview

This document captures the results of the Hyperliquid wallet tracking spike for Argus Increment 3. The goal was to:
1. Identify well-known public whale/trader addresses with active open positions
2. Confirm the exact JSON shape returned by the Hyperliquid API `clearinghouseState` endpoint
3. Bootstrap a seed list of addresses for tracking

## API Endpoint & Response Shape

**Endpoint:** `POST https://api.hyperliquid.xyz/info`

**Request:**
```json
{
  "type": "clearinghouseState",
  "user": "0x<40-HEX-ADDRESS>"
}
```

**Response Structure (abbreviated):**
```json
{
  "marginSummary": {
    "accountValue": "STRING<USD, float as string>",
    "totalNtlPos": "STRING",
    "totalRawUsd": "STRING",
    "totalMarginUsed": "STRING"
  },
  "crossMarginSummary": {
    "accountValue": "STRING",
    "totalNtlPos": "STRING",
    "totalRawUsd": "STRING",
    "totalMarginUsed": "STRING"
  },
  "crossMaintenanceMarginUsed": "STRING",
  "withdrawable": "STRING",
  "assetPositions": [
    {
      "type": "oneWay",
      "position": {
        "coin": "STRING (e.g., 'BTC', 'ETH', 'SOL')",
        "szi": "STRING (size in asset units, negative=short, positive=long)",
        "leverage": {
          "type": "cross",
          "value": NUMBER (e.g., 10, 5, 40)
        },
        "entryPx": "STRING (entry price as string float)",
        "positionValue": "STRING (notional position value in USD)",
        "unrealizedPnl": "STRING (unrealized profit/loss)",
        "returnOnEquity": "STRING (ROE as decimal)",
        "liquidationPx": "STRING (liquidation price)",
        "marginUsed": "STRING (margin allocated to position)",
        "maxLeverage": NUMBER,
        "cumFunding": {
          "allTime": "STRING",
          "sinceOpen": "STRING",
          "sinceChange": "STRING"
        }
      }
    }
  ],
  "time": NUMBER (Unix timestamp in milliseconds)
}
```

## Position Object Field Names

**Confirmed Fields in `assetPositions[].position`:**
- `coin` ✓
- `szi` ✓
- `leverage` (object with `type` and `value`) ✓
- `entryPx` ✓
- `positionValue` ✓
- `unrealizedPnl` ✓
- `returnOnEquity` ✓
- `liquidationPx` ✓
- `marginUsed` ✓
- `maxLeverage` ✓
- `cumFunding` (object with `allTime`, `sinceOpen`, `sinceChange`) ✓

**Status:** No discrepancies found. All fields match expected schema.

## Real Sample Response (Active Trader)

Address: `0x5b5d51203a0f9079f8aeb098a6523a13f298c060`

**Account Summary:**
```
accountValue: 11,036,332.46 USD
totalNtlPos: 61,891,132.05 USD
totalRawUsd: 38,038,034.86 USD
totalMarginUsed: 8,254,409.82 USD
```

**Sample Position (BTC Long):**
```json
{
  "coin": "BTC",
  "szi": "279.19307",
  "leverage": {
    "type": "cross",
    "value": 10
  },
  "entryPx": "77160.8",
  "positionValue": "17,448,729.30",
  "unrealizedPnl": "-4,094,056.91",
  "returnOnEquity": "-1.9004",
  "liquidationPx": "9923.51",
  "marginUsed": "1,744,872.93",
  "maxLeverage": 40,
  "cumFunding": {
    "allTime": "-15,962,511.92",
    "sinceOpen": "71,007.35",
    "sinceChange": "27,512.34"
  }
}
```

**Additional Positions (same address):**
- ETH Short: -10,816.385 units @ $2,198.60 entry → $18.9M position
- SOL Short: -65,093.82 units @ $86.36 entry → $4.5M position
- AVAX Short: -57,673.71 units @ $9.53 entry → $439K position
- SUI Short, XRP Short, HYPE Short, FARTCOIN Short, PUMP Short

**Account Status:** Active trader with 9 open positions, total notional exposure ~$62M, moderate losses on BTC position offset by gains on altcoin shorts.

---

## Seeded Addresses

### Confirmed Active Traders

| Address | Account Value (USD) | Open Positions | Status | Source |
|---------|-------------------|-----------------|--------|--------|
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | 11,036,332 | 9 | ✓ Active | CoinGlass whale tracker |
| `0x5078c2fbea2b2ad61bc840bc023e35fce56bedb6` | 12,943 | 1 | ✓ Active | CoinGlass whale tracker |

### Why These Addresses

1. **0x5b5d51203a0f9079f8aeb098a6523a13f298c060**
   - Confirmed by CoinGlass as a whale address
   - $11M+ account value (substantial capital)
   - 9 open positions across major and alt assets
   - Diverse leverage strategies (5x–10x)
   - High trading activity
   - **Reason to track:** Multi-position whale with significant exposure

2. **0x5078c2fbea2b2ad61bc840bc023e35fce56bedb6**
   - Listed on CoinGlass whale tracker
   - Active BTC short position
   - High leverage (40x)
   - **Reason to track:** Concentrated trader, useful for market sentiment signals

### Attempted Addresses (No Positions Found)

- `0xf3f496c9486be5924a93d67e98298733bb47057c` – Account value 0.0 (abandoned)
- `0xb317d2bc2d3d2df5fa441b5bae0ab9d8b07283ae` – Account value 0.0 (abandoned)
- `0xc322736d81a6977f71c77a0a0761195649e6f7ad` – Account value ~39K, 0 positions (inactive)

### Search Sources

- **CoinGlass:** https://www.coinglass.com/hyperliquid — Real-time whale position tracking
- **HyperStats:** https://hyperstats.org/ — Leaderboard rankings by trader grade
- **HyperTracker:** https://hypertracker.io/ — 1.5M+ wallet monitor
- **Dexly Leaderboard:** https://dexly.trade/hyperliquid/leaderboard — Time-windowed rankings

---

## Notes for Integration

1. **Field Names Match Exactly** — The parser expecting `{coin, szi, entryPx, positionValue, leverage, marginSummary.accountValue}` will work without modification.

2. **Leverage Is Nested** — `leverage.type` is always `"cross"` so far; `leverage.value` is the multiplier.

3. **Negative szi = Short** — No separate short/long fields; direction encoded in sign of `szi`.

4. **Strings Not Numbers** — All numeric fields come as JSON strings (e.g., `"77160.8"`), not floats. Parser must convert.

5. **Time Field Is Milliseconds** — `"time"` is Unix timestamp in ms, not seconds.

6. **Funding Costs Tracked** — `cumFunding` object shows all-time funding paid, useful for PnL analysis.

7. **marginSummary vs crossMarginSummary** — Both identical in samples; suggests accounts use cross-margin exclusively. Monitor if divergence appears.

---

## Next Steps

1. Extend the `wallets.yaml` seed list via the web frontend (add more addresses as discovered).
2. Implement the Hyperliquid collector in `argus/collectors/hyperliquid.py`.
3. Parse positions and extract portfolio value time-series.
4. Validate PnL calculations against reported unrealizedPnl.
5. Monitor for field schema changes (e.g., new leverage types, additional margin modes).
