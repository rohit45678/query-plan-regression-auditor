"""Live SQLite auditing: explain a real query and audit its plan.

Everything here uses only the ``sqlite3`` standard-library module
against a real (usually in-memory) database -- no mocks.  That is
what makes the integration tests honest: SQLite itself decides
whether a query is a ``SCAN`` or a ``SEARCH``.
"""
from __future__ import annotations

import sqlite3

from .detector import audit_single_plan
from .parser import parse_sqlite_rows
from .models import QueryPlan
from .scoring import score_plan


def explain_query(
    conn: sqlite3.Connection, sql: str, params: tuple = (), name: str = "sqlite-query"
) -> QueryPlan:
    """Run ``EXPLAIN QUERY PLAN`` for *sql* and parse the result."""
    rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
    return parse_sqlite_rows(rows, name=name, query=sql)


def audit_sqlite_query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict:
    """Explain + audit one query; return plan, findings and score."""
    plan = explain_query(conn, sql, params=params)
    findings = audit_single_plan(plan)
    return {
        "plan": plan,
        "findings": findings,
        "score": score_plan(plan),
        "has_seq_scan": bool(plan.seq_scan_nodes()),
    }


def build_demo_db(row_count: int = 200) -> sqlite3.Connection:
    """A small, deterministic in-memory demo database.

    ``orders`` has an index on ``user_id`` so a filtered lookup is a
    SEARCH, while an unfiltered / non-indexed query is a SCAN --
    exactly the contrast the auditor exists to catch.
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL
        );
        CREATE INDEX idx_orders_user ON orders(user_id);
        """
    )
    conn.executemany(
        "INSERT INTO users (id, name) VALUES (?, ?)",
        [(i, f"user-{i}") for i in range(1, 51)],
    )
    conn.executemany(
        "INSERT INTO orders (id, user_id, amount, status) VALUES (?, ?, ?, ?)",
        [
            (i, (i % 50) + 1, float(i % 97) + 0.50, "paid" if i % 3 else "pending")
            for i in range(1, row_count + 1)
        ],
    )
    conn.commit()
    return conn
