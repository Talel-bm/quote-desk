"""Build the synthetic ERP database for Lakeshore Electric (fictional).

`build_erp()` returns every table as a pandas DataFrame; `generate()` writes
them to data/generated/erp.sqlite. Same seed -> same database.
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

from quote_desk import config
from quote_desk.generate import commodity
from quote_desk.generate import cost_model as cm

HISTORY_START = pd.Timestamp("2023-11-01")
HISTORY_END = pd.Timestamp("2026-10-31")
TODAY = pd.Timestamp("2026-11-20")

# --- Product options ---------------------------------------------------------
KVA_3PH = [15, 30, 45, 75, 112.5, 150, 225, 300, 500, 750, 1000]
KVA_1PH = [15, 25, 37.5, 50, 75, 100]
SECONDARY_BY_PRIMARY = {
    480: ["208/120"],
    600: ["208/120", "480/277"],
    4160: ["208/120", "480/277", "600/347"],
}
ENCLOSURE_SIZES = [
    "16x12x6", "20x16x8", "24x20x8", "30x24x10",
    "36x30x12", "48x36x12", "60x36x16", "72x36x18",
]  # fmt: skip
TRANSFORMER_FIELDS = [
    "kva", "primary_v", "secondary_v", "phase", "winding", "k_factor", "enclosure", "efficiency",
]  # fmt: skip
ENCLOSURE_FIELDS = ["size", "gauge", "finish", "nema_rating"]

# --- Customers ----------------------------------------------------------------
SEGMENTS = ["contractor", "distributor", "OEM", "utility"]
SEGMENT_SHARE = [0.35, 0.25, 0.25, 0.15]
SEGMENT_MARGIN = {"contractor": 0.28, "distributor": 0.18, "OEM": 0.22, "utility": 0.20}
SEGMENT_TRANSFORMER_SHARE = {"contractor": 0.7, "distributor": 0.6, "OEM": 0.3, "utility": 0.95}

ROUTINE_NOTES = [
    "rush - customer needs by month end",
    "cust supplied drawing rev B",
    "match previous order",
    "partial shipment ok",
    "per phone call w/ buyer",
    "credit hold released",
    "label per customer spec",
]


# --- Helpers ------------------------------------------------------------------
def iso(date) -> str:
    """Format a date as 'YYYY-MM-DD' for storage in SQLite."""
    return pd.Timestamp(date).strftime("%Y-%m-%d")


def popularity(n: int, rng: np.random.Generator) -> np.ndarray:
    """Random 'Zipf-like' weights: a few items are ordered a lot, most rarely."""
    weights = 1.0 / np.arange(1, n + 1) ** 1.1
    rng.shuffle(weights)
    return weights / weights.sum()


# --- Customers ----------------------------------------------------------------
def make_customers(rng: np.random.Generator, fake: Faker, n: int = 60) -> pd.DataFrame:
    """Fictional customers with a segment, region, email domain and order volume."""
    rows = []
    for i in range(n):
        name = fake.unique.company()
        words = ["".join(ch for ch in w if ch.isalnum()) for w in name.lower().split()]
        domain = "".join(words[:2]) + ".com"  # "Garza Inc" -> garzainc.com
        first, last = fake.first_name(), fake.last_name()
        contact = f"{first} {last}"
        segment = rng.choice(SEGMENTS, p=SEGMENT_SHARE)
        country = rng.choice(["US", "CA"], p=[0.7, 0.3])
        region = fake.state_abbr() if country == "US" else rng.choice(["ON", "QC", "AB", "BC"])
        rows.append(
            {
                "customer_id": f"C{1001 + i}",
                "name": name,
                "segment": str(segment),
                "country": str(country),
                "region": str(region),
                "email_domain": domain,
                "contact_name": contact,
                "contact_email": f"{first.lower()}.{last.lower()}@{domain}",
                "payment_terms": str(rng.choice(["Net 30", "Net 45", "Net 60"])),
                # Hidden helpers for job generation, dropped before saving.
                "_volume": rng.lognormal(0, 1),
                "_p_transformer": SEGMENT_TRANSFORMER_SHARE[segment],
            }
        )
    return pd.DataFrame(rows)


# --- Catalog ------------------------------------------------------------------
def sample_transformer(rng: np.random.Generator) -> dict:
    """One random, valid transformer configuration."""
    phase = int(rng.choice([3, 1], p=[0.8, 0.2]))
    primary = int(rng.choice([480, 600, 4160], p=[0.5, 0.35, 0.15]))
    return {
        "product_family": "transformer",
        "kva": float(rng.choice(KVA_3PH if phase == 3 else KVA_1PH)),
        "primary_v": primary,
        "secondary_v": str(rng.choice(SECONDARY_BY_PRIMARY[primary])),
        "phase": phase,
        "winding": str(rng.choice(["copper", "aluminum"], p=[0.45, 0.55])),
        "k_factor": int(rng.choice([1, 4, 13], p=[0.7, 0.2, 0.1])),
        "enclosure": str(rng.choice(["NEMA 1", "NEMA 3R"], p=[0.75, 0.25])),
        "efficiency": str(rng.choice(["DOE 2016", "premium"], p=[0.7, 0.3])),
    }


def sample_enclosure(rng: np.random.Generator) -> dict:
    """One random, valid enclosure configuration."""
    return {
        "product_family": "enclosure",
        "size": str(rng.choice(ENCLOSURE_SIZES)),
        "gauge": int(rng.choice([16, 14, 12], p=[0.3, 0.5, 0.2])),
        "finish": str(rng.choice(["powder gray", "powder white", "galvanized"], p=[0.6, 0.2, 0.2])),
        "nema_rating": str(
            rng.choice(["NEMA 1", "NEMA 3R", "NEMA 4", "NEMA 12"], p=[0.4, 0.3, 0.15, 0.15])
        ),
    }


def part_number(cfg: dict) -> str:
    """Systematic part number, e.g. TX-75-3P-480-208120-CU-K1-N1-D."""
    if cfg["product_family"] == "transformer":
        return "-".join(
            [
                "TX",
                f"{cfg['kva']:g}",
                f"{cfg['phase']}P",
                str(cfg["primary_v"]),
                cfg["secondary_v"].replace("/", ""),
                "CU" if cfg["winding"] == "copper" else "AL",
                f"K{cfg['k_factor']}",
                "N1" if cfg["enclosure"] == "NEMA 1" else "3R",
                "D" if cfg["efficiency"] == "DOE 2016" else "P",
            ]
        )
    nema = {"NEMA 1": "N1", "NEMA 3R": "3R", "NEMA 4": "N4", "NEMA 12": "N12"}[cfg["nema_rating"]]
    finish = {"powder gray": "GR", "powder white": "WH", "galvanized": "GV"}[cfg["finish"]]
    return f"EN-{cfg['size']}-{cfg['gauge']}G-{nema}-{finish}"


def description(cfg: dict) -> str:
    """Human-readable item description, the way an ERP catalog shows it."""
    if cfg["product_family"] == "transformer":
        return (
            f"XFMR {cfg['kva']:g}KVA {cfg['phase']}PH {cfg['primary_v']}-{cfg['secondary_v']} "
            f"{'CU' if cfg['winding'] == 'copper' else 'AL'} K{cfg['k_factor']} "
            f"{cfg['enclosure']} {cfg['efficiency'].upper()}"
        )
    return f"ENCL {cfg['size']} {cfg['gauge']}GA {cfg['nema_rating']} {cfg['finish'].upper()}"


def make_catalog(rng: np.random.Generator, n_tx: int = 300, n_en: int = 100) -> pd.DataFrame:
    """Finished-goods catalog: unique transformer and enclosure configurations."""
    configs: dict[str, dict] = {}
    for sampler, target in [(sample_transformer, n_tx), (sample_enclosure, n_en)]:
        found = 0
        while found < target:
            cfg = sampler(rng)
            pn = part_number(cfg)
            if pn not in configs:
                configs[pn] = cfg
                found += 1
    rows = [
        {"part_number": pn, "item_type": "finished", "description": description(cfg)} | cfg
        for pn, cfg in configs.items()
    ]
    return pd.DataFrame(rows)


def make_components() -> pd.DataFrame:
    """Purchased raw materials and hardware kits."""
    rows = [
        ("CU-COND", "Copper magnet wire", "kg", None),
        ("AL-COND", "Aluminum magnet strip", "kg", None),
        ("ESTEEL", "Electrical steel, grain oriented", "kg", None),
        ("SHEET", "Sheet steel, cold rolled", "kg", None),
    ] + [(kit, f"Hardware kit {kit[3:]}", "ea", cost) for kit, cost in cm.HARDWARE_KITS.items()]
    return pd.DataFrame(
        [
            {
                "part_number": pn,
                "item_type": "component",
                "description": desc,
                "uom": uom,
                "std_cost": cost,
            }
            for pn, desc, uom, cost in rows
        ]
    )


def item_config(item: pd.Series) -> dict:
    """Read a config dict back out of a catalog row."""
    fields = TRANSFORMER_FIELDS if item["product_family"] == "transformer" else ENCLOSURE_FIELDS
    cfg = {"product_family": item["product_family"]}
    for field in fields:
        value = item[field]
        cfg[field] = value.item() if hasattr(value, "item") else value
    return cfg


# --- BOMs and routings --------------------------------------------------------
def make_boms(catalog: pd.DataFrame) -> pd.DataFrame:
    """Material lines per finished item, all in kg (the mess step converts some to lb)."""
    rows = []
    for _, item in catalog.iterrows():
        cfg = item_config(item)
        m = cm.materials(cfg)
        lines = []
        if cfg["product_family"] == "transformer":
            conductor = "CU-COND" if cfg["winding"] == "copper" else "AL-COND"
            lines += [(conductor, m["conductor_kg"], "kg"), ("ESTEEL", m["core_kg"], "kg")]
        lines += [("SHEET", m["sheet_kg"], "kg"), (cm.hardware_kit(cfg), 1, "ea")]
        for n, (component, qty, uom) in enumerate(lines, start=1):
            rows.append(
                {
                    "parent_part": item["part_number"],
                    "line_no": n,
                    "component_part": component,
                    "qty": round(float(qty), 2),
                    "uom": uom,
                }
            )
    return pd.DataFrame(rows)


def make_routings(catalog: pd.DataFrame) -> pd.DataFrame:
    """Standard operations per finished item (hours for one unit)."""
    rows = []
    for _, item in catalog.iterrows():
        for n, (op, labor, machine) in enumerate(cm.routing(item_config(item)), start=1):
            rows.append(
                {
                    "part_number": item["part_number"],
                    "op_seq": n * 10,
                    "operation": op,
                    "labor_hours": round(labor, 2),
                    "machine_hours": round(machine, 2),
                }
            )
    return pd.DataFrame(rows)


# --- Jobs (quote history) -----------------------------------------------------
def pick_quantity(rng: np.random.Generator, family: str) -> int:
    """Order quantity: mostly small, sometimes large."""
    if family == "transformer":
        return int(rng.choice([1, 2, 3, 4, 5, 6, 8, 10, 12, 20], p=[
            0.35, 0.18, 0.12, 0.08, 0.08, 0.05, 0.05, 0.04, 0.03, 0.02,
        ]))  # fmt: skip
    return int(rng.choice([1, 2, 5, 10, 20, 25, 50], p=[0.2, 0.2, 0.2, 0.15, 0.1, 0.1, 0.05]))


def estimator_quote(cfg, qty, quote_date, segment, prices, rng) -> tuple[float, float]:
    """What the estimator quoted, and the estimated unit cost behind it.

    Estimators work from last month's metal prices and their estimates are a
    bit noisy (about 8%), so quotes lag in a rising copper market.
    """
    est_date = max(quote_date - pd.Timedelta(days=30), HISTORY_START)
    est_cost = cm.expected_unit_cost(cfg, qty, commodity.prices_on(prices, est_date))["total"]
    est_cost *= rng.lognormal(0, 0.08)
    margin = SEGMENT_MARGIN[segment] + rng.normal(0, 0.03)
    return round(est_cost * (1 + margin), 2), round(est_cost, 2)


def win_probability(quoted_price: float, true_cost: float) -> float:
    """Chance of winning: falls fast when we quote above the market price.

    The market price is the true cost plus a typical 22% margin.
    """
    market = true_cost * 1.22
    return 1 / (1 + np.exp(0.2 + 12 * (quoted_price / market - 1)))


def make_jobs(rng, customers, catalog, prices, n_jobs: int) -> pd.DataFrame:
    """Three years of quotes: config, quantity, price, won/lost, and actual costs if won."""
    span_days = (HISTORY_END - HISTORY_START).days
    quote_dates = sorted(
        HISTORY_START + pd.to_timedelta(rng.integers(0, span_days + 1, n_jobs), "D")
    )

    by_family = {
        fam: catalog[catalog["product_family"] == fam] for fam in ["transformer", "enclosure"]
    }
    weights = {fam: popularity(len(items), rng) for fam, items in by_family.items()}
    cust_weights = (customers["_volume"] / customers["_volume"].sum()).to_numpy()

    rows = []
    for i, quote_date in enumerate(quote_dates):
        cust = customers.iloc[rng.choice(len(customers), p=cust_weights)]
        family = "transformer" if rng.random() < cust["_p_transformer"] else "enclosure"
        item = by_family[family].iloc[rng.choice(len(by_family[family]), p=weights[family])]
        cfg = item_config(item)
        qty = pick_quantity(rng, family)

        prices_now = commodity.prices_on(prices, quote_date)
        true_cost = cm.expected_unit_cost(cfg, qty, prices_now)["total"]
        quoted, _ = estimator_quote(cfg, qty, quote_date, cust["segment"], prices, rng)
        won = rng.random() < win_probability(quoted, true_cost)

        row = {
            "job_id": f"J{100001 + i}",
            "customer_id": cust["customer_id"],
            "part_number": item["part_number"],
            "quantity": qty,
            "quote_date": iso(quote_date),
            "requested_ship_date": iso(quote_date + pd.Timedelta(days=int(rng.integers(21, 61)))),
            "ship_date": None,
            "quoted_unit_price": quoted,
            "status": "won" if won else "lost",
            "actual_material_cost": None,
            "actual_labor_cost": None,
            "actual_unit_cost": None,
            "notes": None,
        }
        if won:
            actual = cm.actual_unit_cost(cfg, qty, prices_now, rng)
            row["ship_date"] = iso(quote_date + pd.Timedelta(days=int(rng.integers(30, 91))))
            row["actual_material_cost"] = round(actual["material"] * qty, 2)
            row["actual_labor_cost"] = round(actual["labor"] * qty, 2)
            row["actual_unit_cost"] = round(actual["total"], 2)
            if actual["rework"] and rng.random() < 0.7:
                row["notes"] = "coil rework - retested OK"
        if row["notes"] is None and rng.random() < 0.15:
            row["notes"] = str(rng.choice(ROUTINE_NOTES))
        rows.append(row)
    return pd.DataFrame(rows)


# --- Current state: open quotes, inventory, purchase orders --------------------
def make_open_quotes(rng, customers, catalog, prices, n: int = 40) -> pd.DataFrame:
    """Quotes sent in the last ~7 weeks that customers have not answered yet."""
    rows = []
    for i in range(n):
        cust = customers.iloc[rng.integers(len(customers))]
        item = catalog.iloc[rng.integers(len(catalog))]
        cfg = item_config(item)
        qty = pick_quantity(rng, cfg["product_family"])
        quote_date = pd.Timestamp("2026-10-01") + pd.Timedelta(days=int(rng.integers(0, 50)))
        quoted, est_cost = estimator_quote(cfg, qty, quote_date, cust["segment"], prices, rng)
        rows.append(
            {
                "quote_id": f"Q-2026-{i + 1:04d}",
                "customer_id": cust["customer_id"],
                "part_number": item["part_number"],
                "quantity": qty,
                "quote_date": iso(quote_date),
                "valid_until": iso(quote_date + pd.Timedelta(days=30)),
                "est_unit_cost": est_cost,
                "quoted_unit_price": quoted,
                "status": "open",
            }
        )
    return pd.DataFrame(rows)


def make_inventory(rng, components: pd.DataFrame) -> pd.DataFrame:
    """On-hand stock of each purchased component."""
    rows = []
    for _, comp in components.iterrows():
        on_hand = rng.integers(20, 200) if comp["uom"] == "ea" else rng.integers(500, 8000)
        rows.append(
            {
                "part_number": comp["part_number"],
                "location": "MAIN",
                "on_hand_qty": int(on_hand),
                "uom": comp["uom"],
                "last_count_date": iso(TODAY - pd.Timedelta(days=int(rng.integers(1, 60)))),
            }
        )
    return pd.DataFrame(rows)


def make_open_pos(rng, fake: Faker, components: pd.DataFrame, prices, n: int = 15) -> pd.DataFrame:
    """Open purchase orders for raw materials and hardware."""
    metal_of = {"CU-COND": "copper", "AL-COND": "aluminum", "ESTEEL": "electrical_steel"}
    suppliers = [fake.unique.company() for _ in range(5)]
    rows = []
    for i in range(n):
        comp = components.iloc[rng.integers(len(components))]
        order_date = TODAY - pd.Timedelta(days=int(rng.integers(1, 45)))
        p = commodity.prices_on(prices, order_date)
        if comp["part_number"] in metal_of:
            unit_price = p[metal_of[comp["part_number"]]] * 1.08  # supplier premium
        elif comp["part_number"] == "SHEET":
            unit_price = p["electrical_steel"] * cm.SHEET_STEEL_RATIO * 1.08
        else:
            unit_price = comp["std_cost"]
        qty = rng.integers(50, 300) if comp["uom"] == "ea" else rng.integers(1000, 10000)
        rows.append(
            {
                "po_number": f"PO-{45001 + i}",
                "supplier": str(rng.choice(suppliers)),
                "part_number": comp["part_number"],
                "qty": int(qty),
                "uom": comp["uom"],
                "unit_price": round(float(unit_price), 2),
                "order_date": iso(order_date),
                "due_date": iso(order_date + pd.Timedelta(days=int(rng.integers(14, 60)))),
            }
        )
    return pd.DataFrame(rows)


# --- Deliberate mess ------------------------------------------------------------
# Real ERPs are messy. Each function below adds one kind of mess that
# foundation/ must clean up. They return new tables and never edit in place.
LB_PER_KG = 2.20462
MISSING_COLUMNS = {
    "jobs": ["requested_ship_date", "quoted_unit_price", "actual_labor_cost"],
    "items": ["description"],
    "customers": ["region", "payment_terms"],
    "boms": ["qty"],
}


def add_duplicate_parts(items, jobs, rng, share=0.05):
    """Give ~5% of finished items a second, legacy part number, and move some of
    their jobs onto it, so the same product appears under two numbers."""
    items, jobs = items.copy(), jobs.copy()
    finished = items[items["item_type"] == "finished"]
    picked = finished.sample(frac=share, random_state=rng)
    legacy = picked.copy()
    legacy["part_number"] = [f"L{40001 + i}" for i in range(len(legacy))]
    legacy["description"] = legacy["description"].str.replace(" ", ",", n=2).str.lower()
    for old, new in zip(picked["part_number"], legacy["part_number"], strict=True):
        on_old = jobs.index[jobs["part_number"] == old]
        moved = on_old[rng.random(len(on_old)) < 0.4]
        jobs.loc[moved, "part_number"] = new
    return pd.concat([items, legacy], ignore_index=True), jobs


def add_quote_rows(jobs, rng, share=0.05):
    """Copy the original quote record of ~5% of won jobs back into the jobs table,
    the way quotes and orders end up mixed in one ERP table."""
    won = jobs[jobs["status"] == "won"]
    quotes = won.sample(frac=share, random_state=rng).copy()
    quotes["job_id"] = "Q" + quotes["job_id"].str[1:]
    quotes["status"] = "quote"
    cost_cols = ["ship_date", "actual_material_cost", "actual_labor_cost", "actual_unit_cost"]
    quotes[cost_cols] = None
    quotes["notes"] = "quote - see order"
    mixed = pd.concat([jobs, quotes], ignore_index=True)
    return mixed.sort_values(["quote_date", "job_id"], kind="mergesort", ignore_index=True)


def add_cancelled(jobs, rng, share=0.03):
    """Mark ~3% of won jobs as cancelled, leaving the partial costs booked before
    cancellation. Their unit cost looks cheap and would mislead a model."""
    jobs = jobs.copy()
    won = jobs.index[jobs["status"] == "won"]
    picked = rng.choice(won, size=int(len(won) * share), replace=False)
    material = jobs.loc[picked, "actual_material_cost"] * rng.uniform(0.2, 0.6, len(picked))
    labor = jobs.loc[picked, "actual_labor_cost"] * rng.uniform(0.0, 0.3, len(picked))
    jobs.loc[picked, "status"] = "cancelled"
    jobs.loc[picked, "actual_material_cost"] = material.round(2)
    jobs.loc[picked, "actual_labor_cost"] = labor.round(2)
    unit = (material + labor * (1 + cm.OVERHEAD_RATE)) / jobs.loc[picked, "quantity"]
    jobs.loc[picked, "actual_unit_cost"] = unit.round(2)
    jobs.loc[picked, "notes"] = "cancelled by customer"
    return jobs


def add_outliers(jobs, rng, share=0.005):
    """Typo-style errors on ~0.5% of won jobs: unit cost off by a factor of 10."""
    jobs = jobs.copy()
    won = jobs.index[jobs["status"] == "won"]
    picked = rng.choice(won, size=max(1, int(len(won) * share)), replace=False)
    factor = rng.choice([10.0, 0.1], size=len(picked))
    jobs.loc[picked, "actual_unit_cost"] = (jobs.loc[picked, "actual_unit_cost"] * factor).round(2)
    return jobs


def mix_units(boms, rng, share=0.3):
    """Record ~30% of kg BOM lines in pounds instead."""
    boms = boms.copy()
    kg_rows = boms.index[boms["uom"] == "kg"]
    picked = kg_rows[rng.random(len(kg_rows)) < share]
    boms.loc[picked, "qty"] = (boms.loc[picked, "qty"] * LB_PER_KG).round(2)
    boms.loc[picked, "uom"] = "lb"
    return boms


def add_missing(table, columns, rng, share=0.03):
    """Blank out ~3% of the values in the given columns."""
    table = table.copy()
    for col in columns:
        blank = rng.random(len(table)) < share
        table[col] = table[col].astype(object).where(~blank, None)
    return table


def add_mess(tables: dict[str, pd.DataFrame], rng) -> dict[str, pd.DataFrame]:
    """Apply all deliberate mess to clean tables."""
    t = dict(tables)
    t["items"], t["jobs"] = add_duplicate_parts(t["items"], t["jobs"], rng)
    t["jobs"] = add_quote_rows(t["jobs"], rng)
    t["jobs"] = add_cancelled(t["jobs"], rng)
    t["jobs"] = add_outliers(t["jobs"], rng)
    t["boms"] = mix_units(t["boms"], rng)
    for name, columns in MISSING_COLUMNS.items():
        t[name] = add_missing(t[name], columns, rng)
    return t


# --- Assemble and save --------------------------------------------------------
def build_erp(
    seed: int = config.SEED, n_jobs: int = 3000, messy: bool = True
) -> dict[str, pd.DataFrame]:
    """Build every ERP table in memory. Same seed -> identical tables.

    The mess uses its own random stream, so the clean data underneath is the
    same whether `messy` is True or False.
    """
    rng = np.random.default_rng(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)

    prices = commodity.load_prices(seed)
    customers = make_customers(rng, fake)
    catalog = make_catalog(rng)
    components = make_components()
    jobs = make_jobs(rng, customers, catalog, prices, n_jobs)

    tables = {
        "customers": customers.drop(columns=["_volume", "_p_transformer"]),
        "items": pd.concat([catalog, components], ignore_index=True),
        "boms": make_boms(catalog),
        "routings": make_routings(catalog),
        "jobs": jobs,
        "commodity_prices": commodity.to_erp_table(prices),
        "open_quotes": make_open_quotes(rng, customers, catalog, prices),
        "inventory": make_inventory(rng, components),
        "open_pos": make_open_pos(rng, fake, components, prices),
    }
    if messy:
        tables = add_mess(tables, np.random.default_rng([seed, 1]))
    return tables


def write_erp(tables: dict[str, pd.DataFrame], path: Path) -> Path:
    """Write all tables to a fresh SQLite file (any old file is replaced)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with sqlite3.connect(path) as conn:
        for name, table in tables.items():
            table.to_sql(name, conn, index=False)
    return path


def generate(seed: int = config.SEED, n_jobs: int = 3000) -> Path:
    """Build the ERP and save it to data/generated/erp.sqlite."""
    tables = build_erp(seed, n_jobs)
    path = write_erp(tables, config.ERP_DB)
    for name, table in tables.items():
        print(f"{name:18s} {len(table):6d} rows")
    print(f"Wrote {path}")
    return path
