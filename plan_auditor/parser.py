"""Plan parsing: SQLite ``EXPLAIN QUERY PLAN`` rows and JSON plan trees.

Supported inputs
----------------
1. SQLite rows -- the 4-tuples ``(id, parent, notused, detail)``
   returned by ``EXPLAIN QUERY PLAN <query>``, e.g.::

       (4, 0, 0, 'SEARCH orders USING INDEX idx_orders_user (user_id=?)')
       (9, 0, 0, 'SCAN users')

2. Flat JSON -- ``{"name": ..., "total_cost": ..., "nodes": [...]}``
   where each node may use ``operation``/``op``/``type``,
   ``table``/``relation``, ``cost``/``estimated_cost`` and
   ``rows``/``estimated_rows``, plus the partitioning fields
   described in :class:`plan_auditor.models.PlanNode`.

3. Nested JSON trees -- a node dict with a ``children`` list; the
   tree is flattened depth-first and ``id``/``parent`` links are
   synthesised, so it lands in exactly the same shape as (1) and (2).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

from .models import PlanNode, QueryPlan

_INDEX_RE = re.compile(r"USING (?:COVERING )?INDEX\s+(\S+)", re.IGNORECASE)
_TABLE_RE = re.compile(
    r"^(?:SCAN|SEARCH|Seq Scan|Index Scan|Index Only Scan)\s+(?:ON\s+)?(\S+)",
    re.IGNORECASE,
)


def _parse_detail(detail: str) -> tuple[str, str | None, str | None]:
    """Split a SQLite detail string into (operation, table, index)."""
    detail = (detail or "").strip()
    if not detail:
        return "", None, None
    operation = detail.split()[0].upper()
    table_match = _TABLE_RE.match(detail)
    table = table_match.group(1) if table_match else None
    index_match = _INDEX_RE.search(detail)
    index = index_match.group(1) if index_match else None
    return operation, table, index


def parse_sqlite_rows(
    rows: Iterable[Sequence[Any]],
    name: str = "sqlite-plan",
    query: str = "",
) -> QueryPlan:
    """Build a :class:`QueryPlan` from ``EXPLAIN QUERY PLAN`` rows."""
    nodes: list[PlanNode] = []
    for row in rows:
        if len(row) < 4:
            raise ValueError(f"EXPLAIN QUERY PLAN row needs 4 columns, got {row!r}")
        node_id, parent, _notused, detail = int(row[0]), int(row[1]), row[2], str(row[3])
        operation, table, index = _parse_detail(detail)
        nodes.append(
            PlanNode(
                id=node_id,
                parent=parent,
                operation=operation,
                detail=detail,
                table=table,
                index=index,
            )
        )
    if not nodes:
        raise ValueError("no plan rows supplied")
    return QueryPlan(name=name, nodes=nodes, query=query, source_format="sqlite")


def _node_from_dict(raw: dict[str, Any], node_id: int, parent: int) -> PlanNode:
    operation = str(
        raw.get("operation") or raw.get("op") or raw.get("type") or raw.get("detail") or ""
    )
    detail = str(raw.get("detail") or operation)
    # If only a detail string was given (SQLite style), split it out.
    if raw.get("table") is None and detail:
        op2, table2, index2 = _parse_detail(detail)
        if table2:
            operation = operation if raw.get("operation") else op2
            raw = {**raw, "table": table2}
            if raw.get("index") is None and index2:
                raw = {**raw, "index": index2}
    return PlanNode(
        id=int(raw.get("id", node_id)),
        parent=int(raw.get("parent", parent)),
        operation=operation,
        detail=detail,
        table=raw.get("table") or raw.get("relation"),
        index=raw.get("index"),
        cost=float(raw.get("cost", raw.get("estimated_cost", 0.0)) or 0.0),
        rows=float(raw.get("rows", raw.get("estimated_rows", 0)) or 0),
        partitioned=bool(raw.get("partitioned", False)),
        partition_filter=bool(
            raw.get("partition_filter", raw.get("has_partition_filter", False))
        ),
        partitions_total=raw.get("partitions_total"),
        partitions_scanned=raw.get("partitions_scanned"),
        partitions_pruned=raw.get("partitions_pruned"),
    )


def _flatten_tree(raw: dict[str, Any], nodes: list[PlanNode], parent: int, counter: list[int]) -> None:
    counter[0] += 1
    my_id = counter[0]
    node = _node_from_dict(raw, node_id=my_id, parent=parent)
    node.id = my_id
    node.parent = parent
    nodes.append(node)
    for child in raw.get("children", []) or []:
        _flatten_tree(child, nodes, parent=my_id, counter=counter)


def parse_json_plan(data: Any, name: str | None = None) -> QueryPlan:
    """Build a :class:`QueryPlan` from parsed JSON (dict or list)."""
    if isinstance(data, list):
        data = {"nodes": data}
    if not isinstance(data, dict):
        raise ValueError(f"plan JSON must be an object or list, got {type(data).__name__}")

    plan_name = name or data.get("name") or "json-plan"
    query = data.get("query", "") or ""

    if "nodes" in data and data["nodes"]:
        nodes = [
            _node_from_dict(raw, node_id=i + 1, parent=int(raw.get("parent", 0)))
            for i, raw in enumerate(data["nodes"])
        ]
        source_format = "json-flat"
    elif "children" in data or "operation" in data or "type" in data:
        nodes = []
        _flatten_tree(data, nodes, parent=0, counter=[0])
        source_format = "json-tree"
    else:
        raise ValueError("plan JSON has neither 'nodes' nor a root node")

    total_cost = data.get("total_cost", data.get("cost"))
    return QueryPlan(
        name=plan_name,
        nodes=nodes,
        total_cost=float(total_cost) if total_cost is not None else None,
        query=query,
        source_format=source_format,
    )


def parse_plan_text(text: str, name: str | None = None) -> QueryPlan:
    """Parse a JSON string into a :class:`QueryPlan`."""
    return parse_json_plan(json.loads(text), name=name)


def load_plan_file(path: str | Path) -> QueryPlan:
    """Load a plan from a ``.json`` file on disk."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return parse_json_plan(data, name=data.get("name") if isinstance(data, dict) else None)
