"""Integration: audit the plan of a REAL sqlite3 in-memory query.

No mocks -- SQLite itself produces the EXPLAIN QUERY PLAN, so a
SEARCH-vs-SCAN verdict here is SQLite's own verdict.
"""
import sqlite3

from plan_auditor import audit_sqlite_query, build_demo_db, explain_query


def test_real_sqlite_indexed_lookup_uses_search_not_scan():
    conn = build_demo_db()
    try:
        result = audit_sqlite_query(conn, "SELECT * FROM orders WHERE user_id = ?", (7,))
        assert result["has_seq_scan"] is False
        assert any(n.is_search for n in result["plan"].nodes)
        assert result["findings"] == []
        # And the query itself really runs and returns the right rows.
        rows = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = 7").fetchone()[0]
        assert rows > 0
    finally:
        conn.close()


def test_real_sqlite_unindexed_predicate_is_flagged_as_seq_scan():
    conn = build_demo_db()
    try:
        # `status` has no index, so SQLite must scan the whole table.
        result = audit_sqlite_query(conn, "SELECT * FROM orders WHERE status = ?", ("paid",))
        assert result["has_seq_scan"] is True
        assert any(f.rule == "SEQ_SCAN" for f in result["findings"])
        assert result["plan"].seq_scan_nodes()[0].table == "orders"
        assert result["score"] < 100
    finally:
        conn.close()


def test_real_sqlite_full_table_scan_and_explain_shape():
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)")
        conn.executemany("INSERT INTO items (label) VALUES (?)",
                         [(f"item-{i}",) for i in range(20)])
        plan = explain_query(conn, "SELECT * FROM items")
        assert plan.source_format == "sqlite"
        assert len(plan.nodes) >= 1
        assert plan.seq_scan_nodes(), "a bare SELECT on a rowid table must SCAN"
    finally:
        conn.close()


def test_demo_db_contents_are_deterministic():
    conn = build_demo_db(row_count=200)
    try:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 200
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 50
    finally:
        conn.close()
