"""Streamlit demo UI for the Lane Procurement Agent.

Run:
    streamlit run app.py
"""

import os
import time

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Import after .env loads, in case the agent reads env at import time.
from agent import build_agent

st.set_page_config(page_title="Lane Procurement Agent", layout="wide")
st.markdown("# Lane Procurement Agent")
st.caption("Schema-aware Text-to-SQL · validation gate · retry-with-error-context")


@st.cache_resource
def _compiled_agent():
    return build_agent()


agent = _compiled_agent()

EXAMPLES = [
    "What was the average rate by carrier in 2025?",
    "Top 10 lanes out of Chicago by volume in 2025, with average rate and most-used carrier.",
    "Which carriers improved their average rate the most quarter-over-quarter this year?",
    "Compare LTL hazmat performance against regular LTL across our top facilities.",
]

# Sidebar — example prompts (clickable)
with st.sidebar:
    st.markdown("### Example questions")
    for ex in EXAMPLES:
        if st.button(ex, key=f"ex::{ex}", use_container_width=True):
            st.session_state["question"] = ex
    st.markdown("---")
    st.caption("Model: `claude-sonnet-4-6` · Validator: SQLGlot · Max attempts: 3")


question = st.text_area(
    "Ask a question about the freight data:",
    value=st.session_state.get("question", ""),
    height=80,
    key="question_input",
)
run = st.button("Run", type="primary", disabled=not question.strip())

if run and question.strip():
    t0 = time.time()
    with st.status("Running agent…", expanded=True) as status:
        st.write("→ loading schema context")
        st.write("→ generating SQL")
        result = agent.invoke({"question": question})
        elapsed = time.time() - t0
        n = len(result.get("attempts", []))
        label = f"Done in {elapsed:.1f}s · {n} attempt{'s' if n != 1 else ''}"
        status.update(label=label, state="complete")

    # Attempts trace
    st.subheader("Attempts")
    attempts = result.get("attempts", [])
    for att in attempts:
        is_retry = att.get("prior_error") is not None
        header = f"Attempt {att['n']}" + (" · retry (after error)" if is_retry else "")
        with st.expander(header, expanded=(att == attempts[-1])):
            if is_retry:
                st.error(f"Previous attempt failed: {att['prior_error']}")
            st.code(att["sql"], language="sql")

    # Final outcome
    if result.get("validation_error"):
        st.error(
            f"Gave up after {len(attempts)} attempts. Last validation error: "
            f"{result['validation_error']}"
        )
    elif result.get("execution_error"):
        st.error(
            f"Gave up after {len(attempts)} attempts. Last execution error: "
            f"{result['execution_error']}"
        )
    else:
        rows = result.get("results") or []
        cols = result.get("columns") or []
        st.subheader(f"Results · {len(rows)} row{'s' if len(rows) != 1 else ''}")
        if rows:
            st.dataframe(pd.DataFrame(rows, columns=cols), use_container_width=True)
        else:
            st.info("Query returned no rows.")
