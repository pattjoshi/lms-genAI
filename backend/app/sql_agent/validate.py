"""Check LLM-written SQL before it reaches the database (Phase 6).

This is a fast, explainable first filter, not the security boundary: the read-only user and row-level
security (access.py) hold even if something gets past it. What it does:

- parses the SQL with sqlglot (Postgres dialect) instead of using regexes: `SELECT 'drop table'` is a
  string, `DELETE` inside a CTE is a write, and only a parser can tell them apart;
- exactly one statement, and it must be a query (SELECT, WITH ... SELECT, UNION ...);
- nothing that writes or locks anywhere in the tree (`WITH x AS (DELETE ...)`, `SELECT ... INTO`, `FOR UPDATE`);
- only the agent's tables (CTE names are fine), so no `pg_catalog`, `information_schema` or app tables;
- no functions that reach outside the query: `pg_*` (pg_sleep, pg_read_file...), `set_config`,
  `dblink`, `query_to_xml` (runs a SQL string), large objects...

An error message here goes back to the model, which writes a corrected query (the self-correction loop),
so it says what to change.
"""

import logging
import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.sql_agent.access import TABLE_NAMES

logging.getLogger("sqlglot").setLevel(logging.ERROR)  # "falling back to parsing as a Command": we refuse those

WRITE_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Copy,
    exp.Into,
    exp.Command,  # anything sqlglot only knows as a raw command: SET, GRANT, VACUUM, CALL...
    exp.Set,
    exp.Grant,
    exp.Lock,  # FOR UPDATE / FOR SHARE
)

BLOCKED_FUNCTIONS = {
    "set_config",
    "current_setting",
    "dblink",
    "dblink_exec",
    "query_to_xml",
    "query_to_xml_and_xmlschema",
    "cursor_to_xml",
    "table_to_xml",
    "schema_to_xml",
    "database_to_xml",
    "txid_current",
    "lo_import",
    "lo_export",
    "lo_get",
    "lo_open",
}
BLOCKED_PREFIXES = ("pg_", "lo_", "dblink")
# Our own row-level security helpers: calling them tells nothing useful and invites probing.
BLOCKED_PREFIXES += ("lms_",)


class UnsafeSql(Exception):
    """kind: 'write' (asks to change data: refused, not retried) or 'invalid' (the model may fix it)."""

    def __init__(self, message: str, kind: str = "invalid"):
        super().__init__(message)
        self.message = message
        self.kind = kind


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def clean(sql: str) -> str:
    """Strip markdown fences and trailing semicolons the model sometimes adds."""
    sql = sql.strip()
    sql = re.sub(r"^```(?:sql)?\s*|\s*```$", "", sql, flags=re.IGNORECASE).strip()
    return sql.rstrip(";").strip()


def check_sql(sql: str, allowed_tables: frozenset[str] = TABLE_NAMES) -> str:
    """Return the cleaned SQL, or raise UnsafeSql saying what is wrong."""
    sql = clean(sql)
    if not sql:
        raise UnsafeSql("The query is empty.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as exc:
        first = exc.errors[0]["description"] if exc.errors else str(exc)
        raise UnsafeSql(f"The SQL could not be parsed: {first}") from None
    if len(statements) != 1:
        raise UnsafeSql("Write exactly one SQL statement (no ';' between statements).", kind="write")
    tree = statements[0]

    for node in tree.walk():
        if isinstance(node, WRITE_NODES):
            raise UnsafeSql(
                f"Only read-only SELECT queries are allowed (found {type(node).__name__.upper()}).", kind="write"
            )
    if not isinstance(tree, exp.Query):
        raise UnsafeSql("Only SELECT queries are allowed.", kind="write")

    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        schema = (table.db or "").lower()
        if not name:  # e.g. a table function, such as generate_series(...) in FROM
            continue
        if table.catalog or schema not in ("", "public"):
            raise UnsafeSql(f"Table {table.sql()} is not available. Use only the tables listed in the schema.")
        if name not in allowed_tables and not (not schema and name in ctes):
            raise UnsafeSql(f"Table {name} is not available. Use only the tables listed in the schema.")

    for func in tree.find_all(exp.Func):
        name = _function_name(func)
        if name in BLOCKED_FUNCTIONS or name.startswith(BLOCKED_PREFIXES):
            raise UnsafeSql(f"The function {name}() is not allowed. Use plain SQL over the listed tables.")
    return sql
