"""Scoring, urgency and commercial routing."""

from __future__ import annotations

import pandas as pd


URGENCY_SCORE = {"high": 100, "medium": 60, "low": 20}
CONFIDENCE_SCORE = {"high": 100, "medium": 60, "low": 20}


def _severity_gap(row: pd.Series) -> float:
    expected = float(row.get("expected_units", 0) or 0)
    observed = float(row.get("observed_units", 0) or 0)
    if expected <= 0:
        return 0.0
    return min(max(expected - observed, 0) / expected * 100, 100)


def _urgency(row: pd.Series) -> str:
    alert_type = row.get("alert_type", "")
    if alert_type in {"anomalous_drop", "churn_risk"}:
        return "high"
    if alert_type == "capture_window":
        return "high" if _severity_gap(row) >= 55 else "medium"
    if row.get("category_type") == "technical":
        median = float(row.get("median_interpurchase_days", 1) or 1)
        days = float(row.get("days_since_last_purchase", 0) or 0)
        ratio = days / max(median, 1)
        if ratio >= 2.4:
            return "high"
        if ratio >= 1.7:
            return "medium"
    return "medium" if _severity_gap(row) >= 40 else "low"


def _channel(row: pd.Series, segment: str) -> str:
    urgency = row.get("urgency", "low")
    opportunity = float(row.get("estimated_revenue_opportunity", 0) or 0)
    confidence = row.get("confidence", "medium")

    if segment == "large" or opportunity >= 1200:
        return "delegado"
    if urgency == "high" and confidence != "low":
        return "delegado" if segment == "medium" else "televenta"
    if urgency in {"high", "medium"}:
        return "televenta"
    return "marketing_automation"


def score_alerts(alerts_df: pd.DataFrame, clients_df: pd.DataFrame) -> pd.DataFrame:
    if alerts_df.empty:
        return alerts_df

    df = alerts_df.copy()
    df["urgency"] = df.apply(_urgency, axis=1)

    segment_map = clients_df.set_index("client_id")["clinic_segment"].to_dict()
    df["clinic_segment"] = df["client_id"].map(segment_map).fillna("small")
    df["recommended_channel"] = df.apply(lambda row: _channel(row, row["clinic_segment"]), axis=1)

    severity_gap = df.apply(_severity_gap, axis=1)
    max_revenue = max(float(df["estimated_revenue_opportunity"].max() or 0), 1)
    revenue_norm = (df["estimated_revenue_opportunity"] / max_revenue * 100).clip(0, 100)
    urgency_score = df["urgency"].map(URGENCY_SCORE).fillna(20)
    confidence_score = df["confidence"].map(CONFIDENCE_SCORE).fillna(60)

    df["severity_gap"] = severity_gap.round(1)
    df["revenue_opportunity_normalized"] = revenue_norm.round(1)
    df["priority_score"] = (
        0.40 * severity_gap
        + 0.30 * revenue_norm
        + 0.20 * urgency_score
        + 0.10 * confidence_score
    ).clip(0, 100).round(1)

    return df.drop(columns=["clinic_segment"]).sort_values("priority_score", ascending=False).reset_index(drop=True)
