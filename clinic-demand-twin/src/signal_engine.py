"""Generación de señales mediante reglas de negocio para Clinic Demand Twin."""

from __future__ import annotations

import uuid

import pandas as pd


def _alert_id() -> str:
    return uuid.uuid4().hex[:8].upper()


def _clinic_name(client_id, clients_df: pd.DataFrame) -> str:
    match = clients_df[clients_df["client_id"] == client_id]
    if match.empty:
        return f"Cliente {client_id}"
    return str(match.iloc[0]["clinic_name"])


def _campaign_context(
    family_id: int,
    reference_months: list[str],
    campaigns_by_family: dict[int, dict[str, list[str]]],
) -> tuple[bool, str]:
    months = campaigns_by_family.get(int(family_id), {})
    hits: list[str] = []
    for month in sorted(set(reference_months) & set(months.keys())):
        hits.extend(months[month])
    if not hits:
        return False, ""
    names = ", ".join(sorted(set(hits)))
    return True, f"possible efecto campaña: {names}"


def _commodity_confidence(n_purchase_months: int, n_reference_months: int) -> str:
    if n_purchase_months >= 12 and n_reference_months >= 2:
        return "high"
    if n_purchase_months >= 6:
        return "medium"
    return "low"


def _base_alert(row, clients_df: pd.DataFrame, campaign_context: tuple[bool, str]) -> dict:
    has_campaign, campaign_note = campaign_context
    return {
        "alert_id": _alert_id(),
        "client_id": row["client_id"],
        "clinic_name": _clinic_name(row["client_id"], clients_df),
        "family_id": int(row["family_id"]),
        "family_name": row["family_name"],
        "category_type": row["category_type"],
        "campaign_context": has_campaign,
        "campaign_note": campaign_note,
    }


def generate_commodity_alerts(
    commodity_stats: pd.DataFrame,
    clients_df: pd.DataFrame,
    reference_months: list[str],
    campaigns_by_family: dict[int, dict[str, list[str]]],
) -> list[dict]:
    alerts: list[dict] = []
    n_ref = max(len(reference_months), 1)

    for _, row in commodity_stats.iterrows():
        n_hist_purchase_months = int(row.get("n_hist_purchase_months", 0))
        historical_avg_units = float(row.get("historical_avg_units", 0) or 0)
        observed_units = float(row.get("observed_units", 0) or 0)
        expected_units = float(row.get("expected_units", 0) or 0)
        potential_units = float(row.get("potential_units", 0) or 0)
        monthly_potential = float(row.get("monthly_potential_units", 0) or 0)
        capture_rate = float(row.get("capture_rate", 0) or 0)
        avg_unit_price = float(row.get("avg_unit_price", 100) or 100)
        classification = row.get("client_classification", "marginal")

        if n_hist_purchase_months < 3 and historical_avg_units < 1:
            continue

        alert_type = None
        alert_expected_units = expected_units
        alert_uncaptured = max(expected_units - observed_units, 0)

        if classification == "loyal":
            gap_ratio = (expected_units - observed_units) / max(expected_units, 1)
            if observed_units < expected_units * 0.60:
                alert_type = "anomalous_drop" if gap_ratio >= 0.60 else "churn_risk"

        elif classification == "promiscuous":
            potential_gap = max(monthly_potential - historical_avg_units, 0) * n_ref
            recent_capture = observed_units / max(potential_units, 1)
            if potential_gap > potential_units * 0.20 and recent_capture < 0.70:
                alert_type = "capture_window"
                alert_expected_units = potential_units
                alert_uncaptured = max(alert_expected_units - observed_units, 0)

        elif classification == "marginal":
            recent_capture = observed_units / max(potential_units, 1)
            if potential_units >= 8 and recent_capture < 0.25:
                alert_type = "capture_window"
                alert_expected_units = potential_units
                alert_uncaptured = max(alert_expected_units - observed_units, 0)

        high_potential_low_recent = potential_units >= max(expected_units * 1.4, 10) and observed_units < potential_units * 0.25
        if alert_type is None and high_potential_low_recent:
            alert_type = "capture_window"
            alert_expected_units = potential_units
            alert_uncaptured = max(alert_expected_units - observed_units, 0)

        if alert_type is None and expected_units >= 4 and observed_units < expected_units * 0.50:
            alert_type = "replenishment_expected"

        if alert_type is None:
            continue

        campaign = _campaign_context(int(row["family_id"]), reference_months, campaigns_by_family)
        confidence = _commodity_confidence(n_hist_purchase_months, n_ref)
        alert = _base_alert(row, clients_df, campaign)
        alert.update(
            {
                "alert_type": alert_type,
                "expected_units": round(alert_expected_units, 2),
                "observed_units": round(observed_units, 2),
                "potential_units": round(potential_units, 2),
                "uncaptured_demand": round(max(alert_uncaptured, 0), 2),
                "estimated_revenue_opportunity": round(max(alert_uncaptured, 0) * avg_unit_price, 2),
                "confidence": confidence,
                "capture_rate": round(capture_rate, 3),
                "client_classification": classification,
                "days_since_last_purchase": None,
                "median_interpurchase_days": None,
                "n_purchases": None,
                "avg_unit_price": round(avg_unit_price, 2),
            }
        )
        alerts.append(alert)

    return alerts


