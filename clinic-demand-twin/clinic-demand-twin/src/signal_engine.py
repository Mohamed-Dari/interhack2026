"""
Core alert-generation logic.

Two independent pipelines:
  • Commodity: capture-rate analysis vs declared potential
  • Technical: inter-purchase interval overdue detection

Campaigns are global (no family link) – any overlap adds context, but does
NOT suppress the alert; it adds a note so the rep can decide.
"""

import uuid
import pandas as pd

# Static fallback when a client has no potential entry for a given category
_FAMILY_BY_CAT = {
    "C1": "Anestesia",
    "C2": "Biomateriales",
    "T1": "Biomateriales Técnics",
}


# ── Internal helpers ───────────────────────────────────────────────────────────

def _uid() -> str:
    return str(uuid.uuid4())[:8].upper()


def _campaign_context(reference_months: list, camp_months: set) -> tuple[bool, str]:
    overlap = set(reference_months) & camp_months
    if overlap:
        return True, f"campaña activa en {', '.join(sorted(overlap))}"
    return False, ""


def _confidence_for_commodity(n_hist_months: int) -> str:
    if n_hist_months >= 12:
        return "high"
    if n_hist_months >= 6:
        return "medium"
    return "low"


def _clinic_name(client_id, clients_df: pd.DataFrame) -> str:
    row = clients_df[clients_df["client_id"] == client_id]
    if row.empty:
        return f"Cliente {client_id}"
    return row.iloc[0]["clinic_name"]


# ── Commodity alerts ───────────────────────────────────────────────────────────

def generate_commodity_alerts(
    commodity_stats: pd.DataFrame,
    clients_df: pd.DataFrame,
    reference_months: list,
    camp_months: set,
) -> list[dict]:
    alerts = []
    n_ref = len(reference_months)
    in_campaign, camp_desc = _campaign_context(reference_months, camp_months)

    for _, row in commodity_stats.iterrows():
        cid            = row["client_id"]
        cat_id         = row["cat_id"]
        cat_name       = row.get("category_name", cat_id)
        family_name    = row.get("family_name") or _FAMILY_BY_CAT.get(cat_id, cat_id)
        classification = row.get("client_classification", "marginal")
        capture_rate   = row.get("capture_rate", 0.0)
        hist_avg       = row.get("historical_avg", 0.0)
        expected       = row.get("expected", 0.0)
        observed       = row.get("observed", 0.0)
        monthly_pot    = row.get("monthly_potential", 0.0)
        n_hist         = int(row.get("n_hist_months", 0))

        # Skip clients with too little history
        if n_hist < 3 or hist_avg < 1:
            continue

        alert_type = None
        alert_expected = expected
        alert_uncaptured = max(expected - observed, 0)

        # ── Loyal: recent observed drop ────────────────────────────────────
        if classification == "loyal":
            gap_ratio = (expected - observed) / max(expected, 1)
            if observed < expected * 0.60:
                alert_type = "anomalous_drop" if gap_ratio > 0.60 else "churn_risk"

        # ── Promiscuous: uncaptured potential window ───────────────────────
        elif classification == "promiscuous":
            uncaptured_potential = (monthly_pot - hist_avg) * n_ref
            if uncaptured_potential > monthly_pot * n_ref * 0.30:
                alert_type = "capture_window"
                alert_expected = monthly_pot * n_ref   # show full potential
                alert_uncaptured = max(alert_expected - observed, 0)

        # ── Marginal: any notable potential ────────────────────────────────
        elif classification == "marginal":
            if monthly_pot * n_ref > 50:
                alert_type = "capture_window"
                alert_expected = monthly_pot * n_ref
                alert_uncaptured = max(alert_expected - observed, 0)

        # ── Generic replenishment fallback ─────────────────────────────────
        if alert_type is None and expected > 5 and observed < expected * 0.50:
            alert_type = "replenishment_expected"

        if alert_type is None:
            continue

        confidence = _confidence_for_commodity(n_hist)

        alerts.append({
            "alert_id":                  _uid(),
            "client_id":                 cid,
            "clinic_name":               _clinic_name(cid, clients_df),
            "cat_id":                    cat_id,
            "family_name":               family_name,
            "category_name":             cat_name,
            "category_type":             "commodity",
            "alert_type":                alert_type,
            "client_classification":     classification,
            "capture_rate":              round(float(capture_rate), 3),
            "expected":                  round(float(alert_expected), 2),
            "observed":                  round(float(observed), 2),
            "monthly_potential":         round(float(monthly_pot), 2),
            "uncaptured":                round(float(alert_uncaptured), 2),
            "estimated_revenue_opp":     round(float(alert_uncaptured), 2),
            "days_since":                None,
            "median_interpurchase":      None,
            "n_purchases":               None,
            "confidence":                confidence,
            "campaign_context":          in_campaign,
            "campaign_note":             camp_desc if in_campaign else "",
        })

    return alerts


