"""The contract format: what a source's data means, written down.

A contract is the entity-relationship model a forward-deployed engineer
writes with the customer after profiling the raw data: what identifies each
row, how tables link, what each column's type is, where units live, when two
records are the same thing, and which rows count for a given purpose.

The cleaning engine (clean.py) reads a contract and applies it. It contains
no domain knowledge itself, so a new source needs a new contract, not new code.
"""

from dataclasses import dataclass, field

# Column types the engine knows how to enforce.
COLUMN_TYPES = {"str", "category", "int", "float", "date"}


@dataclass
class ForeignKey:
    """`column` in this table points to `ref_column` in `ref_table`."""

    column: str
    ref_table: str
    ref_column: str


@dataclass
class Units:
    """Quantities in `qty_column` are measured in the unit named in `uom_column`.

    `conversions` maps each unit to (canonical unit, factor), e.g.
    {"lb": ("kg", 0.45359237)} means 1 lb = 0.45359237 kg.
    """

    qty_column: str
    uom_column: str
    conversions: dict[str, tuple[str, float]]


@dataclass
class Identity:
    """Two rows are the same real-world thing when all `columns` match.

    Rows where every identity column is empty (e.g. purchased components with
    no configuration) are never merged. Among a group of duplicates, the key
    used most often in `usage_table.usage_column` becomes the master.
    """

    columns: list[str]
    usage_table: str
    usage_column: str


@dataclass
class Table:
    """Contract for one source table."""

    name: str
    primary_key: list[str]
    types: dict[str, str]
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    allowed_values: dict[str, set[str]] = field(default_factory=dict)
    units: Units | None = None
    identity: Identity | None = None
    description: str = ""


@dataclass
class Filter:
    """Keep rows where `column` is one of `keep`; the rest are excluded with `reason`."""

    column: str
    keep: set[str]
    reason: str


@dataclass
class Outliers:
    """Flag values that are far from comparable rows.

    Values are compared on a log scale (so "10x too high" and "10x too low"
    are equally far). Each row is compared with the first group in
    `group_levels` that has at least `min_group_size` rows, from most
    specific to most general. Flagged rows are kept. Rows more than
    `review_ratio` times above or below the group's typical value also go to
    the human review queue.
    """

    column: str
    group_levels: list[list[str]]
    min_group_size: int = 5
    z_threshold: float = 3.5
    review_ratio: float = 5.0


@dataclass
class Dataset:
    """A purpose-built table assembled from cleaned tables (e.g. cost history)."""

    name: str
    base_table: str
    joins: list[tuple[str, str]] = field(default_factory=list)  # (table, join column)
    filters: list[Filter] = field(default_factory=list)
    outliers: Outliers | None = None
    description: str = ""


@dataclass
class Contract:
    """Everything the engine needs to know about one source."""

    source: str
    tables: list[Table]
    datasets: list[Dataset] = field(default_factory=list)

    def table(self, name: str) -> Table:
        """Look up one table's contract by name."""
        return next(t for t in self.tables if t.name == name)

    def validate(self) -> None:
        """Catch mistakes in the contract itself before running anything."""
        names = {t.name for t in self.tables}
        for t in self.tables:
            bad = {c: k for c, k in t.types.items() if k not in COLUMN_TYPES}
            if bad:
                raise ValueError(f"{t.name}: unknown column types {bad}")
            for fk in t.foreign_keys:
                if fk.ref_table not in names:
                    raise ValueError(f"{t.name}.{fk.column} points to unknown table {fk.ref_table}")
        for d in self.datasets:
            if d.base_table not in names:
                raise ValueError(f"dataset {d.name}: unknown base table {d.base_table}")
