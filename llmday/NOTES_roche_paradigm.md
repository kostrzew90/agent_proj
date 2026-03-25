# NOTATKI: Agentic Systems Architecture - 5 Foundational Components

## Sesja: RAG vs Agentic Systems - Paradigm Shift

---

## 1. RAG vs AGENTIC SYSTEMS - FUNDAMENTALNA RÓŻNICA

### RAG (Retrieval-Augmented Generation)

**Jak działa:**
```
Query → Retrieve → Answer
```

**Charakterystyka:**
- **Stateless** - brak pamięci między zapytaniami
- **Single-shot** - jedno zapytanie, jedna odpowiedź
- **No planning** - nie planuje dalszych kroków
- **No tools** - nie może wywoływać zewnętrznych narzędzi
- **No memory** - każde zapytanie od zera

**Przykład:**
```
User: "What is Q3 revenue?"
RAG: [retrieves from docs] → "Q3 revenue was $X million"

User: "And previous quarter?"
RAG: "I don't have information about previous context"
```

### AGENTIC SYSTEM

**Jak działa:**
```
Query → Intent → Planning → Retrieval (multi-hop) → Tool Calling → Memory → Response
```

**Charakterystyka:**
- **Stateful** - pamięta kontekst rozmowy
- **Multi-step** - może wykonać wiele kroków
- **Planning** - planuje jak osiągnąć cel
- **Tools** - wywołuje API, bazy danych, zewnętrzne systemy
- **Memory** - pamięta poprzednie interakcje

**Przykład:**
```
User: "Compare Q3 revenue with Q2 and analyze the trend"

Agent:
1. [Intent] User wants multi-quarter comparison + analysis
2. [Planning] Need to:
   - Retrieve Q3 data from financial DB
   - Retrieve Q2 data from financial DB
   - Maybe retrieve Q1 for better context
   - Analyze trend
   - Consider external factors (market data?)
3. [Multi-hop Retrieval] Loop until all data gathered
4. [Tool Calling] Access financial DB, maybe Bloomberg API
5. [Memory] Store this analysis for follow-up questions
6. [Response] "Q3: $X (+Y% vs Q2: $Z). Trend analysis: ..."
```

---

## 2. 5 FOUNDATIONAL COMPONENTS AGENTIC SYSTEMS

**Kluczowa informacja:**
> "These components are NOT sequential - they are **interconnecting** with each other. It's not Component 1→2→3→4→5, they work together iteratively."

### Component 1: **INTENT INTERPRETATION**

**Co robi:**
- Rozumie **intentions** użytkownika
- Rozbija zapytanie na mniejsze części
- Identyfikuje co user **faktycznie chce osiągnąć**

**Przykład:**
```
Query: "Show me Q3 performance vs competitors and market trends"

Intent breakdown:
- Need Q3 financial data (internal)
- Need competitor data (external API?)
- Need market trends (external - Bloomberg/Reuters?)
- Need to correlate all three
- User wants comparative analysis
```

**Różnica vs RAG:**
- RAG: "Here's Q3 data" (literal answer)
- Agent: "I need to gather multiple data sources and correlate them"

---

### Component 2: **PLANNING**

**Co robi:**
- Tworzy **plan działania**
- Określa **sekwencję kroków**
- Decyduje **które źródła danych** są potrzebne
- Może **iterować** i zmieniać plan w trakcie

**Jak działa z Intent:**
- Bardzo podobne, ale Planning idzie **dalej**
- Intent: "co user chce?"
- Planning: "jak to osiągnąć krok po kroku?"

**Przykład:**
```
Plan for: "Compare Q3 with Q2 and analyze trend"

Step 1: Retrieve Q3 revenue from financial_db.reports
Step 2: Retrieve Q2 revenue from financial_db.reports
Step 3: Maybe check if Q1 data available for better context
Step 4: Call analysis function to calculate %change
Step 5: Return comparative analysis
```

**Important note:**
> "It can go to planning, it can go to memory, or it can go to retrieval - not fixed sequence!"

---

