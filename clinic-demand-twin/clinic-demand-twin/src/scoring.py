"""
Scoring layer: assigns urgency, channel, confidence, and priority_score.

priority_score = 40% severity_gap
               + 30% revenue_opportunity_normalised
               + 20% urgency_score
               + 10% confidence_score
"""

import numpy as np
import pandas as pd


_URGENCY_SCORE  = {"high": 100, "medium": 60, "low": 20}
_CONF_SCORE     = {"high": 100, "medium": 60, "low": 20}


# ── Urgency ────────────────────────────────────────────────────────────────────

def _compute_urgency(row: pd.Series) -> str:
    atype    = row.get("alert_type", "")
    expected = row.get("expected", 0) or 0
    observed = row.get("observed", 0) or 0
    days     = row.get("days_since") or 0
    median   = row.get("median_interpurchase") or 1

    if atype == "anomalous_drop":
        return "high"
    if atype == "churn_risk":
        return "high"
    if atype == "capture_window":
        gap = (expected - observed) / max(expected, 1)
        return "high" if gap > 0.50 else "medium"
    if atype == "replenishment_expected":
        if row.get("category_type") == "technical":
            ratio = days / max(median, 1)
            return "high" if ratio > 2.5 else ("medium" if ratio > 1.8 else "low")
        gap = (expected - observed) / max(expected, 1)
        return "medium" if gap > 0.30 else "low"
    return "low"


# ── Channel ────────────────────────────────────────────────────────────────────

def _compute_channel(row: pd.Series, segment: str) -> str:
    urgency = row.get("urgency", "low")
    rev_opp = row.get("estimated_revenue_opp", 0) or 0

    if segment == "large":
        return "delegado"
    if segment == "medium":
        if urgency == "high" or rev_opp > 500:
            return "delegado"
        return "televenta"
    # small
    if urgency == "high":
        return "televenta"
    return "marketing_automation"


# ── Priority score ─────────────────────────────────────────────────────────────

def _severity_gap_score(row: pd.Series) -> float:
    expected = row.get("expected", 0) or 0
    observed = row.get("observed", 0) or 0
    if expected <= 0:
        return 0.0
    gap = max(expected - observed, 0) / expected
    return min(gap * 100, 100)


# ── Public API ─────────────────────────────────────────────────────────────────

def score_alerts(alerts_df: pd.DataFrame, clients_df: pd.DataFrame) -> pd.DataFrame:
    if alerts_df.empty:
        return alerts_df

    df = alerts_df.copy()

    # Urgency
    df["urgency"] = df.apply(_compute_urgency, axis=1)

    # Channel (requires client segment)
    seg_map = clients_df.set_index("client_id")["clinic_segment"].to_dict()
    df["clinic_segment"]      = df["client_id"].map(seg_map).fillna("small")
    df["recommended_channel"] = df.apply(
        lambda r: _compute_channel(r, r["clinic_segment"]), axis=1
    )
    df = df.drop(columns=["clinic_segment"])

    # Severity gap (0-100)
    severity = df.apply(_severity_gap_score, axis=1)

    # Revenue opportunity normalised (0-100)
    max_rev = df["estimated_revenue_opp"].max()
    rev_norm = (df["estimated_revenue_opp"] / max(max_rev, 1)) * 100

    # Urgency score (0-100)
    urg_score  = df["urgency"].map(_URGENCY_SCORE).fillna(20)

    # Confidence score (0-100)
    conf_score = df["confidence"].map(_CONF_SCORE).fillna(60)

    df["priority_score"] = (
        0.40 * severity +
        0.30 * rev_norm +
        0.20 * urg_score +
        0.10 * conf_score
    ).clip(0, 100).round(1)

    return df.sort_values("priority_score", ascending=False).reset_index(drop=True)
