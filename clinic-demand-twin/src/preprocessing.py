"""Preprocesamiento y generación de variables para señales de demanda."""

from __future__ import annotations

import numpy as np
import pandas as pd


def get_reference_periods(sales_df: pd.DataFrame, n_recent: int = 2) -> tuple[set[str], set[str]]:
    """Devuelve meses históricos y meses recientes de referencia como cadenas YYYY-MM."""
    if sales_df.empty:
        return set(), set()
    months = pd.to_datetime(sales_df["date"]).dt.to_period("M").astype(str)
    all_months = sorted(months.dropna().unique())
    if len(all_months) <= n_recent:
        return set(), set(all_months)
    return set(all_months[:-n_recent]), set(all_months[-n_recent:])


def aggregate_by_family_month(sales_df: pd.DataFrame, products_df: pd.DataFrame) -> pd.DataFrame:
    """Agrega ventas por cliente, familia de producto y mes."""
    if sales_df.empty:
        return pd.DataFrame(
            columns=[
                "client_id",
                "family_id",
                "family_name",
                "category_type",
                "year_month",
                "units",
                "revenue",
            ]
        )

    product_cols = ["product_id", "family_id", "family_name", "category_type"]
    merged = sales_df.merge(products_df[product_cols].drop_duplicates("product_id"), on="product_id", how="left")
    merged = merged.dropna(subset=["family_id"])
    merged["family_id"] = merged["family_id"].astype(int)
    merged["year_month"] = pd.to_datetime(merged["date"]).dt.to_period("M").astype(str)

    return (
        merged.groupby(["client_id", "family_id", "family_name", "category_type", "year_month"], as_index=False)
        .agg(units=("units", "sum"), revenue=("revenue", "sum"))
    )


def _base_combinations(
    agg_df: pd.DataFrame,
    potential_df: pd.DataFrame,
    products_df: pd.DataFrame,
    category_type: str,
) -> pd.DataFrame:
    families = products_df[products_df["category_type"] == category_type][
        ["family_id", "family_name", "category_type"]
    ].drop_duplicates()
    from_potential = potential_df.merge(families[["family_id"]], on="family_id", how="inner")[
        ["client_id", "family_id"]
    ].drop_duplicates()
    from_sales = agg_df[agg_df["category_type"] == category_type][
        ["client_id", "family_id"]
    ].drop_duplicates()
    combos = pd.concat([from_potential, from_sales], ignore_index=True).drop_duplicates()
    return combos.merge(families, on="family_id", how="left")


def compute_commodity_stats(
    agg_df: pd.DataFrame,
    potential_df: pd.DataFrame,
    products_df: pd.DataFrame,
    historical_months: set[str],
    reference_months: set[str],
) -> pd.DataFrame:
    """Calcula líneas base y observaciones recientes para commodities por cliente."""
    combos = _base_combinations(agg_df, potential_df, products_df, "commodity")
    if combos.empty:
        return pd.DataFrame()

    commodity = agg_df[agg_df["category_type"] == "commodity"].copy()
    hist = commodity[commodity["year_month"].isin(historical_months)]
    recent = commodity[commodity["year_month"].isin(reference_months)]

    hist_stats = (
        hist.groupby(["client_id", "family_id"], as_index=False)
        .agg(
            historical_total_units=("units", "sum"),
            historical_total_revenue=("revenue", "sum"),
            n_hist_purchase_months=("year_month", "nunique"),
        )
    )
    recent_stats = (
        recent.groupby(["client_id", "family_id"], as_index=False)
        .agg(
            observed_units=("units", "sum"),
            observed_revenue=("revenue", "sum"),
            n_recent_purchase_months=("year_month", "nunique"),
        )
    )

    stats = combos.merge(hist_stats, on=["client_id", "family_id"], how="left")
    stats = stats.merge(recent_stats, on=["client_id", "family_id"], how="left")
    stats = stats.merge(
        potential_df[["client_id", "family_id", "monthly_potential_units"]],
        on=["client_id", "family_id"],
        how="left",
    )

    fill_zero_cols = [
        "historical_total_units",
        "historical_total_revenue",
        "n_hist_purchase_months",
        "observed_units",
        "observed_revenue",
        "n_recent_purchase_months",
    ]
    stats[fill_zero_cols] = stats[fill_zero_cols].fillna(0)
    n_hist = max(len(historical_months), 1)
    stats["historical_avg_units"] = stats["historical_total_units"] / n_hist
    stats["historical_avg_revenue"] = stats["historical_total_revenue"] / n_hist
    stats["avg_unit_price"] = (
        stats["historical_total_revenue"] / stats["historical_total_units"].replace(0, np.nan)
    )
    stats["avg_unit_price"] = stats["avg_unit_price"].fillna(
        stats["observed_revenue"] / stats["observed_units"].replace(0, np.nan)
    )
    stats["avg_unit_price"] = stats["avg_unit_price"].fillna(100.0)
    stats["monthly_potential_units"] = stats["monthly_potential_units"].fillna(
        (stats["historical_avg_units"] * 1.25).clip(lower=1)
    )
    stats["capture_rate"] = (
        stats["historical_avg_units"] / stats["monthly_potential_units"].clip(lower=0.01)
    ).clip(lower=0, upper=2)
    stats["client_classification"] = pd.cut(
        stats["capture_rate"],
        bins=[-np.inf, 0.15, 0.70, np.inf],
        labels=["marginal", "promiscuous", "loyal"],
    ).astype(str)
    stats["expected_units"] = stats["historical_avg_units"] * len(reference_months)
    stats["potential_units"] = stats["monthly_potential_units"] * len(reference_months)
    stats["uncaptured_demand"] = (stats["expected_units"] - stats["observed_units"]).clip(lower=0)
    return stats.reset_index(drop=True)


