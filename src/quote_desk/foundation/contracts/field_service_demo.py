"""Contract for the fictional field-service sample in data/samples/field_service/.

It exists to show the engine is generic: a different business, different
tables, different mess, and the same cleaning code. Only this file changes.
"""

from quote_desk.foundation.contract import (
    Contract,
    Dataset,
    Filter,
    ForeignKey,
    Identity,
    Outliers,
    Table,
    Units,
)

CONTRACT = Contract(
    source="field_service_demo",
    tables=[
        Table(
            "sites",
            primary_key=["site_id"],
            types={
                "site_id": "str",
                "name": "str",
                "street": "str",
                "city": "str",
                "postal_code": "str",
            },
            # Customer: "a site is its address; some sites were re-created under new IDs."
            identity=Identity(["street", "city", "postal_code"], "work_orders", "site_id"),
        ),
        Table(
            "technicians",
            primary_key=["tech_id"],
            types={"tech_id": "str", "name": "str", "level": "category"},
        ),
        Table(
            "work_orders",
            primary_key=["wo_id"],
            types={
                "wo_id": "str",
                "site_id": "str",
                "tech_id": "str",
                "status": "category",
                "job_type": "category",
                "opened": "date",
                "labor": "float",
                "labor_unit": "category",
                "parts_cost": "float",
            },  # fmt: skip
            foreign_keys=[
                ForeignKey("site_id", "sites", "site_id"),
                ForeignKey("tech_id", "technicians", "tech_id"),
            ],
            allowed_values={"status": {"done", "open", "cancelled"}},
            units=Units("labor", "labor_unit", {"h": ("h", 1.0), "min": ("h", 1 / 60)}),
        ),
    ],
    datasets=[
        Dataset(
            "completed_work",
            base_table="work_orders",
            joins=[("sites", "site_id"), ("technicians", "tech_id")],
            filters=[Filter("status", {"done"}, "only finished work has final costs")],
            outliers=Outliers("parts_cost", [["site_id", "job_type"], ["job_type"]]),
        )
    ],
)