def generate_technical_alerts(
    technical_stats: pd.DataFrame,
    potential_df: pd.DataFrame,
    clients_df: pd.DataFrame,
    reference_months: list[str],
    campaigns_by_family: dict[int, dict[str, list[str]]],
) -> list[dict]:
    alerts: list[dict] = []

    for _, row in technical_stats.iterrows():
        n_purchases = int(row.get("n_purchases", 0) or 0)
        median_days = row.get("median_interpurchase_days")
        days_since = row.get("days_since_last_purchase")

        if n_purchases < 3 or pd.isna(median_days) or pd.isna(days_since):
            continue

        median_days = float(median_days)
        days_since = float(days_since)
        observed_recent = float(row.get("observed_recent_units", 0) or 0)
        avg_units = float(row.get("avg_units_per_purchase", 0) or 0)
        avg_revenue = float(row.get("avg_revenue_per_purchase", 0) or 0)
        threshold = max(median_days * 1.5, median_days + 21)

        if days_since <= threshold:
            continue

        if observed_recent > avg_units * 0.50:
            continue

        overdue_ratio = days_since / max(median_days, 1)
        if overdue_ratio >= 3.0:
            alert_type = "anomalous_drop"
        elif overdue_ratio >= 2.0:
            alert_type = "churn_risk"
        else:
            alert_type = "replenishment_expected"

        family_id = int(row["family_id"])
        potential_match = potential_df[
            (potential_df["client_id"] == row["client_id"]) & (potential_df["family_id"] == family_id)
        ]
        monthly_potential = (
            float(potential_match.iloc[0]["monthly_potential_units"])
            if not potential_match.empty
            else max(avg_units, 1)
        )
        potential_units = monthly_potential * max(len(reference_months), 1)
        expected_units = max(avg_units, 1)
        uncaptured = max(expected_units - observed_recent, 0)
        estimated_revenue = avg_revenue if avg_revenue > 0 else uncaptured * 250

        campaign = _campaign_context(family_id, reference_months, campaigns_by_family)
        alert = _base_alert(row, clients_df, campaign)
        alert.update(
            {
                "alert_type": alert_type,
                "expected_units": round(expected_units, 2),
                "observed_units": round(observed_recent, 2),
                "potential_units": round(potential_units, 2),
                "uncaptured_demand": round(uncaptured, 2),
                "estimated_revenue_opportunity": round(estimated_revenue, 2),
                "confidence": row.get("confidence", "medium"),
                "capture_rate": None,
                "client_classification": None,
                "days_since_last_purchase": int(days_since),
                "median_interpurchase_days": int(round(median_days)),
                "n_purchases": n_purchases,
                "avg_unit_price": round(estimated_revenue / max(expected_units, 1), 2),
            }
        )
        alerts.append(alert)

    return alerts


def generate_all_alerts(
    commodity_stats: pd.DataFrame,
    technical_stats: pd.DataFrame,
    potential_df: pd.DataFrame,
    clients_df: pd.DataFrame,
    reference_months: list[str],
    campaigns_by_family: dict[int, dict[str, list[str]]],
) -> pd.DataFrame:
    commodity_alerts = generate_commodity_alerts(
        commodity_stats, clients_df, reference_months, campaigns_by_family
    )
    technical_alerts = generate_technical_alerts(
        technical_stats, potential_df, clients_df, reference_months, campaigns_by_family
    )
    alerts = commodity_alerts + technical_alerts
    if not alerts:
        return pd.DataFrame()

    df = pd.DataFrame(alerts)
    return (
        df.sort_values("estimated_revenue_opportunity", ascending=False)
        .drop_duplicates(["client_id", "family_id", "alert_type"])
        .reset_index(drop=True)
    )