# ── Technical alerts ───────────────────────────────────────────────────────────

def generate_technical_alerts(
    technical_stats: pd.DataFrame,
    potential_df: pd.DataFrame,
    clients_df: pd.DataFrame,
    reference_months: list,
    camp_months: set,
) -> list[dict]:
    alerts = []
    in_campaign, camp_desc = _campaign_context(reference_months, camp_months)

    for _, row in technical_stats.iterrows():
        cid          = row["client_id"]
        cat_id       = row["cat_id"]
        cat_name     = row.get("category_name", cat_id)
        n            = int(row.get("n_purchases", 0))
        median_ip    = row.get("median_interpurchase")
        days_since   = row.get("days_since")
        confidence   = row.get("confidence", "low")
        avg_rev      = row.get("avg_rev_per_purchase", 0.0)

        # Require sufficient history and valid metrics
        if n < 3 or median_ip is None or days_since is None:
            continue

        threshold = median_ip * 1.5

        # Within normal window → no alert (covers designed case 3)
        if days_since <= threshold:
            continue

        overdue_ratio = days_since / max(median_ip, 1)

        if overdue_ratio < 2.0:
            alert_type = "replenishment_expected"
        elif overdue_ratio < 3.0:
            alert_type = "churn_risk"
        else:
            alert_type = "anomalous_drop"   # designed case 4 lands here

        # Potential reference
        pot_row = potential_df[
            (potential_df["client_id"] == cid) & (potential_df["cat_id"] == cat_id)
        ]
        monthly_pot = float(pot_row.iloc[0]["monthly_potential"]) if not pot_row.empty else avg_rev

        family_name = (
            pot_row.iloc[0]["family_name"] if not pot_row.empty
            else _FAMILY_BY_CAT.get(cat_id, cat_id)
        )

        alerts.append({
            "alert_id":              _uid(),
            "client_id":             cid,
            "clinic_name":           _clinic_name(cid, clients_df),
            "cat_id":                cat_id,
            "family_name":           family_name,
            "category_name":         cat_name,
            "category_type":         "technical",
            "alert_type":            alert_type,
            "client_classification": None,
            "capture_rate":          None,
            "expected":              round(float(avg_rev), 2),
            "observed":              0.0,
            "monthly_potential":     round(float(monthly_pot), 2),
            "uncaptured":            round(float(avg_rev), 2),
            "estimated_revenue_opp": round(float(avg_rev), 2),
            "days_since":            int(days_since),
            "median_interpurchase":  int(median_ip),
            "n_purchases":           n,
            "confidence":            confidence,
            "campaign_context":      in_campaign,
            "campaign_note":         camp_desc if in_campaign else "",
        })

    return alerts


# ── Combined entry point ───────────────────────────────────────────────────────

def generate_all_alerts(
    commodity_stats: pd.DataFrame,
    technical_stats: pd.DataFrame,
    potential_df: pd.DataFrame,
    clients_df: pd.DataFrame,
    reference_months: list,
    camp_months: set,
) -> pd.DataFrame:
    comm  = generate_commodity_alerts(commodity_stats, clients_df, reference_months, camp_months)
    tech  = generate_technical_alerts(technical_stats, potential_df, clients_df, reference_months, camp_months)
    all_a = comm + tech

    if not all_a:
        return pd.DataFrame()

    df = pd.DataFrame(all_a)
    # Deduplicate: keep highest uncaptured per (client, cat_id, alert_type)
    df = (
        df.sort_values("uncaptured", ascending=False)
        .drop_duplicates(subset=["client_id", "cat_id", "alert_type"])
        .reset_index(drop=True)
    )
    return df
