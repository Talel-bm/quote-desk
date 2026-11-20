"""The hidden "true cost" rules of the fictional factory.

Real data would never show you these formulas: the ML model in forge/ has to
learn them from job history. They are rough engineering rules of thumb, tuned
to give plausible numbers, not a real transformer design method.

A config is a plain dict, e.g.
  {"product_family": "transformer", "kva": 75, "primary_v": 480, "secondary_v": "208/120",
   "phase": 3, "winding": "copper", "k_factor": 1, "enclosure": "NEMA 1",
   "efficiency": "DOE 2016"}
  {"product_family": "enclosure", "size": "24x20x8", "gauge": 14,
   "finish": "powder gray", "nema_rating": "NEMA 3R"}
"""

import numpy as np

# --- Factory constants -------------------------------------------------------
LABOR_RATE = 55.0  # US$ per labor hour
OVERHEAD_RATE = 0.35  # overhead as a share of labor cost
SCRAP_FACTOR = 1.04  # 4% extra material lost to offcuts and scrap
SHEET_STEEL_RATIO = 0.42  # plain sheet steel costs ~42% of electrical steel per kg
LEARNING_EXPONENT = -0.15  # labor per unit falls as quantity rises: qty ** -0.15
REWORK_RATE = 0.05  # share of jobs that need rework
STEEL_DENSITY = 7850  # kg per cubic meter

GAUGE_MM = {16: 1.52, 14: 1.90, 12: 2.66}  # sheet thickness by steel gauge

# Hardware kits: part number -> standard cost (US$).
HARDWARE_KITS = {"HW-S": 45.0, "HW-M": 90.0, "HW-L": 180.0, "HW-XL": 340.0}


# --- Bill of materials ---------------------------------------------------------
def hardware_kit(cfg: dict) -> str:
    """Pick the hardware kit (bolts, lugs, gaskets, labels) for a config."""
    if cfg["product_family"] == "enclosure":
        return "HW-S" if cfg["nema_rating"] in ("NEMA 1", "NEMA 3R") else "HW-M"
    kva = cfg["kva"]
    if kva <= 45:
        return "HW-S"
    if kva <= 150:
        return "HW-M"
    if kva <= 500:
        return "HW-L"
    return "HW-XL"


def transformer_materials(cfg: dict) -> dict[str, float]:
    """Material masses (kg per unit) for one transformer.

    Core and winding mass grow like kVA ** 0.75 (bigger units are more
    material-efficient per kVA). Aluminum conducts worse than copper, so it needs
    a bigger cross-section, but it is so much lighter that the winding weighs
    about half as much.
    """
    size = cfg["kva"] ** 0.75
    k_core = {1: 1.00, 4: 1.05, 13: 1.15}[cfg["k_factor"]]
    k_wind = {1: 1.00, 4: 1.10, 13: 1.25}[cfg["k_factor"]]
    premium = cfg["efficiency"] == "premium"
    single_phase = cfg["phase"] == 1

    core_kg = 6.3 * size * k_core * (1.12 if premium else 1.0) * (0.85 if single_phase else 1.0)
    copper_equiv_kg = 2.0 * size * k_wind * (1.08 if premium else 1.0)
    if cfg["primary_v"] == 4160:
        copper_equiv_kg *= 1.15  # medium-voltage primary needs more insulation and turns
    conductor_kg = copper_equiv_kg * (0.5 if cfg["winding"] == "aluminum" else 1.0)
    sheet_kg = 4.5 * cfg["kva"] ** 0.6 * (1.2 if cfg["enclosure"] == "NEMA 3R" else 1.0)

    return {
        "conductor_kg": conductor_kg,
        "core_kg": core_kg,
        "sheet_kg": sheet_kg,
    }


def enclosure_area_m2(size: str) -> float:
    """Sheet-metal surface area of a box given as 'HxWxD' in inches, plus a back panel."""
    h, w, d = (float(x) for x in size.split("x"))
    area_in2 = 2 * (h * w + h * d + w * d) + h * w  # six faces + internal back panel
    return area_in2 * 0.00064516  # square inches -> square meters


