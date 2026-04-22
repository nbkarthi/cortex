# Cortex

**AI-Powered Investment Analyst Platform**

Cortex is an end-to-end AI investment research system that ingests financial data, analyzes earnings transcripts, tracks sentiment and narrative shifts, and generates institutional-quality IC memos. Designed so 1-2 people can operate with the output of a full analyst team.

---

## Architecture

Cortex is built as a layered system. Each layer has a clear responsibility, a defined interface, and a path from current (hardcoded/seed) to production (live feeds, scrapers, real-time).

```
                          +---------------------------+
                          |     Presentation Layer     |
                          |   FastAPI + HTML/JS UI     |
                          +-------------+-------------+
                                        |
                          +-------------v-------------+
                          |    Workflow / Pipeline     |
                          |   Orchestrates all layers  |
                          +-------------+-------------+
                                        |
              +------------+------------+------------+
              |            |            |            |
    +---------v--+ +-------v----+ +----v-------+ +--v-----------+
    | Data Layer | | Signal     | | Agent      | | Trust &      |
    | (Ingestion | | Layer      | | Layer      | | Evaluation   |
    |  + Store)  | | (News +    | | (Reasoning | | Layer        |
    |            | |  Events)   | |  + LLMs)   | | (Validation) |
    +------------+ +------------+ +------------+ +--------------+
```

---

## Layer 1: Data Layer

**Purpose:** Ingest, structure, and serve financial data for analysis.

**Current state:** Hardcoded seed dataset (JSON files) covering 3 companies (NVDA, TSLA, AMZN) across 8 quarterly earnings transcripts each. Structured with financials, key quotes, themes, risks, and management tone.

**What's in place:**
- `src/data/nvidia.json`, `tesla.json`, `amazon.json` -- structured earnings transcripts
- `src/data/index.json` -- company registry and metadata
- `src/data_loader.py` -- load, query, and serve company data

**Future (production):**
- Scrapers for SEC filings (10-K, 10-Q, 8-K, DEF 14A)
- Earnings transcript ingestion from IR pages and transcript providers
- Private data room parser (PDF extraction, table detection, entity linking)
- Entity resolution layer (map mentions to canonical companies, people, metrics)
- Structured storage (PostgreSQL + vector DB for semantic retrieval)

**Data sources roadmap:**

| Source | Type | Status |
|--------|------|--------|
| Earnings transcripts | Structured JSON | Seed data |
| SEC 10-K / 10-Q | Public filings | Planned -- SEC EDGAR scraper |
| SEC 8-K | Material events | Planned |
| Investor Relations pages | Guidance, presentations | Planned |
| Annual reports (PDF) | Unstructured | Planned -- PDF parser |
| Private data rooms | Deal documents | Planned -- secure ingestion pipeline |

---

## Layer 2: Signal Layer

**Purpose:** Capture real-time and near-real-time market signals -- news, social sentiment, supply chain data, estimate revisions -- and surface them as structured inputs for agents.

**Current state:** Static news items (4 per company) stored alongside transcript data. Headlines, sources, snippets, and tags.

**What's in place:**
- News items in each company JSON file
- `src/agents/sentiment_narrative.py` -- processes news into narratives, sentiment, and emerging risks

**Future (production):**
- Real-time news feed ingestion (RSS, news APIs, financial wire services)
- Social signal tracking (Twitter/X, Reddit, StockTwits)
- Supply chain and alternative data signals
- Estimate revision tracking (consensus EPS, revenue estimates over time)
- Material event detection and alerting
- Entity-tagged signal stream (every signal linked to a company + event type)

**Signal types roadmap:**

| Signal | Source | Status |
|--------|--------|--------|
| News headlines + snippets | Seed JSON | Seed data |
| Real-time news | News APIs / RSS | Planned |
| Social sentiment | Twitter, Reddit | Planned |
| Consensus estimate revisions | Financial data providers | Planned |
| Insider transactions | SEC Form 4 | Planned |
| Supply chain signals | Alt data vendors | Planned |

---

## Layer 3: Agent Layer

**Purpose:** The reasoning engine. Specialized LLM agents that analyze data, synthesize across sources, and produce investment-grade outputs.

**Current state:** Three production agents powered by DeepSeek (via OpenAI-compatible API), orchestrated in a sequential pipeline.

**What's in place:**

### Earnings Analyzer Agent (`src/agents/earnings_analyzer.py`)
- **Input:** Current transcript + previous transcript
- **Output:** Key themes, financial metrics, management tone, risks, what changed vs last quarter, notable quotes
- **Wow feature:** Quarter-over-quarter narrative diff -- identifies what shifted in guidance, emphasis, and tone

### Sentiment & Narrative Agent (`src/agents/sentiment_narrative.py`)
- **Input:** News items for a company
- **Output:** Top 3 narratives, overall sentiment (bullish/bearish/mixed), emerging risks, 3 things the market may be missing
- **Focus:** Themes and narrative structure, not just sentiment scores

### IC Memo Generator Agent (`src/agents/memo_generator.py`)
- **Input:** Outputs from Earnings Analyzer + Sentiment Agent
- **Output:** Full IC memo with Investment Summary, Key Drivers, What Changed, Risks (with severity/likelihood/mitigant table), Opportunities, Market May Be Missing, and Overall View (Buy/Hold/Sell with conviction and reasoning)

### Pipeline Orchestrator (`src/pipeline.py`)
- Chains: Data Loader -> Earnings Agent -> Sentiment Agent -> Memo Generator -> File Output
- Full logging at every step (timing, token counts, result sizes)

