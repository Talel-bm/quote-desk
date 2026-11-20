"""Contract for the Lakeshore Electric ERP (fictional).

Every line here is something the customer told us after we showed them the
profile of their raw data. Nothing comes from how the synthetic data was
generated: e.g. we know `jobs.status` has four values because profiling found
them, and what each one means because the customer explained it.
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

# Columns that together describe what a product *is*. Two part numbers with the
# same values here are the same product. (Customer: "part numbers changed when
# we migrated systems; the configuration is what matters.")
CONFIG_COLUMNS = [
    "product_family",
    "kva", "primary_v", "secondary_v", "phase", "winding", "k_factor", "enclosure", "efficiency",
    "size", "gauge", "finish", "nema_rating",
]  # fmt: skip

CONTRACT = Contract(
    source="lakeshore_erp",
    tables=[
        Table(
            "customers",
            primary_key=["customer_id"],
            types={
                "customer_id": "str",
                "name": "str",
                "segment": "category",
                "country": "category",
                "region": "category",
                "email_domain": "str",
                "contact_name": "str",
                "contact_email": "str",
                "payment_terms": "category",
            },  # fmt: skip
            description="Customer master: one row per customer account.",
        ),
        Table(
            "items",
            primary_key=["part_number"],
            types={
                "part_number": "str",
                "item_type": "category",
                "description": "str",
                "product_family": "category",
                "kva": "float",
                "primary_v": "int",
                "secondary_v": "category",
                "phase": "int",
                "winding": "category",
                "k_factor": "int",
                "enclosure": "category",
                "efficiency": "category",
                "size": "category",
                "gauge": "int",
                "finish": "category",
                "nema_rating": "category",
                "uom": "category",
                "std_cost": "float",
            },  # fmt: skip
            allowed_values={"item_type": {"finished", "component"}},
            identity=Identity(CONFIG_COLUMNS, usage_table="jobs", usage_column="part_number"),
            description="Item master: finished products and purchased components.",
        ),
        Table(
            "boms",
            primary_key=["parent_part", "line_no"],
            types={
                "parent_part": "str",
                "line_no": "int",
                "component_part": "str",
                "qty": "float",
                "uom": "category",
            },  # fmt: skip
            foreign_keys=[
                ForeignKey("parent_part", "items", "part_number"),
                ForeignKey("component_part", "items", "part_number"),
            ],
            # Customer: "BOM quantities are entered in kg, but some clerks use pounds."
            units=Units(
                "qty", "uom", {"kg": ("kg", 1.0), "lb": ("kg", 0.45359237), "ea": ("ea", 1.0)}
            ),
            description="Bill of materials: component quantities per unit of a product.",
        ),
        Table(
            "routings",
            primary_key=["part_number", "op_seq"],
            types={
                "part_number": "str",
                "op_seq": "int",
                "operation": "category",
                "labor_hours": "float",
                "machine_hours": "float",
            },  # fmt: skip
            foreign_keys=[ForeignKey("part_number", "items", "part_number")],
            description="Manufacturing steps and standard hours per unit.",
        ),
        Table(
            "jobs",
            primary_key=["job_id"],
            types={
                "job_id": "str",
                "customer_id": "str",
                "part_number": "str",
                "quantity": "int",
                "quote_date": "date",
                "requested_ship_date": "date",
                "ship_date": "date",
                "quoted_unit_price": "float",
                "status": "category",
                "actual_material_cost": "float",
                "actual_labor_cost": "float",
                "actual_unit_cost": "float",
                "notes": "str",
            },  # fmt: skip
            foreign_keys=[
                ForeignKey("customer_id", "customers", "customer_id"),
                ForeignKey("part_number", "items", "part_number"),
            ],
            allowed_values={"status": {"won", "lost", "quote", "cancelled"}},
            description="Quote and order history (quotes and orders share this table).",
        ),
        Table(
            "commodity_prices",
            primary_key=["month", "metal"],
            types={
                "month": "str",
                "metal": "category",
                "usd_per_kg": "float",
                "source": "category",
            },
            description="Monthly metal price index used by purchasing.",
        ),
        Table(
            "open_quotes",
            primary_key=["quote_id"],
            types={
                "quote_id": "str",
                "customer_id": "str",
                "part_number": "str",
                "quantity": "int",
                "quote_date": "date",
                "valid_until": "date",
                "est_unit_cost": "float",
                "quoted_unit_price": "float",
                "status": "category",
            },  # fmt: skip
            foreign_keys=[
                ForeignKey("customer_id", "customers", "customer_id"),
                ForeignKey("part_number", "items", "part_number"),
            ],
            description="Quotes sent and awaiting the customer's answer.",
        ),
        Table(
            "inventory",
            primary_key=["part_number", "location"],
            types={
                "part_number": "str",
                "location": "category",
                "on_hand_qty": "int",
                "uom": "category",
                "last_count_date": "date",
            },  # fmt: skip
            foreign_keys=[ForeignKey("part_number", "items", "part_number")],
            description="Stock on hand per component and location.",
        ),
        Table(
            "open_pos",
            primary_key=["po_number"],
            types={
                "po_number": "str",
                "supplier": "str",
                "part_number": "str",
                "qty": "int",
                "uom": "category",
                "unit_price": "float",
                "order_date": "date",
                "due_date": "date",
            },  # fmt: skip
            foreign_keys=[ForeignKey("part_number", "items", "part_number")],
            description="Purchase orders placed with suppliers, not yet received.",
        ),
    ],
    datasets=[
        Dataset(
            "cost_history",
            base_table="jobs",
            joins=[("items", "part_number"), ("customers", "customer_id")],
            # Customer: "Only won orders were built, so only they have real costs.
            # 'quote' rows are the quote record kept next to an order; 'cancelled'
            # jobs only booked part of their cost before they stopped."
            filters=[
                Filter(
                    "status",
                    keep={"won"},
                    reason="only won orders were built and have complete actual costs",
                )
            ],
            # Customer: "Compare a job with other jobs for the same product; if there
            # are too few, with products of the same family and size."
            outliers=Outliers(
                column="actual_unit_cost",
                group_levels=[
                    ["part_number"],
                    ["product_family", "kva", "winding"],
                    ["product_family", "size", "gauge"],
                    ["product_family"],
                ],
            ),
            description="Won jobs with their product configuration and customer: "
            "what the cost model trains on.",
        )
    ],
)
