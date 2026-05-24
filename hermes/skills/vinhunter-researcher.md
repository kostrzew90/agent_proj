# vinhunter-researcher

## When to use
Every 7 days at 10:00 (cron) or manually via `/skill vinhunter-research`.

## Steps
1. List existing plugins via mcp-fs-vinhunter `fs_list_dir("backend/plugins")` — see what categories exist
2. Brave Search (3 queries, deduplicated by domain):
   - `"VIN API EU free 2026"`
   - `"car history database API Europe"`
   - `"vehicle registry open data API"`
3. LLM (medium tier) scores each new source on 4 axes:
   - Type: API REST (5) / scraping (3) / open data file (3)
   - Coverage: EU (5) / global (3) / US only (1)
   - Cost: free (5) / freemium (3) / paid (1)
   - Difficulty: easy (5) / medium (3) / hard (1)
   Total score: 0-20
4. Write report to `audit/vinhunter-research-YYYY-MM-DD.md` (markdown table + Top 3 section)
5. Telegram: top source name + score + ask if to write plugin

## Tools needed
- `fs_list_dir` (mcp-fs-vinhunter)
- `_brave_search` (bridge built-in)
- `llm_client.call_llm(prompt, tier="medium", skill="vinhunter-research")`

## Watch out for
- Deduplicate search results by domain (same URL from multiple queries)
- Report filename must use ISO date YYYY-MM-DD (plugin-writer finds latest by glob sort)
- If Brave Search returns 0 results, report error and skip LLM

## Example
Cron trigger: 10:00
Output Telegram: "🔍 VINhunter research — 2026-05-30\nRaport: audit/vinhunter-research-2026-05-30.md\nNajlepsze: RDW Open Data (score 18/20)\n\nNapisać plugin? /skill vinhunter-write-plugin rdw_open_data"
