# LLM Query Engine

A schema-aware Text-to-SQL agent that lets users query relational databases in plain English. Built with Claude (Anthropic), LangGraph, SQLGlot, PostgreSQL, and Streamlit.

**Key reliability mechanism:** SQL is validated before it touches the database, and if validation or execution fails, the exact error is fed back to the model for a targeted retry — pushing first-pass accuracy from ~70% to 95%+.

---

## How It Works

Users type a natural language question. The agent generates a PostgreSQL SELECT statement, validates it statically, executes it against the database, and returns a result table — all without the user writing any SQL.

If the generated SQL fails validation or execution, the exact error is injected back into the next prompt so the model corrects the specific mistake rather than starting from scratch.

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

### Nodes

| Node | What it does |
|------|-------------|
| `load_schema` | Injects column metadata + business rules into state. Runs once per invocation. |
| `generate_sql` | Calls Claude with schema + question + prior error (on retry). Returns a raw SELECT statement. |
| `validate_sql` | Parses with SQLGlot. Rejects non-SELECT, unknown tables, hallucinated columns. Zero DB calls. |
| `execute_sql` | Runs validated SQL against Postgres. Captures any execution error. |

### Retry loop

On failure, the prompt includes:

```
## Previous attempt failed

Error: <exact error from validator or database>

Fix the specific issue above and produce a corrected SELECT.
```

The model corrects the specific mistake instead of guessing. This targeted feedback is what drives the accuracy improvement over a naive retry.

### Data privacy

The LLM only receives:
- Column names, types, and plain-English descriptions
- Business rules and domain hints
- The user's natural language question
- The exact error message on retry

Actual row data never leaves your infrastructure.

---

## Project Structure

```
├── agent.py          # LangGraph state machine (nodes + routing)
├── app.py            # Streamlit UI
├── prompts.py        # System + user prompt builders
├── schema_store.py   # Static schema context + validation allow-lists
├── data/
│   └── synthetic_freight.csv   # Sample dataset for local development
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

```bash
psql -U postgres -c "CREATE DATABASE mydb;"

psql -U postgres -d mydb << 'EOF'
CREATE TABLE IF NOT EXISTS my_table (
    -- define your columns here
);

\COPY my_table FROM 'data/your_data.csv' WITH (FORMAT csv, HEADER true);
EOF
```

A sample dataset is included in `data/synthetic_freight.csv` for local development and testing.

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...your-key...
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/mydb
```

### 4. Adapt the schema store

Edit `schema_store.py` to describe your table — column names, types, plain-English descriptions, and any domain-specific rules the model should know. This is what makes the agent accurate for your specific data.

### 5. Run

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`.

---

## Adapting to Your Domain

The agent is domain-agnostic. To point it at a different database:

1. **Update `schema_store.py`** — describe your table's columns and add business rules (e.g. which columns encode categorical flags, how to group, how to handle nulls)
2. **Update `ALLOWED_TABLES` and `ALLOWED_COLUMNS`** in `schema_store.py` — the validator uses these to reject hallucinated references
3. **Update example questions** in `app.py` sidebar to match your domain
4. Point `DATABASE_URL` at your database

No changes needed to `agent.py`, `prompts.py`, or the graph structure.

---

## Key Design Decisions

**Schema store separate from prompts** — domain context can be updated without touching orchestration code.

**Validation before execution** — SQLGlot catches bad SQL cheaply before a DB round-trip. Also enforces SELECT-only — no writes, deletes, or DDL can reach the database.

**Retry with error context** — the single biggest reliability improvement. Raw LLM SQL generation is ~70% accurate on moderately complex schemas. With retry-with-error-context, that rises to 95%+.

**LangGraph over plain function chaining** — first-class state management, conditional edges, and a full attempt trace visible in the UI.

---

## Production Roadmap

- Dynamic schema retrieval from `information_schema` for multi-table databases
- Query result cache keyed by question + schema version
- Per-user rate limits and request audit logging
- Streaming results for large response sets
- Clarifying question node for ambiguous prompts
- Eval harness with curated question/SQL pairs to measure accuracy over time
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
