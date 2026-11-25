"""Product families: which options a customer can ask for, per family.

Each family is a Pydantic model of its configuration, so a request with an impossible
option (a 7 kVA transformer, a "NEMA 9" enclosure) fails validation instead of being
priced. More families are added in Step 4; the registry `FAMILIES` is what the rest
of the code uses.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TransformerConfig(BaseModel):
    """A dry-type transformer, configured from a menu (configure-to-order)."""

    model_config = ConfigDict(extra="forbid")

    kva: float | None = Field(default=None, ge=15, le=1000, description="power rating in kVA")
    primary_v: Literal[480, 600, 4160] | None = None
    secondary_v: Literal["208/120", "480/277", "600/347"] | None = None
    phase: Literal[1, 3] | None = None
    winding: Literal["copper", "aluminum"] | None = None
    k_factor: Literal[1, 4, 13] | None = None
    enclosure: Literal["NEMA 1", "NEMA 3R"] | None = None
    efficiency: Literal["DOE 2016", "premium"] | None = None


class EnclosureConfig(BaseModel):
    """A steel electrical enclosure."""

    model_config = ConfigDict(extra="forbid")

    size: str | None = Field(default=None, description="e.g. '24x20x8' (inches)")
    gauge: Literal[12, 14, 16] | None = None
    finish: Literal["powder white", "powder gray", "galvanized"] | None = None
    nema_rating: Literal["NEMA 1", "NEMA 3R", "NEMA 4", "NEMA 12"] | None = None


FAMILIES: dict[str, type[BaseModel]] = {
    "transformer": TransformerConfig,
    "enclosure": EnclosureConfig,
}


def missing_options(family: str, config: BaseModel) -> list[str]:
    """Options the customer did not state (left empty), so the reply can ask for them."""
    return [name for name, value in config.model_dump().items() if value is None]
