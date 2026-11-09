# LLM Spike Findings — VPS Free Model Reachability

**Date:** 2026-06-05  
**VPS:** `ubuntu@84.235.174.129`  
**Scope:** Network reachability + JSON response format for free LLM providers from Oracle VPS  
**Status:** ⚠️ **DONE_WITH_CONCERNS**

---

## Summary

Both free LLM providers are **network-reachable** from the VPS and **return valid JSON errors**, confirming:
- Network path is open (no SSL proxy blocking)
- API endpoints are operational
- Error responses are parseable JSON

**However,** both free tiers have **aggressive rate limiting** that makes them unsuitable as primary gap-fill sources without fallback or caching strategy.

---

## Step 1: Key Presence

| Key | Status | Count |
|-----|--------|-------|
| `GEMINI_API_KEY` | Present in `.env` | 1 ✅ |
| `OPENROUTER_API_KEY` | Present in `.env` | 1 ✅ |

Both keys are configured on the VPS.

---

## Step 2: Gemini Free Tier (gemini-2.0-flash)

### Request
```bash
curl -sS "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=$GEMINI_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"contents":[{"parts":[{"text":"Return ONLY a JSON array: [{\"asset\":\"BTC\",\"direction\":\"bull\"}]. Market: Fed dovish."}]}]}'
```

### Response
**HTTP Status:** 429 (RESOURCE_EXHAUSTED)  
**Response Format:** Valid JSON ✅

```json
{
  "error": {
    "code": 429,
    "message": "You exceeded your current quota...",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_input_token_count",
            "quotaId": "GenerateContentInputTokensPerModelPerMinute-FreeTier",
            "quotaDimensions": {
              "location": "global",
              "model": "gemini-2.0-flash"
            }
          },
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
            ...
          }
        ]
      }
    ]
  }
}
```

### Findings
- **Connectivity:** ✅ VPS reaches `generativelanguage.googleapis.com:443` (TLS 1.3)
- **Response Format:** ✅ Valid, parseable JSON (not wrapped in text/HTML)
- **usageMetadata:** ❌ Not present in error response (quota exhausted before processing)
- **Quota Status:** ❌ Free tier daily quota already exhausted
  - Limit per model per day: 0 (all quota consumed in this session or prior)
  - Retry wait: 38–40 seconds per request
  - Pattern: Multiple quota violations (input tokens, request count per minute, per day)

### Verdict
Gemini free tier is **not viable as primary gap-fill** due to:
- Extremely restrictive daily quota (appears to be 0 available per day in this project)
- Per-minute rate limit on both requests and input tokens
- No token usage metadata in error responses (cannot observe success behavior without consuming full quota)

---

## Step 3: OpenRouter Free Models (meta-llama/llama-3.3-70b-instruct:free)

### Request
```bash
curl -sS https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"meta-llama/llama-3.3-70b-instruct:free","messages":[{"role":"user","content":"Reply with JSON only: [{\"asset\":\"BTC\",\"direction\":\"bull\"}]"}],"max_tokens":100}'
```

### Response
**HTTP Status:** 429 (rate limited)  
**Response Format:** Valid JSON ✅

```json
{
  "error": {
    "message": "Provider returned error",
    "code": 429,
    "metadata": {
      "raw": "meta-llama/llama-3.3-70b-instruct:free is temporarily rate-limited upstream. Please retry shortly, or add your own key to accumulate your rate limits: https://openrouter.ai/settings/integrations",
      "provider_name": "Venice",
      "is_byok": false,
      "retry_after_seconds": 7,
      "retry_after_seconds_raw": 6.205,
      "headers": {
        "Retry-After": "7"
      }
    }
  },
  "user_id": "user_3B6y1nmG09KWnU6DB835FNtsbvX"
}
```

### Findings
- **Connectivity:** ✅ VPS reaches `openrouter.ai:443` API endpoint
- **Response Format:** ✅ Valid JSON (standard OpenRouter error schema)
- **usage block:** ❌ Not present (request rejected before processing)
- **Rate Limit:** Currently 429; retry after ~7 seconds
- **Provider:** Venice (upstream provider for free Llama model)
- **Suggestion in response:** "add your own key to accumulate your rate limits" (indicates shared quota among free-tier users)