**Future (production):**
- Multi-agent collaboration (LangGraph / CrewAI)
- Cross-company comparative analysis ("How does NVDA's AI capex compare to AMZN's?")
- Hypothesis generation agent ("What if China export controls tighten?")
- Private company diligence agent (data room analysis for private deals)
- Financial estimate tracking agent (revision alerts, consensus drift)
- Custom MCP tool servers for agent-external-system integration

---

## Layer 4: Trust & Evaluation Layer

**Purpose:** Ensure outputs are decision-grade. This is what separates a demo from something a fund will actually use.

**Current state:** Not yet implemented. This is the next critical layer.

**Planned architecture:**

```
Agent Output
    |
    v
+---+---+    +---+---+
| LLM 2 |    | LLM 3 |    (Independent validation)
+---+---+    +---+---+
    |            |
    v            v
+---+------------+---+
|  Consensus Check   |
|  + Confidence Score|
+--------------------+
    |
    v
 Final Output
 (with citations + confidence)
```

**Planned capabilities:**
- **Cross-LLM validation:** Output from the primary agent (DeepSeek) is independently reviewed by 2 additional LLMs (e.g., Claude, GPT-4) to check for factual accuracy, logical consistency, and hallucination
- **Source grounding:** Every claim in the memo is traced back to a specific transcript quote, filing paragraph, or news item
- **Confidence scoring:** Each section of the memo receives a confidence score (High/Medium/Low) based on data coverage and cross-LLM agreement
- **Hallucination detection:** Flag statements that cannot be grounded in the input data
- **Evaluation benchmarks:** Manually curated "gold standard" insights for each company, compared against system output to measure coverage and accuracy

**Evaluation roadmap:**

| Capability | Status |
|------------|--------|
| Manual benchmark (3 key insights per company) | Planned |
| Cross-LLM fact checking (2 validator LLMs) | Planned |
| Source citation linking | Planned |
| Confidence scoring per section | Planned |
| Hallucination detection | Planned |
| Automated regression tests | Planned |

---

## Layer 5: Workflow & Automation Layer

**Purpose:** Remove operational friction. Not just analysis -- how the firm operates day-to-day.

**Current state:** Pipeline auto-saves memos to `output/` as markdown and supports PDF export.

**What's in place:**
- Auto-generated IC memos saved to `output/{TICKER}_memo_{timestamp}.md`
- PDF export via UI (Download PDF button)
- CLI interface for batch analysis (`python src/main.py Nvidia`)

**Future (production):**
- Scheduled analysis runs (daily pre-market briefings)
- Estimate revision alerts (push notifications when consensus moves)
- Material event alerts (8-K filings, earnings surprises, guidance changes)
- Research log maintenance (track what was analyzed, when, and what changed)
- Portfolio-level dashboard (aggregate view across all covered companies)
- Integration with communication tools (Slack, email digests)

---

## Current Project Structure

```
cortex/
|-- src/
|   |-- agents/
|   |   |-- earnings_analyzer.py    # Earnings transcript analysis agent
|   |   |-- sentiment_narrative.py  # News sentiment & narrative agent
|   |   |-- memo_generator.py       # IC memo generation agent
|   |-- data/
|   |   |-- index.json              # Company registry
|   |   |-- nvidia.json             # NVDA: 8 transcripts + 4 news
|   |   |-- tesla.json              # TSLA: 8 transcripts + 4 news
|   |   |-- amazon.json             # AMZN: 8 transcripts + 4 news
|   |-- templates/
|   |   |-- index.html              # Web UI
|   |-- app.py                      # FastAPI server + PDF export
|   |-- config.py                   # API keys, paths
|   |-- data_loader.py              # Data access layer
|   |-- llm.py                      # LLM client (DeepSeek via OpenAI SDK)
|   |-- main.py                     # CLI entry point
|   |-- pipeline.py                 # Orchestrator
|-- output/                         # Generated memos
|-- .env                            # API keys (not committed)
|-- pyproject.toml                  # Dependencies
```

---

## Getting Started

```bash
# 1. Clone and enter
cd cortex

# 2. Set your DeepSeek API key
echo "DEEPSEEK_API_KEY=your_key" > .env

# 3. Run the web UI
cd src && uv run python app.py
# Open http://localhost:8000

# 4. Or run from CLI
uv run python main.py Nvidia
```

**Requirements:** Python 3.13+, uv

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| LLM | DeepSeek (via OpenAI SDK) |
| Backend | FastAPI + Uvicorn |
| Frontend | Vanilla HTML/CSS/JS |
| PDF Export | fpdf2 |
| Package Manager | uv |
| Data | Structured JSON (seed) |

---

## Roadmap

**Phase 1 (Current):** Core agents + UI + hardcoded data
- [x] Earnings Analyzer Agent
- [x] Sentiment & Narrative Agent
- [x] IC Memo Generator Agent
- [x] Pipeline orchestrator with logging
- [x] Web UI with transcript/news/analysis views
- [x] PDF export
- [x] CLI interface

**Phase 2:** Trust & Evaluation
- [ ] Cross-LLM validation (3-LLM consensus)
- [ ] Source grounding and citations
- [ ] Confidence scoring
- [ ] Manual evaluation benchmarks

**Phase 3:** Live Data
- [ ] SEC EDGAR scraper (10-K, 10-Q, 8-K)
- [ ] Real-time news feed ingestion
- [ ] Estimate revision tracking
- [ ] Entity resolution and linking

**Phase 4:** Advanced Agents
- [ ] Cross-company comparative analysis
- [ ] Hypothesis generation
- [ ] Private company diligence
- [ ] Multi-agent collaboration (LangGraph)

**Phase 5:** Workflow Automation
- [ ] Scheduled daily briefings
- [ ] Material event alerts
- [ ] Portfolio-level dashboard
- [ ] Research log system

---

*Cortex: AI that researches, thinks, writes, and supports investing decisions end-to-end.*
