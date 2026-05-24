# vinhunter-plugin-writer

## When to use
After `vinhunter-researcher` produces a report. Triggered manually via `/skill vinhunter-write-plugin [source_name]`.

## Steps
1. Find latest `audit/vinhunter-research-*.md` report
2. Read 2 existing plugins as code templates: `nhtsa.py` (vin_decode) + `nl_rdw.py` (registries)
3. LLM (hard tier, max 2048 tokens) generates complete plugin .py file
4. Via mcp-fs-vinhunter:
   a. `git_checkout_branch("hermes/plugin-{source_name}")` — create local branch
   b. `fs_write_file("backend/plugins/{category}/{source_name}.py", code)` — write file
   c. `git_commit("feat(plugins): add {source_name} plugin (hermes-generated)")` — commit
5. Alumnium health check on VINhunter backend (optional — skip if not running)
6. Telegram: ✅ plugin written + file path + branch name + next steps

## Tools needed
- `fs_read_file`, `fs_write_file`, `git_checkout_branch`, `git_commit` (mcp-fs-vinhunter)
- `al_navigate` (mcp-alumnium) — optional health check
- `llm_client.call_llm(prompt, tier="hard", max_tokens=2048, skill="vinhunter-plugin-writer")`

## Watch out for
- LLM may wrap code in ```python fences — strip them before writing
- Category detection: check for `REGISTRY`, `DAMAGE`, `PHOTO_OSINT`, `ADS_ARCHIVE` in generated code
- VINhunter needs restart to load new plugin (hot-reload not supported)
- git_push will fail (local-only repo, no remote) — that's expected, mention it in output

## Example
Input: `/skill vinhunter-write-plugin rdw_open_data`
Output: "✅ Plugin `rdw_open_data` napisany.\nPlik: backend/plugins/registries/rdw_open_data.py\nBranch: hermes/plugin-rdw_open_data\nZrestartuj VINhunter żeby załadować plugin."