### Component 3: **RETRIEVAL** (Multi-Hop)

**Traditional RAG:**
- Query → single retrieval → answer
- One source, one hop

**Agentic Multi-Hop Retrieval:**
```
Query → Retrieval 1 → Synthesis → Retrieval 2 → ... → Retrieval N → Final Response
```

**Jak działa (przykład):**

```
Query: "Analyze our financial performance"

Hop 1: Internal financial database
  → Retrieve Q3 reports

Synthesis: "Need competitive context"

Hop 2: External API (e.g., Google Finance)
  → Retrieve competitor data

Synthesis: "Got data, need to analyze performance gaps"

Hop 3: Return to agent for analysis
  → Compare and synthesize

Hop N: Loop until desired outcome achieved
```

**Diagram flow:**
```
User Query
   ↓
Retrieve (Hop 1)
   ↓
Synthesize
   ↓
Call again? (if needed)
   ↓
Retrieve (Hop 2)
   ↓
Synthesize
   ↓
... (Loop continues)
   ↓
Final Response
```

**IMPORTANT WARNING:**
> "Multi-hop is expensive and time-consuming! It will loop and loop until it has desired outcome."

**Cost implications:**
- Each hop = API call
- Can run many times (N hops)
- Token usage multiplies

**When to use:**
- Complex queries requiring multiple data sources
- When single retrieval insufficient
- When synthesis between retrievals needed

---

### Component 4: **TOOL CALLING**

**Co to jest:**
- Zdolność do **wywoływania zewnętrznych narzędzi/API**
- RAG NIE MA tej możliwości

**Przykłady tools:**
- Internal APIs (financial DB, CRM, ERP)
- External APIs (Bloomberg, Google Finance, weather)
- Databases (SQL queries)
- Computational functions (calculations, analysis)

**Przykład:**
```
Query: "Get Q3 revenue from our firm"

Tool calls:
1. financial_db.get_quarterly_report(quarter="Q3", year=2024)
2. Maybe: external_api.get_market_data() for context
3. analysis_function.calculate_variance(Q3, Q2)
```

**Integration with other components:**
- Intent → determines which tools needed
- Planning → sequences tool calls
- Retrieval → may trigger tool calls mid-process
- Memory → stores tool call results

---

### Component 5: **MEMORY**

**Dlaczego to najważniejsze:**
> "Memory is one of the **complete and complete component** - most important!"

**Types of Memory:**

**1. Short-term Memory (Past Interactions):**
```
User: "What was Q3 revenue?"
Agent: "$5M"

User: "And previous quarter?"
Agent: [remembers context] "$4.5M in Q2"
```

**2. Semantic Memory:**
- Understands business domain
- Knows relationships between concepts
- "Q3 performance" → links to revenue, costs, margins

**3. Episodic Memory:**
- Remembers past workflows
- "Last time user asked about revenue, they also wanted margin analysis"
- Can proactively suggest: "Would you also like margin breakdown?"

**Różnica vs RAG:**
- **RAG:** "I don't have information about previous context, sorry"
- **Agent:** Uses memory to understand follow-up questions

**Real-world implications:**

Example conversation:
```
User: "Show me revenue"
Agent: [retrieves] "$5M in Q3"
[MEMORY STORES: user_interest = revenue, quarter = Q3]

User: "What about costs?"
Agent: [remembers Q3 context] "Q3 costs were $3M"
[MEMORY UPDATES: user_interest += costs]

User: "Calculate margin"
Agent: [remembers Q3 revenue + costs] "Margin is 40%"
[MEMORY: user_workflow = financial_analysis]

Later...
User: "Same analysis for Q4"
Agent: [recalls entire workflow from memory]
      "Q4: Revenue $5.5M, Costs $3.2M, Margin 41.8%"
```

---

## 3. COMPONENT INTERACTIONS - FLOW EXAMPLES

### Example 1: Simple Financial Query

```
User: "What's Q3 revenue?"

Flow:
1. Intent: User wants Q3 financial data
2. Planning: Access financial_db.reports
3. Retrieval: Single-hop (no complexity)
4. Tool Calling: financial_db.get_report(Q3)
5. Memory: Store Q3 context
6. Response: "$5M"
```

