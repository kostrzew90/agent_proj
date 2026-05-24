# scrape-autocentrum

## When to use
When asked to scrape autocentrum.pl for a specific car make and model, or when the nightly cron triggers at 2:00.

## Steps
1. Use Brave Search (or browser-mcp Google fallback) to find the autocentrum.pl page for the make/model: `site:autocentrum.pl [make] [model] test opinia`
2. Navigate to the found URL with browser-mcp
3. Extract editorial review: find "Test" or "Opinia redakcji" link, navigate, scrape title + full text + rating (scale 1-10)
4. Extract owner opinions: find "Opinie użytkowników" section, scrape up to 50 entries per model (text + rating + date). Follow "następna strona" pagination.
5. For each text (editorial chunks of 800 chars, full owner opinions): generate embedding via Ollama POST /api/embed with model qwen3-embedding:0.6b
6. INSERT to autocentrum_models and autocentrum_reviews
7. Report: "Scraped [make] [model]: 1 editorial + N owner opinions → DB"

## Tools needed
- browser_google_search or browser_navigate (browser-mcp)
- psycopg2 (direct DB connection)
- httpx POST to Ollama /api/embed

## Watch out for
- autocentrum.pl may rate-limit: add 2s sleep between page navigations
- Ratings appear as "8.5/10" or "4/5" — normalize to 0-10 (divide x/5 by 0.5)
- Owner opinion text may be very short (< 50 chars) — skip embeddings, insert content only
- Always use ON CONFLICT DO NOTHING on autocentrum_models.url to keep handler idempotent

## Example
Input: `/skill scrape-autocentrum BMW Seria3`
Output: "✅ autocentrum scrape: BMW Seria 3 — 1 recenzja redakcji + 38 opinii właścicieli zapisanych do bazy"