def compute_technical_stats(
    sales_df: pd.DataFrame,
    products_df: pd.DataFrame,
    reference_months: set[str],
    reference_end_date=None,
) -> pd.DataFrame:
    """Calcula variables de intervalo entre compras para familias técnicas."""
    if sales_df.empty:
        return pd.DataFrame()

    merged = sales_df.merge(
        products_df[["product_id", "family_id", "family_name", "category_type"]].drop_duplicates("product_id"),
        on="product_id",
        how="left",
    )
    tech = merged[merged["category_type"] == "technical"].copy()
    if tech.empty:
        return pd.DataFrame()

    tech["date"] = pd.to_datetime(tech["date"])
    tech["year_month"] = tech["date"].dt.to_period("M").astype(str)
    reference_end = pd.to_datetime(reference_end_date) if reference_end_date is not None else tech["date"].max()

    records = []
    for (client_id, family_id), group in tech.groupby(["client_id", "family_id"]):
        purchase_days = sorted(group["date"].dt.normalize().unique())
        n_purchases = len(purchase_days)
        purchase_series = pd.Series(pd.to_datetime(purchase_days)).sort_values()
        intervals = purchase_series.diff().dt.days.dropna().to_numpy()
        median_days = float(np.median(intervals)) if len(intervals) else np.nan
        std_days = float(np.std(intervals)) if len(intervals) else np.nan
        last_purchase = pd.to_datetime(purchase_days[-1]) if purchase_days else pd.NaT
        days_since = int((reference_end.normalize() - last_purchase.normalize()).days) if pd.notna(last_purchase) else np.nan

        daily = group.groupby(group["date"].dt.normalize()).agg(units=("units", "sum"), revenue=("revenue", "sum"))
        avg_units_per_purchase = float(daily["units"].mean()) if not daily.empty else 0.0
        avg_revenue_per_purchase = float(daily["revenue"].mean()) if not daily.empty else 0.0
        observed_recent_units = float(group[group["year_month"].isin(reference_months)]["units"].sum())
        observed_recent_revenue = float(group[group["year_month"].isin(reference_months)]["revenue"].sum())

        if n_purchases < 3:
            confidence = "low"
        elif n_purchases < 6:
            confidence = "medium"
        else:
            confidence = "high"

        family_name = group["family_name"].dropna().iloc[0] if group["family_name"].notna().any() else str(family_id)
        records.append(
            {
                "client_id": client_id,
                "family_id": int(family_id),
                "family_name": family_name,
                "category_type": "technical",
                "n_purchases": n_purchases,
                "median_interpurchase_days": median_days,
                "std_interpurchase_days": std_days,
                "last_purchase_date": last_purchase,
                "days_since_last_purchase": days_since,
                "avg_units_per_purchase": avg_units_per_purchase,
                "avg_revenue_per_purchase": avg_revenue_per_purchase,
                "observed_recent_units": observed_recent_units,
                "observed_recent_revenue": observed_recent_revenue,
                "confidence": confidence,
            }
        )

    return pd.DataFrame(records)


def campaign_calendar(campaigns_df: pd.DataFrame) -> dict[int, dict[str, list[str]]]:
    """Devuelve {family_id: {YYYY-MM: [nombres de campaña]}}."""
    calendar: dict[int, dict[str, list[str]]] = {}
    if campaigns_df.empty:
        return calendar

    for row in campaigns_df.itertuples():
        family_id = int(row.family_id)
        current = pd.to_datetime(row.start_date).replace(day=1)
        end = pd.to_datetime(row.end_date)
        while current <= end:
            month = current.strftime("%Y-%m")
            calendar.setdefault(family_id, {}).setdefault(month, []).append(str(row.campaign_name))
            current = (current.replace(day=28) + pd.Timedelta(days=4)).replace(day=1)
    return calendar