### Example 2: Complex Multi-Source Query

```
User: "Compare our Q3 performance with competitors and market"

Flow:
1. Intent: Multi-source comparison needed
   - Internal: our Q3 data
   - External: competitor data
   - External: market trends

2. Planning:
   - Step 1: Get our Q3 from internal DB
   - Step 2: Get competitor data from external API
   - Step 3: Get market data
   - Step 4: Synthesize all three

3. Multi-Hop Retrieval:
   Hop 1: Internal financial_db → our data
   Synthesize: "Need competitor context"
   Hop 2: External API (Bloomberg?) → competitor data
   Synthesize: "Need market trends"
   Hop 3: Market data API → industry trends
   Synthesize: "Got all data, ready to compare"

4. Tool Calling:
   - SQL query to financial_db
   - API call to Bloomberg/Reuters
   - API call to market data provider
   - Analysis function for comparison

5. Memory:
   - Store all retrieved data
   - Remember user wants comparative analysis
   - Next time: faster retrieval

6. Response:
   "Our Q3: $5M (+10%)
    Competitor A: $4.8M (+8%)
    Market average: +7%
    Analysis: We're outperforming market by 3pp"
```

---

## 4. ARCHITECTURAL CONSIDERATIONS

### When NOT to use Agentic System:

❌ **Simple Q&A** - RAG is faster and cheaper
❌ **Single-source data** - RAG sufficient
❌ **Budget-constrained** - Multi-hop expensive
❌ **Latency-sensitive** - Agents slower (multiple iterations)

### When to use Agentic System:

✅ **Complex queries** requiring multiple data sources
✅ **Multi-step workflows** (e.g., "analyze AND recommend")
✅ **Context-dependent** interactions (memory needed)
✅ **Tool integration** necessary (API calls, DB queries)
✅ **Iterative refinement** (loop until good answer)

---

## 5. PRACTICAL EXAMPLES FROM PRESENTATION

### Example: "Why did sales drop?"

**RAG approach:**
```
Query: "Why did sales drop?"
RAG: "I can show you sales data" [retrieves chart]
→ User has to interpret themselves
```

**Agentic approach:**
```
Query: "Why did sales drop?"

Agent workflow:
1. Intent: User wants root cause analysis
2. Planning:
   - Get sales data (last 3 months)
   - Get market trends
   - Get competitor activity
   - Get internal factors (inventory, marketing spend)
3. Multi-hop retrieval:
   - Sales DB → recent sales trend
   - CRM → customer feedback/complaints
   - Marketing DB → campaign performance
   - External API → market conditions
4. Tool calling:
   - Run correlation analysis
   - Compare with historical patterns
5. Memory:
   - Remember user is investigating sales drop
   - Store analysis for follow-up
6. Response:
   "Sales dropped 15% in Q3. Analysis shows:
    - Competitor launched new product (external factor)
    - Our marketing spend down 20% (internal)
    - Customer satisfaction scores dropped (CRM data)
    Recommendation: Increase marketing, address satisfaction issues"
```

---

## 6. FEEDBACK LOOP (OPTIONAL ENHANCEMENT)

**Dodatkowo można dodać:**
```
Agent → Partial Response → User Feedback → Incorporate → Final Response
```

**Przykład:**
```
Agent: "Here's Q3 analysis. Is this what you needed?"
User: "Yes, but also show me regional breakdown"
Agent: [incorporates feedback] → Enhanced response with regional data
```

**Tools that do this:**
- Claude (sometimes asks: "Is this response good for you?")
- ChatGPT (can ask clarifying questions)

---

## 7. KLUCZOWE CYTATY Z PREZENTACJI

### O RAG:
> "Classical RAG is phenomenal for what it was designed for. But there are things missing in RAG system."

### O Planning:
> "In RAG, there is no planning. It will not tell you WHY it's giving the particular answer."

