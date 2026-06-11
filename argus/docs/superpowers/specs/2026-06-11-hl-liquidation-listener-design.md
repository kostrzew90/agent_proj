# Argus — Hyperliquid Liquidation Listener (Inc 8)

**Date:** 2026-06-11  
**Status:** Approved for implementation  
**Branch:** feat/argus-phase1

---

## Problem

The original Binance `!forceOrder@arr` WebSocket is blocked on Oracle Cloud Amsterdam (HTTP 101 handshake succeeds, server closes with code 1000 immediately). The `liq-listener` container has been in a circuit-breaker loop since deployment, writing 0 liquidation records.

Hyperliquid does not expose a public market-wide liquidation stream. The only available path is `userEvents` per wallet address, which delivers liquidation events when a specific tracked wallet is liquidated.

**Design decision (Fable-reviewed):** Record liquidations as market-context only — no automatic scoring penalty. Scoring stays purely outcome-based. After 30 days of data, revisit whether liquidation events predict future claim misses.

---

## What We're Building

Replace the Binance listener with a Hyperliquid WebSocket listener that:

1. Subscribes to `userEvents` for every tracked whale wallet (kind='hyperliquid' sources)
2. On liquidation event → reconstructs per-asset liquidation records from `wallet_positions`
3. Inserts into existing `liquidations` table (no schema migration)
4. Dynamically subscribes to new wallets added at runtime (no restart needed)
5. Same reconnect + circuit-breaker pattern as Binance listener

---

## Verified Facts (tested before writing spec)

- `wss://api.hyperliquid.xyz/ws` connects from Oracle Cloud VPS ✅
- `userEvents` subscription returns `subscriptionResponse` correctly ✅
- `wallet_positions.coin` uses bare ticker (e.g. "BTC") matching `assets.symbol` ✅
- Some coins in `wallet_positions` (SOL, AVAX, HYPE, FARTCOIN) are not in `assets` → skip silently ✅

---

## Architecture

### Single file: `argus/liquidations/hl_listener.py`

Replaces `argus/liquidations/listener.py` as the entrypoint for the `liq-listener` container.

```
Startup
  └── load wallet addresses from sources (kind='hyperliquid', active=true)
  └── load asset symbol set from assets table
  └── connect to wss://api.hyperliquid.xyz/ws
  └── subscribe userEvents for each wallet

Runtime loop
  └── recv message
      ├── subscriptionResponse → log, ignore
      ├── userEvents + liquidation key → handle_liquidation()
      └── userEvents + other keys (fills, etc.) → ignore

handle_liquidation(wallet_address, event_ts)
  └── load open wallet_positions for this source_id
  └── filter to positions where coin ∈ assets
  └── for each position → insert Liquidation(
          asset=coin,
          exchange='hyperliquid',
          side='long_liq' if side=='long' else 'short_liq',
          price=entry_px,          # best available; not exact liq price
          qty=abs(szi),
          notional_usd=position_value,
          raw_symbol=coin,
          ts=event_ts
      )
  └── mark wallet_positions.open=False for liquidated wallet

Dynamic re-sync (every 30 min)
  └── query sources for new wallets
  └── send subscribe for any address not yet subscribed
  └── (no unsubscribe — deactivated wallets just stop getting events)
```

### Reconnect / circuit breaker

Identical to Binance listener:
- On disconnect: exponential backoff 1→2→4→…→30s
- Circuit breaker: 5 fails in 10 min → 60s pause
- On reconnect: re-subscribe all wallets

### Price field caveat

HL `liquidation` event does NOT include the exact liquidation price per asset. We store `entry_px` from `wallet_positions` as `price` — this is the whale's entry, not the liquidation price. The field is accurate enough for market-context purposes (the dashboard shows notional, not exact price).

---

## HL WebSocket Protocol

**URL:** `wss://api.hyperliquid.xyz/ws`

**Subscribe (one per wallet):**
```json
{"method": "subscribe", "subscription": {"type": "userEvents", "user": "0x<address>"}}
```

**Liquidation event shape:**
```json
{
  "channel": "userEvents",
  "data": {
    "user": "0x<address>",
    "liquidation": {
      "lid": 12345,
      "liquidator": "0x<liquidator>",
      "liquidated_user": "0x<address>",
      "liquidated_ntl_pos": "50000.5",
      "liquidated_account_value": "1234.56"
    }
  }
}
```

**Other `userEvents` types to ignore:** `fills`, `funding`, `liquidation` (own fills from liquidator side).

---

## Data Flow

```
HL WS → liquidation event for 0xABC
  → SELECT wallet_positions WHERE source.handle='0xABC' AND open=true
  → filter: coin IN ('BTC','ETH','XRP',...) [assets table]
  → INSERT INTO liquidations (asset=coin, exchange='hyperliquid', ...)
  → UPDATE wallet_positions SET open=false WHERE source_id=X
```

---

## Files Changed

| File | Change |
|------|--------|
| `argus/liquidations/hl_listener.py` | NEW — full listener |
| `docker-compose.yml` | `command: python -m argus.liquidations.hl_listener` |

**Not changed:** DB schema, `liquidations` model, dashboard endpoints (already read `exchange='hyperliquid'` agnostically).

---

## Out of Scope

- Market-wide liquidation data (not available from HL without third-party service)
- Scoring penalty on liquidation (Fable review: double-counts outcome scorer, measures leverage not credibility)
- Exact per-asset liquidation price (not in HL event payload)
- Liquidation alerts to Telegram (future increment if needed)

---

## Tests

| Test | Assertion |
|------|-----------|
| `test_parse_hl_liquidation_event` | Valid event → returns per-asset records for watchlist coins only |
| `test_parse_hl_liquidation_event_unknown_coin` | Coin not in assets → skipped, no error |
| `test_parse_hl_liquidation_event_no_open_positions` | No open positions → empty result, no crash |
| `test_hl_listener_reconnect` | On exception → reconnects with backoff |
| `test_hl_listener_dynamic_subscribe` | New wallet added mid-run → subscribed without restart |

---

## Success Criteria

- `liq-listener` container connects and stays connected (no circuit-breaker loop)
- `docker logs argus-liq-listener-1` shows "connected, watching N wallets" (not reconnect spam)
- Next time a tracked whale is liquidated → row appears in `liquidations` table with `exchange='hyperliquid'`
- Dashboard `/api/liquidations` returns HL liquidations correctly (no code change needed)
