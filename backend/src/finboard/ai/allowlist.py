"""The allow-lists shared by the SQL guard and the sandbox's authorizer (ADR-0032 §2).
Plain data, so the sandbox doesn't need sqlglot."""

TABLES = frozenset({"ai_txn", "ai_budget"})

# Postgres-dialect function names (sqlglot's sql_name, upper case) the model may use.
ALLOWED_FUNCTIONS = frozenset(
    {
        # aggregates
        "COUNT", "SUM", "AVG", "MIN", "MAX", "GROUP_CONCAT", "STRING_AGG",
        # scalar
        "ABS", "ROUND", "COALESCE", "NULLIF", "LOWER", "UPPER", "LENGTH", "TRIM",
        "SUBSTRING", "CASE", "IF", "CAST", "TRY_CAST", "CONCAT", "GREATEST", "LEAST",
        # dates (the guard rewrites some of these for SQLite)
        "DATE_TRUNC", "TIMESTAMP_TRUNC", "EXTRACT", "TO_CHAR", "TIME_TO_STR", "STR_TO_TIME",
        "DATE", "CURRENT_DATE",
        # windows
        "ROW_NUMBER", "RANK", "DENSE_RANK", "LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE",
    }
)  # fmt: skip
# The same allow-list as SQLite sees it after transpiling (the sandbox's authorizer).
SQLITE_FUNCTIONS = frozenset(
    {
        "count", "sum", "total", "avg", "min", "max", "group_concat",
        "abs", "round", "coalesce", "ifnull", "nullif", "lower", "upper", "length", "trim",
        "substr", "substring", "iif", "like", "strftime", "date",
        "row_number", "rank", "dense_rank", "lag", "lead", "first_value", "last_value",
        "concat",
    }
)  # fmt: skip