### O Memory:
> "In typical RAG system, there is no memory because it's stateless. You query, get answer, that's it. If you ask follow-up, it will say 'I don't have the information, sorry.'"

### O Multi-Hop:
> "It will loop and loop and loop until it finds the desired outcome to return to the user."

**Warning:**
> "If we are going to do multi-hop, be careful - it's expensive and time consuming."

### O Component Interactions:
> "Those components are not sequential. They are interconnecting with each other. Sometimes it can call - after intent - it can go to planning, it can go to memory, or it can go to retrieval."

> "I just wanted to make it easier to understand, so I called them Component 1,2,3,4,5. But those are interconnected, working interactively."

---

## 8. TECHNICAL DETAILS

### Multi-Hop Retrieval Pattern

**Visualized:**
```
┌─────────────┐
│    Query    │
└──────┬──────┘
       ↓
┌─────────────┐
│ Retrieval 1 │──→ Internal DB
└──────┬──────┘
       ↓
┌─────────────┐
│  Synthesize │
└──────┬──────┘
       ↓
    Need more?
    Yes ↓
┌─────────────┐
│ Retrieval 2 │──→ External API
└──────┬──────┘
       ↓
┌─────────────┐
│  Synthesize │
└──────┬──────┘
       ↓
    ...continues...
       ↓
┌─────────────┐
│   Hop N     │──→ Additional sources
└──────┬──────┘
       ↓
┌─────────────┐
│ Final Resp  │
└─────────────┘
```

**Loop mechanism:**
- `while (!desiredOutcome)` logic
- Each iteration can call different sources
- Synthesis step determines: "do I have enough?"

**Cost factors:**
- N hops = N API calls
- Each synthesis = LLM invocation
- Token usage: Input (context) + Output (each hop)

---

## 9. COMPARISON TABLE

| Feature | RAG | Agentic System |
|---------|-----|----------------|
| **Planning** | ❌ No | ✅ Yes |
| **Memory** | ❌ Stateless | ✅ Stateful |
| **Tool Calling** | ❌ No | ✅ Yes |
| **Multi-Hop** | ❌ Single retrieval | ✅ Iterative loops |
| **Intent Understanding** | ⚠️ Basic | ✅ Deep |
| **Cost** | 💰 Low | 💰💰💰 High |
| **Latency** | ⚡ Fast | 🐌 Slower |
| **Complexity** | 📊 Simple | 🧠 Complex |
| **Use Case** | Q&A, lookup | Analysis, workflows |

---

## 10. KLUCZOWE WNIOSKI

### Architectural:

✅ **5 components są foundational** - każdy agentic system powinien je mieć
✅ **Nie są sekwencyjne** - współpracują dynamicznie
✅ **Memory = najważniejszy** komponent dla user experience
✅ **Multi-hop = potężny ale drogi** - use wisely
✅ **Planning odróżnia** agents od RAG fundamentalnie

### Practical:

✅ **RAG nie jest zły** - fenomenalny do simple Q&A
✅ **Don't use agents everywhere** - evaluate cost/benefit
✅ **Multi-hop needs limits** - set max iterations
✅ **Memory enables conversations** - kluczowe dla UX
✅ **Tool calling = superpowers** - integration with real systems

### Business:

✅ **Agents for complex workflows** - analysis, recommendations
✅ **RAG for simple lookups** - fast and cheap
✅ **Cost-conscious design** - multi-hop can be expensive
✅ **Latency matters** - agents slower than RAG
✅ **Real integration** - tools must connect to actual systems (CRM/ERP/BI)

---

## 11. IMPLEMENTATION CONSIDERATIONS

### Design Decisions:

**Question 1: Do I need memory?**
- Simple Q&A → No (RAG fine)
- Multi-turn conversation → Yes (Agent needed)

**Question 2: Do I need multiple data sources?**
- Single source → RAG sufficient
- Multiple sources → Agent with multi-hop

**Question 3: Budget constraints?**
- Tight budget → RAG or limited-hop agent
- Flexible budget → Full agentic with multi-hop