def enclosure_materials(cfg: dict) -> dict[str, float]:
    """Material masses (kg per unit) for one enclosure: just sheet steel."""
    thickness_m = GAUGE_MM[cfg["gauge"]] / 1000
    sheet_kg = enclosure_area_m2(cfg["size"]) * thickness_m * STEEL_DENSITY
    return {"conductor_kg": 0.0, "core_kg": 0.0, "sheet_kg": sheet_kg}


def materials(cfg: dict) -> dict[str, float]:
    """Material masses for any config."""
    if cfg["product_family"] == "transformer":
        return transformer_materials(cfg)
    return enclosure_materials(cfg)


# --- Routing (labor) -----------------------------------------------------------
def routing(cfg: dict) -> list[tuple[str, float, float]]:
    """Standard operations for one unit: (operation, labor hours, machine hours)."""
    if cfg["product_family"] == "transformer":
        s = cfg["kva"] ** 0.6
        k_extra = {1: 1.0, 4: 1.1, 13: 1.25}[cfg["k_factor"]]
        return [
            ("coil winding", 0.60 * s * k_extra, 0.45 * s),
            ("core stacking", 0.35 * s, 0.10 * s),
            ("assembly", 3.0 + 0.03 * cfg["kva"], 0.0),
            ("test", 1.5 + 0.004 * cfg["kva"], 1.0),
            ("enclosure and paint", 1.5 + 0.02 * cfg["kva"], 0.5),
        ]
    area = enclosure_area_m2(cfg["size"])
    sealed = cfg["nema_rating"] in ("NEMA 4", "NEMA 12")
    return [
        ("cut and bend", 0.4 + 0.25 * area, 0.3 + 0.2 * area),
        ("weld", (0.5 + 0.5 * area) * (1.3 if sealed else 1.0), 0.0),
        ("finish", 0.3 + 0.3 * area, 0.2 + 0.2 * area),
        ("assembly", 0.5 + (0.4 if sealed else 0.0), 0.0),
    ]


def labor_hours(cfg: dict, qty: int) -> float:
    """Labor hours per unit, after the learning curve for a batch of `qty`."""
    standard = sum(labor for _, labor, _ in routing(cfg))
    return standard * qty**LEARNING_EXPONENT


# --- Cost ---------------------------------------------------------------------
def material_cost(cfg: dict, prices: dict[str, float]) -> float:
    """Material cost per unit (US$) at the given metal prices ($/kg)."""
    m = materials(cfg)
    conductor_price = prices[cfg["winding"]] if cfg["product_family"] == "transformer" else 0.0
    sheet_price = prices["electrical_steel"] * SHEET_STEEL_RATIO
    metal = (
        m["conductor_kg"] * conductor_price
        + m["core_kg"] * prices["electrical_steel"]
        + m["sheet_kg"] * sheet_price
    )
    finish_extra = 0.0
    if cfg["product_family"] == "enclosure":
        finish_extra = {"powder gray": 0.0, "powder white": 0.05, "galvanized": 0.15}[
            cfg["finish"]
        ] * metal
    return metal * SCRAP_FACTOR + finish_extra + HARDWARE_KITS[hardware_kit(cfg)]


def expected_unit_cost(cfg: dict, qty: int, prices: dict[str, float]) -> dict[str, float]:
    """Cost per unit with no surprises: materials + labor + overhead."""
    material = material_cost(cfg, prices)
    labor = labor_hours(cfg, qty) * LABOR_RATE
    overhead = labor * OVERHEAD_RATE
    return {
        "material": material,
        "labor": labor,
        "overhead": overhead,
        "total": material + labor + overhead,
    }


def actual_unit_cost(
    cfg: dict, qty: int, prices: dict[str, float], rng: np.random.Generator
) -> dict[str, float]:
    """What a job really cost per unit: expected cost plus noise and occasional rework."""
    cost = expected_unit_cost(cfg, qty, prices)
    rework = rng.random() < REWORK_RATE
    material = cost["material"] * rng.lognormal(0, 0.03)
    labor = cost["labor"] * rng.lognormal(0, 0.06) * (rng.uniform(1.2, 1.4) if rework else 1.0)
    overhead = labor * OVERHEAD_RATE
    return {
        "material": material,
        "labor": labor,
        "overhead": overhead,
        "total": material + labor + overhead,
        "rework": rework,
    }
