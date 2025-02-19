"""KPI catalogue.

A KPI is only computed when the source columns it needs can be resolved.
Column resolution is *transparent*:

``explicit``  the column was named by the user (tool argument) or by an
               approved metric definition.
``inferred``  the column was matched by a documented name heuristic; the
               match is reported in the evidence so the user can correct it.

If no candidate exists the tool fails with a ``missing_column_mapping`` error
that lists the roles the KPI needs and the columns that are available.  The
application never fabricates a business KPI that the data cannot support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Semantic roles a column can fulfil.  The right-hand side of each entry is
#: a list of lower-case substrings used for heuristic matching.
ROLE_HINTS: dict[str, tuple[str, ...]] = {
    "money": ("revenue", "sales", "amount", "gross", "net_sales", "total_sales", "income"),
    "cost": ("cost", "cogs", "cost_of_goods", "unit_cost"),
    "profit": ("profit", "margin_amount", "gross_profit"),
    "discount": ("discount", "rebate"),
    "quantity": ("quantity", "qty", "unit_count", "volume", "shipped_quantity", "line_items"),
    "unit_price": ("unit_price", "price", "list_price"),
    "date": ("date", "_dt", "timestamp", "ordered", "created_at", "delivered", "invoiced"),
    "order_id": ("order_id", "orderid", "order_no", "invoice", "transaction_id", "order_number"),
    "customer_id": ("customer_id", "customerid", "cust_id", "buyer_id", "account_id"),
    "product_id": ("product_id", "productid", "sku", "item_id", "article_id"),
    "product_name": ("product_name", "product", "item_name"),
    "category": ("category", "product_category", "dept", "department", "segment"),
    "region": ("region", "country", "state", "territory", "market", "zone", "area"),
    "channel": ("channel", "sales_channel", "source"),
    "supplier": ("supplier_name", "supplier"),
    "supplier_id": ("supplier_id", "supplierid", "vendor_id", "vendor"),
    "status": ("status", "delivery_status", "order_status", "state"),
    "on_time_flag": ("on_time", "ontime", "delivered_on_time", "is_late", "late"),
    "expected_date": ("expected_date", "due_date", "promised_date", "eta", "scheduled_date"),
    "actual_date": ("actual_date", "delivered_date", "received_date", "completion_date"),
    "churn_flag": ("churn", "churned", "cancelled", "canceled", "is_active"),
    "conversion_flag": ("converted", "conversion", "is_won", "won", "purchase"),
    "inventory_on_hand": (
        "inventory",
        "on_hand",
        "stock",
        "stock_level",
        "units_on_hand",
        "quantity_on_hand",
    ),
    "shipped_quantity": ("shipped_quantity", "shipped_qty"),
    "lead_time": ("lead_time", "delivery_time", "cycle_time"),
    "returned_flag": ("returned", "refunded", "is_return", "return_flag"),
    "email": ("email", "e_mail", "mail"),
}


@dataclass(frozen=True)
class KpiDefinition:
    """Definition of a supported business KPI."""

    name: str
    label: str
    description: str
    formula: str
    unit: str
    required_roles: tuple[str, ...]
    optional_roles: tuple[str, ...] = ()
    default_aggregation: str = "sum"
    currency_aware: bool = False
    notes: str = ""
    params: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "formula": self.formula,
            "unit": self.unit,
            "required_roles": list(self.required_roles),
            "optional_roles": list(self.optional_roles),
            "currency_aware": self.currency_aware,
            "notes": self.notes,
        }


KPI_CATALOGUE: dict[str, KpiDefinition] = {
    "revenue": KpiDefinition(
        name="revenue",
        label="Total revenue",
        description="Sum of the monetary sales amount across the selected rows.",
        formula="SUM(<money column>)",
        unit="currency",
        required_roles=("money",),
        currency_aware=True,
    ),
    "average_order_value": KpiDefinition(
        name="average_order_value",
        label="Average order value (AOV)",
        description=(
            "Total revenue divided by the number of distinct orders. "
            "Requires an order identifier so that multi-line orders are not double counted."
        ),
        formula="SUM(<money column>) / COUNT(DISTINCT <order id column>)",
        unit="currency",
        required_roles=("money", "order_id"),
        currency_aware=True,
        notes="Falls back to the row mean only when the data is already one row per order.",
    ),
    "gross_margin_amount": KpiDefinition(
        name="gross_margin_amount",
        label="Gross margin (amount)",
        description="Revenue minus cost of goods sold.",
        formula="SUM(<money column>) - SUM(<cost column>)",
        unit="currency",
        required_roles=("money", "cost"),
        currency_aware=True,
    ),
    "gross_margin_pct": KpiDefinition(
        name="gross_margin_pct",
        label="Gross margin (%)",
        description="Gross margin divided by revenue. Undefined when revenue is zero.",
        formula="(SUM(<money>) - SUM(<cost>)) / SUM(<money>) * 100",
        unit="percent",
        required_roles=("money", "cost"),
        currency_aware=True,
        notes="Zero-denominator case is reported explicitly as undefined.",
    ),
    "units_sold": KpiDefinition(
        name="units_sold",
        label="Units sold",
        description="Total number of units sold.",
        formula="SUM(<quantity column>)",
        unit="count",
        required_roles=("quantity",),
    ),
    "average_unit_price": KpiDefinition(
        name="average_unit_price",
        label="Average unit price",
        description="Mean of the unit price column.",
        formula="AVG(<unit price column>)",
        unit="currency",
        required_roles=("unit_price",),
        currency_aware=True,
    ),
    "effective_discount_pct": KpiDefinition(
        name="effective_discount_pct",
        label="Effective discount (%)",
        description="Average discount rate applied, expressed as a percentage.",
        formula="AVG(<discount column>) * 100",
        unit="percent",
        required_roles=("discount",),
    ),
    "conversion_rate": KpiDefinition(
        name="conversion_rate",
        label="Conversion rate",
        description="Share of rows flagged as converted.",
        formula="COUNT(<conversion flag> = true) / COUNT(*) * 100",
        unit="percent",
        required_roles=("conversion_flag",),
    ),
    "churn_rate": KpiDefinition(
        name="churn_rate",
        label="Churn rate",
        description="Share of rows flagged as churned / cancelled.",
        formula="COUNT(<churn flag> = true) / COUNT(*) * 100",
        unit="percent",
        required_roles=("churn_flag",),
    ),
    "return_rate": KpiDefinition(
        name="return_rate",
        label="Return rate",
        description="Share of rows flagged as returned / refunded.",
        formula="COUNT(<return flag> = true) / COUNT(*) * 100",
        unit="percent",
        required_roles=("returned_flag",),
    ),
    "on_time_delivery_pct": KpiDefinition(
        name="on_time_delivery_pct",
        label="On-time delivery (%)",
        description=(
            "Share of deliveries that arrived on or before the expected date, "
            "or whose status column marks them as on time."
        ),
        formula="COUNT(actual_date <= expected_date) / COUNT(expected_date) * 100",
        unit="percent",
        required_roles=("expected_date", "actual_date"),
        optional_roles=("status", "on_time_flag"),
    ),
    "inventory_turnover": KpiDefinition(
        name="inventory_turnover",
        label="Inventory turnover",
        description="Units sold divided by average inventory on hand.",
        formula="SUM(<quantity>) / AVG(<inventory on hand>)",
        unit="ratio",
        required_roles=("quantity", "inventory_on_hand"),
    ),
    "repeat_purchase_rate": KpiDefinition(
        name="repeat_purchase_rate",
        label="Repeat purchase rate",
        description="Share of customers with more than one order.",
        formula="COUNT(customers with >1 order) / COUNT(DISTINCT <customer id>) * 100",
        unit="percent",
        required_roles=("customer_id", "order_id"),
    ),
    "sales_growth": KpiDefinition(
        name="sales_growth",
        label="Sales growth",
        description="Period over period growth of the revenue metric.",
        formula="(current period value - previous period value) / previous period value * 100",
        unit="percent",
        required_roles=("date", "money"),
        currency_aware=True,
        notes="Requires a date column and a period; the previous period is derived automatically.",
    ),
}


def resolve_role(
    role: str,
    columns: list[dict[str, Any]],
    explicit: str | None = None,
) -> tuple[str | None, str]:
    """Resolve a semantic role to a column name.

    Returns ``(column, resolution)`` where resolution is ``"explicit"``,
    ``"inferred"`` or ``"unresolved"``.
    """
    if explicit:
        return explicit, "explicit"
    names = [str(c.get("name")) for c in columns]
    lowered = {name.lower(): name for name in names}
    for hint in ROLE_HINTS.get(role, ()):
        if hint in lowered:
            return lowered[hint], "inferred"
    for hint in ROLE_HINTS.get(role, ()):
        for lower_name, original in lowered.items():
            if hint in lower_name:
                return original, "inferred"
    return None, "unresolved"


#: Alternative parameter names a caller may use for each semantic role.
ROLE_PARAM_ALIASES: dict[str, tuple[str, ...]] = {
    "money": ("revenue_column", "sales_column", "amount_column", "revenue", "sales", "amount"),
    "cost": ("cost_column", "cogs_column", "cost", "cogs"),
    "quantity": ("quantity_column", "qty_column", "units_column", "quantity", "qty"),
    "unit_price": ("unit_price_column", "price_column", "unit_price", "price"),
    "discount": ("discount_column", "discount"),
    "order_id": ("order_id_column", "order_column", "order_id", "order_no"),
    "customer_id": ("customer_id_column", "customer_column", "customer_id"),
    "date": ("date_column", "order_date_column", "date"),
    "expected_date": ("expected_date_column", "due_date_column", "expected_date"),
    "actual_date": ("actual_date_column", "delivered_date_column", "actual_date"),
    "status": ("status_column", "delivery_status_column", "status"),
    "conversion_flag": ("conversion_column", "conversion_flag_column", "conversion"),
    "churn_flag": ("churn_column", "churn_flag_column", "churn"),
    "returned_flag": ("returned_column", "return_flag_column", "returned"),
    "inventory_on_hand": ("inventory_column", "on_hand_column", "inventory_on_hand"),
    "product_id": ("product_id_column", "sku_column", "product_id"),
    "product_name": ("product_name_column", "product_column", "product_name"),
    "region": ("region_column", "region"),
    "supplier": ("supplier_column", "supplier"),
    "supplier_id": ("supplier_id_column", "supplier_id"),
    "category": ("category_column", "category"),
}


def param_for_role(params: dict[str, Any], role: str) -> str | None:
    """Return the explicit column a caller provided for ``role``."""
    candidates = (role, f"{role}_column", *ROLE_PARAM_ALIASES.get(role, ()))
    for key in candidates:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def describe_catalogue() -> list[dict[str, Any]]:
    return [definition.to_dict() for definition in KPI_CATALOGUE.values()]
