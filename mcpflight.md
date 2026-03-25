Building a thick client application for quick cheap flight searches from Polish airports (like WAW or KRK) to Alps destinations like the French Alps, Italian Alps, Zermatt, or Dolomites is a solid, practical idea. It aligns well with your AI infrastructure expertise and could integrate seamlessly with OpenWebUI or cloud setups for fast price checks via LLM-powered queries.

Feasibility
Flight search APIs exist but lack truly unlimited free access; most offer free tiers or quotas suitable for prototyping and personal use. Approval processes (e.g., Skyscanner for partners) or paid upgrades apply for production-scale apps, but test environments like Amadeus provide thousands of free monthly calls with real-time data. Scraping alternatives (e.g., via SerpApi for Google Flights) are possible but riskier due to terms of service.

Recommended APIs
Use developer-friendly options with free quotas for cheap deals and multi-city searches.

API	Free Tier	Key Features	Best For
Amadeus Flight Offers Search	Up to 10,000 calls/month in production; unlimited test data	Real-time pricing, filters for cheap flights, Europe coverage including Poland-Alps routes	Full search + booking flow
Skyscanner Flights API	Basic free tier (approval needed)	Cached/live prices, flexible searches (e.g., cheapest month to French Alps)	Price calendars and comparisons
Kiwi.com (Skypicker)	Partner integration (not fully public free)	Virtual interlining for multi-leg cheap routes to Dolomites/Zermatt	Non-stop + connecting deals
Aviationstack	100 calls/month	Real-time status/pricing (limited)	Quick status checks alongside prices
Start with Amadeus—sign up for a test API key at developers.amadeus.com.
​

Implementation Tips
Build a desktop thick client using Electron or Tauri (Rust/Web tech) for cross-platform speed, with Python backend for API calls and caching in Postgres. Integrate OpenWebUI/Ollama for natural queries like "cheap flights Poland to French Alps next month," routing to APIs via n8n workflows you already use. Cache results in pgvector for RAG-enhanced responses, enabling fast offline checks. Deploy on cloud (AWS/EC2) or local Docker for low-latency.