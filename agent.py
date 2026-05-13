"""LangGraph agent: schema-aware Text-to-SQL with validation gate and retry loop.

Flow:

    load_schema --> generate_sql --> validate_sql --> execute_sql --> END
                          ^                |                |
                          |                | (error)        | (error)
                          |                v                v
                          +------------ retry? ------------+
                                          |
                                          v (max attempts)
                                         END
"""
from __future__ import annotations

import os
import re
from operator import add
from typing import Annotated, TypedDict

import sqlglot
from sqlglot import exp
from langgraph.graph import StateGraph, END
from anthropic import Anthropic

from schema_store import (
    format_schema_for_prompt,
    ALLOWED_TABLES,
    ALLOWED_COLUMNS,
)
from prompts import SYSTEM_PROMPT, build_user_prompt


MAX_ATTEMPTS = 3
MODEL = "claude-sonnet-4-6"

# Columns the LLM commonly hallucinates against this schema. If we see one of
# these, fail validation fast with a helpful error so the retry has good signal.
KNOWN_HALLUCINATIONS = {
    "is_hazmat", "hazmat", "is_haz",
    "is_active", "active",
    "is_completed", "completed",
    "is_booked", "booked",
    "origin", "destination",   # the actual columns are origin_city / dest_city etc.
}


class AgentState(TypedDict, total=False):
    question: str
    schema_text: str
    sql: str
    validation_error: str
    execution_error: str
    results: list[dict]
    columns: list[str]
    attempts_made: int
    attempts: Annotated[list[dict], add]   # accumulating trace


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def load_schema_node(state: AgentState) -> AgentState:
    """Inject schema context. In production this would also retrieve few-shot
    examples or query templates — kept static for the demo."""
    return {
        "schema_text": format_schema_for_prompt(),
        "attempts_made": 0,
    }


def _strip_fences(s: str) -> str:
    """Strip markdown code fences if the model decides to add them anyway."""
    s = s.strip()
    s = re.sub(r"^```(?:sql)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s)
    # Some models prepend a label like "SQL:" — strip a leading label line.
    s = re.sub(r"^\s*sql:\s*", "", s, flags=re.IGNORECASE)
    return s.strip()


def generate_sql_node(state: AgentState) -> AgentState:
    """Call the LLM. If a prior validation/execution error exists, pass it in
    as feedback so the model can correct itself."""
    client = Anthropic()
    prior_error = state.get("validation_error") or state.get("execution_error") or None

    user_prompt = build_user_prompt(
        question=state["question"],
        schema=state["schema_text"],
        prior_error=prior_error,
    )

    msg = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    sql = _strip_fences(msg.content[0].text)

    attempt = {
        "n": state.get("attempts_made", 0) + 1,
        "sql": sql,
        "prior_error": prior_error,
    }

    return {
        "sql": sql,
        "attempts": [attempt],
        "attempts_made": state.get("attempts_made", 0) + 1,
        # Clear errors so downstream nodes set them fresh
        "validation_error": "",
        "execution_error": "",
    }


def validate_sql_node(state: AgentState) -> AgentState:
    """Cheap static checks before we touch the database:
      1. Parses as valid SQL (sqlglot)
      2. Is a SELECT (no writes / DDL)
      3. References only the allowed table
      4. Doesn't reference well-known hallucinated columns
    """
    sql = state["sql"]
    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
    except Exception as e:
        return {"validation_error": f"SQL parse failed: {e}"}

    if not isinstance(parsed, exp.Select):
        return {"validation_error": "Only SELECT statements are allowed."}

    tables = {t.name.lower() for t in parsed.find_all(exp.Table)}
    unknown = tables - ALLOWED_TABLES
    if unknown:
        return {"validation_error": f"Unknown table(s): {sorted(unknown)}. Only {sorted(ALLOWED_TABLES)} exist."}

    referenced_cols = {c.name.lower() for c in parsed.find_all(exp.Column) if c.name}
    hallucinated = referenced_cols & KNOWN_HALLUCINATIONS
    if hallucinated:
        return {"validation_error": (
            f"Column(s) do not exist: {sorted(hallucinated)}. "
            "Hazmat is encoded in rate_type ('Van Haz', 'LTL Haz'); "
            "booking status is in lane_or_quote; "
            "origin/destination cities are origin_city / dest_city."
        )}

    return {"validation_error": ""}


def execute_sql_node(state: AgentState) -> AgentState:
    """Run the validated SQL against Postgres."""
    import psycopg
    db_url = os.environ["DATABASE_URL"]
    try:
        with psycopg.connect(db_url) as conn, conn.cursor() as cur:
            cur.execute(state["sql"])
            rows = cur.fetchall()
            cols = [d.name for d in cur.description] if cur.description else []
        return {
            "results": [dict(zip(cols, r)) for r in rows],
            "columns": cols,
            "execution_error": "",
        }
    except Exception as e:
        return {"execution_error": f"Database error: {e}"}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_after_validate(state: AgentState) -> str:
    if not state.get("validation_error"):
        return "execute"
    if state.get("attempts_made", 0) >= MAX_ATTEMPTS:
        return "give_up"
    return "retry"


def route_after_execute(state: AgentState) -> str:
    if not state.get("execution_error"):
        return "done"
    if state.get("attempts_made", 0) >= MAX_ATTEMPTS:
        return "give_up"
    return "retry"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def build_agent():
    g = StateGraph(AgentState)
    g.add_node("load_schema",  load_schema_node)
    g.add_node("generate_sql", generate_sql_node)
    g.add_node("validate_sql", validate_sql_node)
    g.add_node("execute_sql",  execute_sql_node)

    g.set_entry_point("load_schema")
    g.add_edge("load_schema", "generate_sql")
    g.add_edge("generate_sql", "validate_sql")

    g.add_conditional_edges(
        "validate_sql",
        route_after_validate,
        {"execute": "execute_sql", "retry": "generate_sql", "give_up": END},
    )
    g.add_conditional_edges(
        "execute_sql",
        route_after_execute,
        {"done": END, "retry": "generate_sql", "give_up": END},
    )

    return g.compile()