**Question 4: Latency requirements?**
- <1 second → RAG only
- <10 seconds → Agent with hop limits
- Flexible → Full multi-hop agent

### Implementation Pattern:

```python
class AgenticSystem:
    def __init__(self):
        self.intent_interpreter = IntentModule()
        self.planner = PlanningModule()
        self.retriever = MultiHopRetriever(max_hops=5)  # Limit!
        self.tool_caller = ToolCaller()
        self.memory = ConversationMemory()

    def process_query(self, query):
        # 1. Intent
        intent = self.intent_interpreter.analyze(query)

        # 2. Planning (can skip if simple)
        if intent.complexity == "high":
            plan = self.planner.create_plan(intent)

        # 3. Multi-hop retrieval
        data = self.retriever.retrieve(intent, max_hops=5)

        # 4. Tool calling (if needed)
        if intent.requires_tools:
            results = self.tool_caller.execute(plan.tools)

        # 5. Memory update
        self.memory.store(query, intent, data, results)

        # 6. Generate response
        return self.generate_response(data, results, self.memory)
```

---

## 12. REAL-WORLD ARCHITECTURES

### Microsoft Fabric Data Agent (mentioned in talk)

**Use case:** "Why did sales drop?"

**Architecture:**
```
User Query → Intent (root cause analysis)
          ↓
       Planning:
       - Sales data retrieval
       - Customer feedback analysis
       - Market condition check
       - Competitor activity
          ↓
   Multi-hop retrieval:
   Hop 1: Sales DB
   Hop 2: CRM database
   Hop 3: External market data API
          ↓
    Tool Calling:
    - SQL queries
    - API calls
    - Analysis functions
          ↓
      Memory:
      Store analysis context
          ↓
    Response with insights
```

### Semantic Kernel - Intelligent Routing (mentioned)

**Challenge:**
```
Query: "How much does product A cost AND what are your business hours?"
```

**Traditional RAG:** Fails (two questions in one)

**Semantic Kernel Agentic Approach:**
```
1. Intent: Detects TWO separate questions
   - Product pricing question
   - Business hours question

2. Planning: Route to different sources
   - Product DB for pricing
   - Business info KB for hours

3. Parallel retrieval (not sequential)

4. Synthesize both answers

5. Response:
   "Product A costs $X.
    Our business hours are 9AM-5PM Monday-Friday."
```

---

## BONUS: Q&A HIGHLIGHTS (If any were captured clearly)

[Note: Transkrypcja była bardzo niska jakość w tej części, więc niewiele wyraźnych Q&A]

**General theme detected:**
- Audience interested in practical implementations
- Questions about cost management for multi-hop
- Questions about when RAG sufficient vs when need full agent
- Concerns about latency for real-time applications

---

## RESOURCES & NEXT STEPS

**Frameworks mentioned:**
- Microsoft Semantic Kernel - routing and orchestration
- Microsoft Fabric - data agent examples
- Prompt Flow - testing & observability (from earlier talks)

**Key concepts to research:**
- Multi-hop retrieval optimization
- Memory management in long conversations
- Tool calling security and sandboxing
- Cost optimization for agentic systems
- Latency reduction techniques

**Best practices:**
- Start with RAG, upgrade to agent when needed
- Set max_hops limits (prevent infinite loops)
- Implement memory pruning (don't store everything forever)
- Monitor costs per query
- Cache common retrievals
- Use cheaper models for intent/planning, expensive for final response

---

## FINAL THOUGHTS

**Paradigm shift:**
> RAG → "Lookup and answer"
> Agent → "Understand, plan, research, analyze, remember, respond"

**When mature:**
Agentic systems will become standard for:
- Enterprise assistants
- Complex workflows
- Multi-system integrations
- Conversational AI (beyond chatbots)

**Current state:**
- RAG: Production-ready, well understood
- Agentic: Emerging, expensive, powerful but needs careful design

**Future:**
- Hybrid approaches (RAG for simple, Agent for complex)
- Better cost optimization
- Faster inference (reducing latency gap)
- Standardized frameworks (like Semantic Kernel evolving)
