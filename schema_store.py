"""Schema store.

Hand-curated column descriptions and value hints for the freight table.
This is what makes the agent 'schema-aware' — instead of letting the LLM
guess what columns mean, we inject this context into every prompt.

In production this would be loaded from a metadata DB or pulled live from
information_schema. For the demo it's static.
"""

FREIGHT_SCHEMA = {
    "table": "freight",
    "description": (
        "Historical freight quotes and booked lanes. "
        "Each row is either a price quote or a booked shipment."
    ),
    "columns": [
        ("id",                "integer",   "Primary key."),
        ("origin_city",       "text",      "Origin city, e.g. 'Chicago'."),
        ("origin_state",      "text",      "Origin state, 2-letter US code, e.g. 'IL'."),
        ("origin_country",    "text",      "Origin country code, usually 'US' or NULL."),
        ("origin_zip_code",   "text",      "Origin ZIP; often NULL."),
        ("dest_city",         "text",      "Destination city."),
        ("dest_state",        "text",      "Destination state, 2-letter US code."),
        ("dest_country",      "text",      "Destination country code, usually 'US' or NULL."),
        ("dest_zip_code",     "text",      "Destination ZIP; often NULL."),
        ("rate_type",         "text",      "Equipment / service type. One of: "
                                           "'Van', 'Dump', 'Van Haz', 'LTL', 'LTL Haz', 'Flatbed'. "
                                           "The 'Haz' suffix marks hazardous-material shipments."),
        ("pallet",            "integer",   "Pallet count; usually NULL."),
        ("weight",            "numeric",   "Shipment weight in pounds."),
        ("commodity",         "text",      "Commodity description, e.g. 'Mixed Load'."),
        ("user_id_requested", "integer",   "User who created the request."),
        ("rate",              "numeric",   "All-in rate in USD."),
        ("carrier",           "integer",   "Carrier id (foreign-key style)."),
        ("carrier_name",      "text",      "Human-readable carrier name. Prefer this for grouping."),
        ("date_requested",    "timestamp", "When the quote/lane was requested."),
        ("date_completed",    "timestamp", "When the quote was booked. NULL if not yet booked."),
        ("user_id_completed", "integer",   "User who closed the quote."),
        ("facility_code",     "text",      "Internal facility code, e.g. 'IL-MAIN', 'TX-DAL'."),
        ("ship_date",         "date",      "Actual ship date."),
        ("lane_or_quote",     "text",      "Either 'lane' (booked shipment) or 'quote' (priced only). "
                                           "Filter on this to distinguish booked freight from open quotes."),
        ("carrier_active",    "smallint",  "1 if carrier is currently active, 0 otherwise."),
    ],
    "hints": [
        "When the user says 'lanes' filter lane_or_quote = 'lane'.",
        "When the user says 'quotes' filter lane_or_quote = 'quote'.",
        "There is NO is_hazmat or hazmat column. For hazmat filter rate_type IN ('Van Haz', 'LTL Haz').",
        "For 'LTL hazmat vs regular LTL' use rate_type IN ('LTL', 'LTL Haz') and GROUP BY rate_type.",
        "Always GROUP BY carrier_name when asked about carriers, never the integer carrier id.",
        "All rates are in USD; do not apply currency conversion.",
        "For quarter-over-quarter comparisons use date_trunc('quarter', date_requested).",
    ],
}


def format_schema_for_prompt() -> str:
    """Render the schema dict into a compact prompt-ready string."""
    s = FREIGHT_SCHEMA
    out = [f"Table: {s['table']}", s["description"], "", "Columns:"]
    for name, type_, desc in s["columns"]:
        out.append(f"  - {name} ({type_}): {desc}")
    out.append("")
    out.append("Important rules:")
    for h in s["hints"]:
        out.append(f"  - {h}")
    return "\n".join(out)


# Allow-list used by the validator
ALLOWED_TABLES = {"freight"}
ALLOWED_COLUMNS = {c[0] for c in FREIGHT_SCHEMA["columns"]}
