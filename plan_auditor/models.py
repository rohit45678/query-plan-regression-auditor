"""Core data models for query plans.

A plan is a flat list of :class:`PlanNode` objects (SQLite's
``EXPLAIN QUERY PLAN`` is already flat, with ``id`` / ``parent`` links,
and synthetic JSON plans are flattened into the same shape by the
parser).  Keeping one canonical shape means the detector, scorer and
reporter never have to care where a plan came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlanNode:
    """One node / row of a query plan."""

    id: int
    parent: int = 0
    operation: str = ""          # e.g. "SCAN", "SEARCH", "Seq Scan", "Index Scan"
    detail: str = ""             # raw detail text, if any
    table: str | None = None
    index: str | None = None
    cost: float = 0.0
    rows: float = 0
    # Partitioning (synthetic / Postgres-style plans)
    partitioned: bool = False
    partition_filter: bool = False
    partitions_total: int | None = None
    partitions_scanned: int | None = None
    partitions_pruned: int | None = None

    @property
    def operation_upper(self) -> str:
        return (self.operation or "").upper()

    @property
    def is_seq_scan(self) -> bool:
        """True for a full / sequential scan of a table.

        SQLite: a node whose operation is ``SCAN`` (as opposed to
        ``SEARCH``) walks the whole table or a whole index.
        Postgres-style synthetic plans spell it ``Seq Scan``.
        A ``SCAN ... USING COVERING INDEX`` is still a full scan --
        of the index -- so it counts too, just at lower severity
        (handled by the detector via :attr:`uses_index`).
        """
        op = self.operation_upper
        if op in {"SCAN", "SEQ SCAN", "SEQUENTIAL SCAN", "FULL SCAN", "TABLE SCAN"}:
            return True
        if "SEQ SCAN" in op or "FULL SCAN" in op:
            return True
        # A bare SCAN in the detail text with no SEARCH
        detail = (self.detail or "").upper()
        return op == "" and detail.startswith("SCAN ")

    @property
    def is_search(self) -> bool:
        op = self.operation_upper
        return op == "SEARCH" or "INDEX SCAN" in op or "INDEX ONLY SCAN" in op

    @property
    def uses_index(self) -> bool:
        if self.index:
            return True
        detail = (self.detail or "").upper()
        return "USING INDEX" in detail or "USING COVERING INDEX" in detail

    @property
    def missing_partition_pruning(self) -> bool:
        """True when a partitioned table is filtered but nothing is pruned.

        Pruning is *missing* when we know the table is partitioned,
        the total partition count is known, and the plan still scans
        every partition (``partitions_scanned >= partitions_total``)
        with zero partitions pruned -- despite (or regardless of) a
        partition-key filter being present.
        """
        if not self.partitioned:
            return False
        if not self.partitions_total or self.partitions_total <= 1:
            return False
        if self.partitions_pruned is not None and self.partitions_pruned > 0:
            return False
        if self.partitions_scanned is not None:
            return self.partitions_scanned >= self.partitions_total
        # No scan count recorded: fall back to an explicit pruned == 0.
        return self.partitions_pruned == 0


@dataclass
class QueryPlan:
    """A whole query plan: an ordered list of nodes plus metadata."""

    name: str = "plan"
    nodes: list[PlanNode] = field(default_factory=list)
    total_cost: float | None = None
    query: str = ""
    source_format: str = ""      # "sqlite", "json-flat", "json-tree"

    def __post_init__(self) -> None:
        if self.total_cost is None:
            self.total_cost = float(sum(n.cost for n in self.nodes))

    # -- convenience views -------------------------------------------------
    def seq_scan_nodes(self) -> list[PlanNode]:
        return [n for n in self.nodes if n.is_seq_scan]

    def search_nodes(self) -> list[PlanNode]:
        return [n for n in self.nodes if n.is_search]

    def tables(self) -> list[str]:
        seen: list[str] = []
        for n in self.nodes:
            if n.table and n.table not in seen:
                seen.append(n.table)
        return seen

    def node_for_table(self, table: str) -> PlanNode | None:
        for n in self.nodes:
            if n.table == table:
                return n
        return None

    def pruning_failures(self) -> list[PlanNode]:
        return [n for n in self.nodes if n.missing_partition_pruning]