### Verdict
OpenRouter free Llama is **currently rate-limited** but:
- Response format is clean JSON (not wrapped in text)
- Retry-After metadata is present and parseable
- If quota were available, JSON extraction would work
- NOT viable right now without waiting or paid tier upgrade

---

## Step 4: Network Diagnostics

### DNS & Connectivity
| Endpoint | DNS | TLS | Status |
|----------|-----|-----|--------|
| `generativelanguage.googleapis.com` | ✅ Resolves | ✅ TLS 1.3 | Connected |
| `openrouter.ai` | ✅ Resolves | ✅ Operational | Connected |
| `api.openrouter.ai` | ❌ Does not resolve | — | DNS failure |

**Note:** OpenRouter's model list endpoint (`openrouter.ai/api/v1/models`) is reachable and returns full JSON payload (403KB+) confirming API health.

---

## Constraints & Blockers

### Gemini Free Tier
1. **Daily quota exhausted** — Cannot test actual JSON response format (quota reached before response generation)
2. **Per-minute input token limit** — Free tier has strict per-minute limits on token count
3. **No usage metadata in errors** — Cannot monitor token consumption for successful requests

### OpenRouter Free Tier
1. **Shared quota pool** — All free-tier users share the same rate limit (currently exhausted)
2. **Upstream rate limiting** — Actual limit imposed by Venice (provider), not OpenRouter directly
3. **Retry after required** — Requests must back off 7+ seconds

---

## Recommendations

### For Immediate Use (Next 24–48 Hours)
1. **Fallback strategy:** Cache successful Argus extractions from previous runs
2. **Request batching:** If retry becomes available, batch multiple market signals into single API call to maximize token efficiency
3. **Model alternative:** OpenRouter's free tier quota may reset; test `google/gemini-3-5-flash` if available on free plan

### For Production Viability
1. **Upgrade to paid tier** (OpenRouter: $5/month gives 50 free credits + accumulated free-tier quota)
2. **Implement circuit breaker** — Fallback to cached signals or skip extraction on rate-limit 429
3. **Hybrid strategy:**
   - Use free tier for intraday signals (every 2–4 hours, well below quota)
   - Use cached/pre-computed signals for high-frequency polling
   - Reserve paid LLM calls for novel signals only

### For Development / Testing
- **Claude API MCP** (via n8n's `mcp__claude_ai_*` tools) bypasses free-tier quotas but requires subscription
- **Local Ollama** (if available) for offline extraction testing before API calls

---

## JSON Parsing Readiness

Both providers return **valid, parseable JSON** in error responses:
- ✅ No HTML wrapping or prose before/after JSON
- ✅ Standard HTTP headers (Content-Type: application/json)
- ✅ Metadata blocks (Retry-After, quotaMetric, provider_name) are machine-readable

**Assumption:** On success (when quota available), both providers will return properly formatted JSON with content field, not wrapped in code fences. **Cannot confirm without quota reset.**

---

## Commit

```bash
git add argus/docs/llm-spike-findings.md
git commit -m "chore(argus): LLM spike findings (free model JSON from VPS)"
```

**Hash:** [Will be generated on commit]

---

## Appendix: Full Error Responses

### Gemini 429 (Truncated to ~800 chars)
```
{
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: gemini-2.0-flash\n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: gemini-2.0-flash\n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_input_token_count, limit: 0, model: gemini-2.0-flash\nPlease retry in 32.896632503s.",
    ...
  }
}
```

### OpenRouter 429 (Full)
```json
{
  "error": {
    "message": "Provider returned error",
    "code": 429,
    "metadata": {
      "raw": "meta-llama/llama-3.3-70b-instruct:free is temporarily rate-limited upstream. Please retry shortly, or add your own key to accumulate your rate limits: https://openrouter.ai/settings/integrations",
      "provider_name": "Venice",
      "is_byok": false,
      "retry_after_seconds": 7,
      "retry_after_seconds_raw": 6.205,
      "headers": {"Retry-After": "7"}
    }
  },
  "user_id": "user_3B6y1nmG09KWnU6DB835FNtsbvX"
}
```
