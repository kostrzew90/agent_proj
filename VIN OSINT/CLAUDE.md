# CLAUDE.md — VINhunter

## Project Overview

Personal OSINT tool for verifying ~20-year-old used cars from EU before purchase.

- **Stack**: FastAPI + Vue 3 + PostgreSQL + Playwright (Chromium + Firefox)
- **Docker**: `docker compose up -d --build` in `VIN OSINT/vinhunter/`
- **Ports**: frontend **3010**, backend **8200**, DB **5436**
- **Full spec**: `VIN_osint.MD`
- **Progress**: `PROGRESS.md` (READ THIS FIRST in new sessions)

## Architecture

```
vinhunter/
├── backend/          # FastAPI app
│   ├── plugins/      # Scanner plugins (each file = one data source)
│   ├── models/       # SQLAlchemy models
│   ├── routes/       # API endpoints
│   └── services/     # Business logic, plugin orchestrator
├── frontend/         # Vue 3 SPA
└── docker-compose.yml
```

## Current Status

- **16 plugins** registered, 5 working, 6 disabled (Cloudflare + Google blocks)
- Scan time: ~22s (optimized from 36s)
- **NHTSA**: 4 endpoints working (decode, recalls, complaints, safety) — free
- **Vincario**: requires API key (VIN decoder)
- **Yandex Images**: works but occasional CAPTCHA

## Key Patterns

- **Cloudflare**: UNBEATABLE — Firefox+stealth doesn't help, plugins disabled
- **DB**: user `vinhunter` / pass `vinhunterpass`, port 5436
- **varchar(20)** on status field — max status length: `done_with_errors`
- **Playwright**: Chromium + Firefox installed in container
- **pydantic-settings v2**: `list[str]` from env var doesn't work — use `str` + property
- **Plugins with API key**: property `enabled` returns `bool(key)` — auto-disable without key

## Plugin Development

Each plugin in `backend/plugins/` is a Python file implementing a scanner interface:
1. Create plugin file
2. Register in plugin orchestrator
3. Set `enabled` property (API key check if needed)
4. Return structured results

## Potential Data Sources (researched)

- **carVertical API** (~EUR 8-25/report) — best pan-EU damage history (300M+ records, 40 countries)
- **CEBIA** — Czech specialist (200M+ records from 32 countries)
- **autoDNA** — 26 EU countries, 50k+ institutions
- **Czech STK API** — free, public, technical inspection history (Ministry of Transport)
- See `VIN_SOURCES_RESEARCH.md` for full analysis
