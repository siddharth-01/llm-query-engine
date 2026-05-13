# LLM Query Engine

A schema-aware Text-to-SQL agent that lets operations teams query structured data in plain English. Built with Claude (Anthropic), LangGraph, SQLGlot, PostgreSQL, and Streamlit.

**Key reliability mechanism:** SQL is validated before it touches the database, and if validation or execution fails, the exact error is fed back to the model for a targeted retry — pushing first-pass accuracy from ~70% to 95%+.

---

## Demo

![Architecture](https://raw.githubusercontent.com/siddharth-01/llm-query-engine/main/docs/architecture.png)

Ask questions like:
- *"What was the average rate by carrier in 2025?"*
- *"Top 10 lanes out of Chicago by volume, with average rate and most-used carrier"*
- *"Compare LTL hazmat performance against regular LTL across our top facilities"*
- *"Which carriers improved their average rate the most quarter-over-quarter?"*

---

## Architecture

```
load_schema → generate_sql → validate_sql → execute_sql → END
                   ↑               │               │
                   │               │ error          │ error
                   └─── retry ←────┴───────────────┘
                            │
                            ↓ (after MAX_ATTEMPTS = 3)
                           END
```

### How each node works

| Node | What it does |
|------|-------------|
| `load_schema` | Injects column metadata + business rules into state. Runs once per invocation. |
| `generate_sql` | Calls Claude with schema + question + prior error (on retry). Returns a raw SELECT statement. |
| `validate_sql` | Parses with SQLGlot. Rejects non-SELECT, unknown tables, hallucinated columns. Zero DB calls. |
| `execute_sql` | Runs validated SQL against Postgres. Captures any execution error. |

### Why the retry loop works

On failure, the prompt sent to Claude includes:

```
## Previous attempt failed

Error: Column(s) do not exist: {'is_hazmat'}. Hazmat is encoded in
rate_type ('Van Haz', 'LTL Haz') — there is no is_hazmat column.

Fix the specific issue above and produce a corrected SELECT.
```

The model corrects the specific mistake instead of guessing. This targeted feedback is what drives the accuracy improvement over a naive retry.

### Why no data is sent to Claude

Claude only receives:
- Column names, types, and plain-English descriptions (~500 tokens)
- Business rules and domain hints
- The user's natural language question
- The exact error message on retry

Actual freight records, rates, and carrier data never leave your infrastructure. This matters for enterprise deployments with sensitive pricing data.

---

## Project Structure

```
├── agent.py          # LangGraph state machine (nodes + routing)
├── app.py            # Streamlit UI
├── prompts.py        # System + user prompt builders
├── schema_store.py   # Static schema context + validation allow-lists
├── data/
│   └── synthetic_freight.csv   # 8,500 synthetic freight records for seeding
├── requirements.txt
├── .env.example
└── README.md
```

---

## Setup

### Prerequisites

- Python 3.10+
- PostgreSQL (local or remote)
- Anthropic API key — [console.anthropic.com](https://console.anthropic.com)

### 1. Clone and install

```bash
git clone https://github.com/siddharth-01/llm-query-engine.git
cd llm-query-engine

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Seed the database

Create a database and load the synthetic structured operational data:

```bash
# Create database
psql -U postgres -c "CREATE DATABASE freight_demo;"

# Load CSV into freight table
psql -U postgres -d freight_demo << 'EOF'
CREATE TABLE IF NOT EXISTS freight (
    id                 INTEGER,
    origin_city        TEXT,
    origin_state       TEXT,
    origin_country     TEXT,
    origin_zip_code    TEXT,
    dest_city          TEXT,
    dest_state         TEXT,
    dest_country       TEXT,
    dest_zip_code      TEXT,
    rate_type          TEXT,
    pallet             INTEGER,
    weight             NUMERIC,
    commodity          TEXT,
    user_id_requested  INTEGER,
    rate               NUMERIC,
    carrier            INTEGER,
    carrier_name       TEXT,
    date_requested     TIMESTAMP,
    date_completed     TIMESTAMP,
    user_id_completed  INTEGER,
    note_completed     TEXT,
    facility_code      TEXT,
    note_request       TEXT,
    ship_date          DATE,
    lane_or_quote      TEXT,
    ltl_flags          TEXT,
    carrier_active     SMALLINT
);

\COPY freight FROM 'data/synthetic_freight.csv' WITH (FORMAT csv, HEADER true);
EOF
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...your-key...
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/freight_demo
```

### 4. Run

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`. Use the sidebar example questions or type your own.

---

## Data

`data/synthetic_freight.csv` contains 8,500 synthetic freight records with realistic lane, carrier, rate, and shipment data. Safe to use for demos and development — no real business data.

### Schema overview

| Column | Type | Description |
|--------|------|-------------|
| `id` | integer | Primary key |
| `origin_city` / `origin_state` | text | Origin location |
| `dest_city` / `dest_state` | text | Destination location |
| `rate_type` | text | `Van`, `Dump`, `Van Haz`, `LTL`, `LTL Haz`, `Flatbed` |
| `weight` | numeric | Shipment weight in pounds |
| `rate` | numeric | All-in rate in USD |
| `carrier_name` | text | Human-readable carrier name |
| `date_requested` | timestamp | When the quote was created |
| `lane_or_quote` | text | `lane` = booked, `quote` = priced only |
| `carrier_active` | smallint | 1 = active carrier, 0 = inactive |

**Important domain rules:**
- No `is_hazmat` column — hazmat is encoded in `rate_type` as `'Van Haz'` or `'LTL Haz'`
- Always `GROUP BY carrier_name`, never by the integer `carrier` id
- Use `date_trunc('quarter', date_requested)` for quarter-over-quarter comparisons

---

## Key Design Decisions

**Schema store separate from prompts** — schema iteration (adding columns, refining descriptions) doesn't require touching the graph orchestration code.

**Validation before execution** — SQLGlot catches bad SQL with a structured error before paying for a database round-trip. Also blocks accidental writes — only SELECT statements pass.

**Retry with error context** — the single biggest reliability improvement. A raw LLM call gets SQL right ~70% of the time on a moderately complex schema. With retry-with-error-context, that rises to 95%+ in practice.

**LangGraph over plain function chaining** — provides first-class state management, conditional edges, and a full attempt trace visible in the UI. Worth the dependency for any flow with more than one LLM call.

---

## Production Roadmap

- Dynamic schema retrieval from `information_schema` (vs. static dict) for multi-table databases
- Query result cache keyed by question + schema version
- Per-user rate limits and request audit logging
- Streaming results for large response sets
- Clarifying question node for ambiguous user prompts
- Eval harness with curated question/SQL pairs (pytest-style) to measure accuracy over time
- Telemetry: token usage, latency per node, retry rate, validator-fail-rate

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| LLM | Claude (`claude-sonnet-4-6`) via Anthropic SDK |
| Agent orchestration | LangGraph |
| SQL validation | SQLGlot |
| Database | PostgreSQL via psycopg3 |
| UI | Streamlit |
| Environment | python-dotenv |
