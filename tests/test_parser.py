"""Plan parsing: SQLite rows, flat JSON, nested JSON trees, sample files."""
import json
from pathlib import Path

import pytest

from plan_auditor import load_plan_file, parse_json_plan, parse_plan_text, parse_sqlite_rows

ROOT = Path(__file__).resolve().parents[1]


def test_parse_sqlite_rows_scan_and_search():
    rows = [
        (2, 0, 0, "SEARCH orders USING INDEX idx_orders_user (user_id=?)"),
        (5, 0, 0, "SCAN users"),
    ]
    plan = parse_sqlite_rows(rows, name="t", query="SELECT ...")
    assert plan.source_format == "sqlite"
    assert plan.nodes[0].is_search and plan.nodes[0].table == "orders"
    assert plan.nodes[0].index == "idx_orders_user"
    assert plan.nodes[1].is_seq_scan and plan.nodes[1].table == "users"
    assert plan.tables() == ["orders", "users"]


def test_parse_sqlite_rows_rejects_short_rows_and_empty():
    with pytest.raises(ValueError):
        parse_sqlite_rows([(1, 0, "SCAN users")])
    with pytest.raises(ValueError):
        parse_sqlite_rows([])


def test_parse_flat_json_with_alias_fields():
    plan = parse_json_plan({
        "name": "alias-plan",
        "total_cost": 42.5,
        "nodes": [
            {"operation": "Seq Scan", "relation": "events",
             "estimated_cost": 40, "estimated_rows": 9000},
            {"op": "SORT", "cost": 2.5, "rows": 10},
        ],
    })
    assert plan.name == "alias-plan"
    assert plan.total_cost == 42.5
    assert plan.nodes[0].table == "events"
    assert plan.nodes[0].cost == 40 and plan.nodes[0].rows == 9000
    assert plan.source_format == "json-flat"


def test_parse_flat_json_total_cost_falls_back_to_node_sum():
    plan = parse_json_plan({"nodes": [{"operation": "SORT", "cost": 3},
                                      {"operation": "SORT", "cost": 4}]})
    assert plan.total_cost == 7.0


def test_parse_nested_json_tree_is_flattened_with_parent_links():
    tree = {
        "operation": "SORT", "cost": 5,
        "children": [
            {"operation": "Seq Scan", "table": "orders", "cost": 100,
             "children": [{"operation": "Filter", "cost": 1}]},
        ],
    }
    plan = parse_json_plan(tree, name="tree")
    assert plan.source_format == "json-tree"
    assert len(plan.nodes) == 3
    assert plan.nodes[1].parent == plan.nodes[0].id
    assert plan.nodes[2].parent == plan.nodes[1].id
    assert plan.seq_scan_nodes()[0].table == "orders"


def test_parse_plan_text_round_trip():
    text = json.dumps({"name": "txt", "nodes": [{"operation": "SCAN", "table": "t", "detail": "SCAN t"}]})
    plan = parse_plan_text(text)
    assert plan.name == "txt" and plan.nodes[0].is_seq_scan


def test_load_bundled_sample_files():
    baseline = load_plan_file(ROOT / "sample_data" / "baseline.json")
    candidate = load_plan_file(ROOT / "sample_data" / "candidate.json")
    assert baseline.total_cost == 142.0
    assert candidate.total_cost == 1840.0
    assert baseline.seq_scan_nodes() == []
    assert len(candidate.seq_scan_nodes()) == 2
