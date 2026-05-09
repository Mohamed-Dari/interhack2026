"""
Aggregation and per-client-category statistics.

All monetary values are in EUR (revenue).  'monthly_potential' is the
declared monthly revenue potential; historical_avg is the monthly avg
actually sold.  The signal engine receives these standardised tables.
"""

import numpy as np
import pandas as pd


# ── Period helpers ─────────────────────────────────────────────────────────────

def get_reference_periods(sales_df: pd.DataFrame, n_recent: int = 2) -> tuple[set, set]:
    """Return (historical_months, reference_months) as 'YYYY-MM' string sets."""
    ym = pd.to_datetime(sales_df["date"]).dt.to_period("M").astype(str)
    all_months = sorted(ym.unique())
    if len(all_months) < n_recent:
        return set(), set(all_months)
    reference   = set(all_months[-n_recent:])
    historical  = set(all_months[:-n_recent])
    return historical, reference


# ── Sales aggregation ──────────────────────────────────────────────────────────

def aggregate_by_category_month(sales_df: pd.DataFrame, products_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate sales to (client_id, cat_id, year_month) level."""
    need_cols = {"cat_id", "category_type", "category_name"}
    if not need_cols.issubset(products_df.columns):
        # Fallback: derive cat_id from family info if needed
        products_df = products_df.copy()
        if "cat_id" not in products_df.columns:
            products_df["cat_id"] = products_df.get("family_id", 0).astype(str)

    df = sales_df.merge(
        products_df[["product_id", "cat_id", "category_type", "category_name"]].drop_duplicates("product_id"),
        on="product_id", how="left"
    )
    df["year_month"] = pd.to_datetime(df["date"]).dt.to_period("M").astype(str)

    agg = (
        df.groupby(["client_id", "cat_id", "category_type", "category_name", "year_month"])
        .agg(revenue=("revenue", "sum"), units=("units", "sum"))
        .reset_index()
    )
    return agg


# ── Commodity statistics ───────────────────────────────────────────────────────

def compute_commodity_stats(
    agg_df: pd.DataFrame,
    potential_df: pd.DataFrame,
    historical_months: set,
    reference_months: set,
) -> pd.DataFrame:
    """
    Per (client, cat_id) stats for commodity categories.
    Returns a DataFrame used by signal_engine.generate_commodity_alerts.
    """
    comm = agg_df[agg_df["category_type"] == "commodity"].copy()

    hist = comm[comm["year_month"].isin(historical_months)]
    recent = comm[comm["year_month"].isin(reference_months)]

    # Historical averages per month
    hist_avg = (
        hist.groupby(["client_id", "cat_id", "category_type", "category_name"])
        .agg(
            historical_avg=("revenue", "mean"),
            historical_total=("revenue", "sum"),
            n_hist_months=("year_month", "nunique"),
        )
        .reset_index()
    )

    # Recent observed (sum over reference window)
    recent_obs = (
        recent.groupby(["client_id", "cat_id"])
        .agg(observed=("revenue", "sum"), n_recent_months=("year_month", "nunique"))
        .reset_index()
    )

    # Merge with potential
    pot_cols = ["client_id", "cat_id", "monthly_potential", "family_name"]
    pot_cols = [c for c in pot_cols if c in potential_df.columns]
    stats = hist_avg.merge(potential_df[pot_cols].drop_duplicates(["client_id", "cat_id"]),
                           on=["client_id", "cat_id"], how="left")
    stats = stats.merge(recent_obs, on=["client_id", "cat_id"], how="left")

    stats["observed"]       = stats["observed"].fillna(0)
    stats["n_recent_months"] = stats["n_recent_months"].fillna(0).astype(int)
    stats["monthly_potential"] = stats["monthly_potential"].fillna(stats["historical_avg"] * 1.2)

    n_ref = len(reference_months)
    # capture_rate vs declared monthly potential
    stats["capture_rate"] = (
        stats["historical_avg"] / stats["monthly_potential"].clip(lower=0.01)
    ).clip(0, 2.0)

    stats["client_classification"] = pd.cut(
        stats["capture_rate"],
        bins=[-np.inf, 0.15, 0.70, np.inf],
        labels=["marginal", "promiscuous", "loyal"],
    ).astype(str)

    stats["expected"] = stats["historical_avg"] * n_ref
    stats["uncaptured"] = (stats["expected"] - stats["observed"]).clip(lower=0)

    return stats.reset_index(drop=True)


# ── Technical statistics ───────────────────────────────────────────────────────

def compute_technical_stats(
    sales_df: pd.DataFrame,
    products_df: pd.DataFrame,
    reference_end_date=None,
) -> pd.DataFrame:
    """
    Per (client, cat_id) inter-purchase stats for technical categories.
    Returns a DataFrame used by signal_engine.generate_technical_alerts.
    """
    df = sales_df.merge(
        products_df[["product_id", "cat_id", "category_type", "category_name"]].drop_duplicates("product_id"),
        on="product_id", how="left"
    )
    tech = df[df["category_type"] == "technical"].copy()
    tech["date"] = pd.to_datetime(tech["date"])

    if reference_end_date is None:
        reference_end_date = tech["date"].max()
    else:
        reference_end_date = pd.to_datetime(reference_end_date)

    records = []
    for (cid, cat_id), grp in tech.groupby(["client_id", "cat_id"]):
        dates = sorted(grp["date"].tolist())
        n = len(dates)

        cat_info = products_df[products_df["cat_id"] == cat_id].iloc[0] if not products_df[products_df["cat_id"] == cat_id].empty else None
        cat_name = cat_info["category_name"] if cat_info is not None else cat_id

        # Inter-purchase intervals
        if n >= 2:
            intervals = [(dates[i + 1] - dates[i]).days for i in range(n - 1)]
            median_ip = float(np.median(intervals))
            std_ip    = float(np.std(intervals))
        else:
            median_ip = std_ip = None

        confidence = "low" if n < 3 else ("medium" if n < 6 else "high")

        last_dt    = dates[-1] if dates else None
        days_since = (reference_end_date - last_dt).days if last_dt else None

        # Average revenue per purchase event
        daily_rev = grp.groupby("date")["revenue"].sum()
        avg_rev_per_purchase = float(daily_rev.mean()) if not daily_rev.empty else 0

        records.append({
            "client_id":             cid,
            "cat_id":                cat_id,
            "category_name":         cat_name,
            "category_type":         "technical",
            "n_purchases":           n,
            "median_interpurchase":  median_ip,
            "std_interpurchase":     std_ip,
            "last_purchase_date":    last_dt,
            "days_since":            days_since,
            "avg_rev_per_purchase":  avg_rev_per_purchase,
            "confidence":            confidence,
        })

    return pd.DataFrame(records)


# ── Campaign month helper ──────────────────────────────────────────────────────

def campaign_months_set(campaigns_df: pd.DataFrame) -> set:
    """Return set of 'YYYY-MM' strings covered by any campaign."""
    months = set()
    for _, row in campaigns_df.iterrows():
        cur = pd.to_datetime(row["start_date"]).replace(day=1)
        end = pd.to_datetime(row["end_date"])
        while cur <= end:
            months.add(cur.strftime("%Y-%m"))
            cur = (cur.replace(day=28) + pd.Timedelta(days=4)).replace(day=1)
    return months
