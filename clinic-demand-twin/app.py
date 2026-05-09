"""Clinic Demand Twin Streamlit app."""

from __future__ import annotations

import os
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data_loader import load_all_data
from src.explanations import add_explanations
from src.feedback import feedback_status_map, load_feedback, save_feedback
from src.preprocessing import (
    aggregate_by_family_month,
    campaign_calendar,
    compute_commodity_stats,
    compute_technical_stats,
    get_reference_periods,
)
from src.scoring import score_alerts
from src.signal_engine import generate_all_alerts


st.set_page_config(
    page_title="Clinic Demand Twin",
    page_icon="🦷",
    layout="wide",
    initial_sidebar_state="expanded",
)

ALERT_COLORS = {
    "replenishment_expected": "#2563eb",
    "capture_window": "#f59e0b",
    "churn_risk": "#dc2626",
    "anomalous_drop": "#7c2d12",
}
URGENCY_COLORS = {"high": "#dc2626", "medium": "#f59e0b", "low": "#16a34a"}


@st.cache_data(show_spinner="Carregant i processant dades...")
def build_pipeline() -> dict:
    sales, clients, products, potential, campaigns = load_all_data()
    historical_months, reference_months = get_reference_periods(sales, n_recent=2)
    agg = aggregate_by_family_month(sales, products)
    commodity_stats = compute_commodity_stats(agg, potential, products, historical_months, reference_months)
    technical_stats = compute_technical_stats(
        sales,
        products,
        reference_months,
        reference_end_date=pd.to_datetime(sales["date"]).max() if not sales.empty else None,
    )
    campaigns_by_family = campaign_calendar(campaigns)
    alerts = generate_all_alerts(
        commodity_stats,
        technical_stats,
        potential,
        clients,
        sorted(reference_months),
        campaigns_by_family,
    )
    if not alerts.empty:
        alerts = score_alerts(alerts, clients)
        alerts = add_explanations(alerts)

    return {
        "sales": sales,
        "clients": clients,
        "products": products,
        "potential": potential,
        "campaigns": campaigns,
        "agg": agg,
        "historical_months": historical_months,
        "reference_months": reference_months,
        "alerts": alerts,
        "source": sales.attrs.get("source", "desconeguda"),
    }


data = build_pipeline()
alerts_df = data["alerts"]
clients_df = data["clients"]
products_df = data["products"]
potential_df = data["potential"]
agg_df = data["agg"]
historical_months = data["historical_months"]
reference_months = data["reference_months"]


with st.sidebar:
    st.title("Clinic Demand Twin")
    st.caption("Smart Demand Signals · Inibsa")
    st.divider()
    page = st.radio("Navegació", ["Overview", "Alert Ranking", "Alert Detail", "Feedback"])
    st.divider()
    st.caption(f"Font de dades: {data['source']}")
    st.caption(f"Període recent: {', '.join(sorted(reference_months)) or '-'}")
    st.caption(f"Alertes generades: {len(alerts_df)}")


def _empty_alerts_guard() -> None:
    if alerts_df.empty:
        st.warning("No s'han generat alertes amb les dades actuals.")
        st.stop()


if page == "Overview":
    st.title("Overview")
    st.write("Alertes comercials accionables per prioritzar recuperació, reposició i captura de demanda.")
    _empty_alerts_guard()

    total_alerts = len(alerts_df)
    high_alerts = int((alerts_df["urgency"] == "high").sum())
    opportunity = float(alerts_df["estimated_revenue_opportunity"].sum())
    at_risk = int(alerts_df[alerts_df["alert_type"].isin(["churn_risk", "anomalous_drop"])]["client_id"].nunique())
    capture_windows = int((alerts_df["alert_type"] == "capture_window").sum())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Alertes totals", total_alerts)
    c2.metric("High priority", high_alerts)
    c3.metric("Oportunitat estimada", f"{opportunity:,.0f} EUR")
    c4.metric("Clients en risc", at_risk)
    c5.metric("Finestres de captura", capture_windows)

    left, right = st.columns(2)
    with left:
        counts = alerts_df["alert_type"].value_counts().reset_index()
        counts.columns = ["alert_type", "alerts"]
        fig = px.bar(
            counts,
            x="alert_type",
            y="alerts",
            color="alert_type",
            color_discrete_map=ALERT_COLORS,
            labels={"alert_type": "Tipus d'alerta", "alerts": "Alertes"},
        )
        fig.update_layout(height=320, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with right:
        category_counts = alerts_df["category_type"].value_counts().reset_index()
        category_counts.columns = ["category_type", "alerts"]
        fig = px.pie(
            category_counts,
            names="category_type",
            values="alerts",
            hole=0.42,
            color="category_type",
            color_discrete_map={"commodity": "#0f766e", "technical": "#6d28d9"},
        )
        fig.update_layout(height=320)
        st.plotly_chart(fig, use_container_width=True)

    left, right = st.columns(2)
    with left:
        by_family = (
            alerts_df.groupby("family_name", as_index=False)["estimated_revenue_opportunity"]
            .sum()
            .sort_values("estimated_revenue_opportunity", ascending=True)
            .tail(10)
        )
        fig = px.bar(
            by_family,
            x="estimated_revenue_opportunity",
            y="family_name",
            orientation="h",
            labels={"estimated_revenue_opportunity": "Oportunitat EUR", "family_name": "Família"},
        )
        fig.update_layout(height=320)
        st.plotly_chart(fig, use_container_width=True)

    with right:
        urgency_counts = alerts_df["urgency"].value_counts().reindex(["high", "medium", "low"]).fillna(0)
        urgency_counts = urgency_counts.reset_index()
        urgency_counts.columns = ["urgency", "alerts"]
        fig = px.bar(
            urgency_counts,
            x="urgency",
            y="alerts",
            color="urgency",
            color_discrete_map=URGENCY_COLORS,
            labels={"urgency": "Urgència", "alerts": "Alertes"},
        )
        fig.update_layout(height=320, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)


elif page == "Alert Ranking":
    st.title("Alert Ranking")
    _empty_alerts_guard()

    feedback_map = feedback_status_map(load_feedback())
    enriched = alerts_df.merge(clients_df[["client_id", "region"]], on="client_id", how="left")

    f1, f2, f3, f4, f5 = st.columns(5)
    selected_category = f1.selectbox("Categoria", ["Totes"] + sorted(enriched["category_type"].dropna().unique()))
    selected_urgency = f2.selectbox("Urgència", ["Totes", "high", "medium", "low"])
    selected_channel = f3.selectbox("Canal", ["Tots"] + sorted(enriched["recommended_channel"].dropna().unique()))
    selected_region = f4.selectbox("Regió", ["Totes"] + sorted(enriched["region"].dropna().unique()))
    selected_type = f5.selectbox("Tipus", ["Tots"] + sorted(enriched["alert_type"].dropna().unique()))

    filtered = enriched.copy()
    if selected_category != "Totes":
        filtered = filtered[filtered["category_type"] == selected_category]
    if selected_urgency != "Totes":
        filtered = filtered[filtered["urgency"] == selected_urgency]
    if selected_channel != "Tots":
        filtered = filtered[filtered["recommended_channel"] == selected_channel]
    if selected_region != "Totes":
        filtered = filtered[filtered["region"] == selected_region]
    if selected_type != "Tots":
        filtered = filtered[filtered["alert_type"] == selected_type]

    st.caption(f"{len(filtered)} alertes amb els filtres actuals")
    visible = filtered[
        [
            "alert_id",
            "priority_score",
            "clinic_name",
            "family_name",
            "alert_type",
            "urgency",
            "estimated_revenue_opportunity",
            "recommended_channel",
            "confidence",
        ]
    ].copy()
    visible["feedback"] = visible["alert_id"].map(lambda alert_id: feedback_map.get(alert_id, "-"))
    st.dataframe(visible, use_container_width=True, height=520, hide_index=True)
    st.download_button(
        "Exportar CSV",
        filtered.to_csv(index=False).encode("utf-8"),
        "clinic_demand_alerts.csv",
        "text/csv",
    )


elif page == "Alert Detail":
    st.title("Alert Detail")
    _empty_alerts_guard()

    options = {
        f"{row.priority_score:05.1f} · {row.clinic_name} · {row.family_name} · {row.alert_type}": row.alert_id
        for row in alerts_df.itertuples()
    }
    selected = st.selectbox("Selecciona una alerta", list(options.keys()))
    alert = alerts_df[alerts_df["alert_id"] == options[selected]].iloc[0]

    st.subheader(f"{alert['clinic_name']} · {alert['family_name']}")
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Priority score", f"{alert['priority_score']}/100")
    h2.metric("Urgència", alert["urgency"])
    h3.metric("Oportunitat", f"{alert['estimated_revenue_opportunity']:,.0f} EUR")
    h4.metric("Canal", alert["recommended_channel"])

    left, right = st.columns([2, 1])
    with left:
        st.markdown("#### Explicació")
        st.info(alert["explanation"])
        st.markdown("#### Acció recomanada")
        st.success(alert["recommended_action"])
        if alert.get("campaign_context"):
            st.warning(alert.get("campaign_note", "possible efecto campaña"))

    with right:
        st.markdown("#### Senyal")
        st.metric("Expected units", f"{alert['expected_units']:,.1f}")
        st.metric("Observed units", f"{alert['observed_units']:,.1f}")
        st.metric("Potential units", f"{alert['potential_units']:,.1f}")
        st.metric("Uncaptured demand", f"{alert['uncaptured_demand']:,.1f}")
        if alert["category_type"] == "commodity":
            capture_rate = alert.get("capture_rate")
            st.metric("Capture rate", f"{capture_rate * 100:.0f}%" if pd.notna(capture_rate) else "-")
            st.metric("Classificació", alert.get("client_classification") or "-")
        else:
            st.metric("Dies sense compra", f"{int(alert.get('days_since_last_purchase') or 0)}")
            st.metric("Interval medià", f"{int(alert.get('median_interpurchase_days') or 0)} dies")

    st.markdown("#### Expected vs observed")
    client_id = alert["client_id"]
    family_id = alert["family_id"]
    monthly = agg_df[(agg_df["client_id"] == client_id) & (agg_df["family_id"] == family_id)].copy()
    all_months = sorted(historical_months | reference_months)
    monthly = pd.DataFrame({"year_month": all_months}).merge(monthly, on="year_month", how="left")
    monthly["units"] = monthly["units"].fillna(0)
    hist_avg = monthly[monthly["year_month"].isin(historical_months)]["units"].mean() if historical_months else 0

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=monthly["year_month"],
            y=monthly["units"],
            name="Observed",
            marker_color=[
                URGENCY_COLORS.get(alert["urgency"], "#dc2626") if month in reference_months else "#2563eb"
                for month in monthly["year_month"]
            ],
        )
    )
    fig.add_trace(
        go.Scatter(
            x=monthly["year_month"],
            y=[hist_avg] * len(monthly),
            mode="lines",
            name="Expected baseline",
            line={"color": "#111827", "dash": "dash"},
        )
    )
    potential_match = potential_df[
        (potential_df["client_id"] == client_id) & (potential_df["family_id"] == family_id)
    ]
    if not potential_match.empty:
        monthly_potential = float(potential_match.iloc[0]["monthly_potential_units"])
        fig.add_trace(
            go.Scatter(
                x=monthly["year_month"],
                y=[monthly_potential] * len(monthly),
                mode="lines",
                name="Monthly potential",
                line={"color": "#f59e0b", "dash": "dot"},
            )
        )
    fig.update_layout(height=360, xaxis_title="Mes", yaxis_title="Unitats", legend_orientation="h")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Feedback")
    note = st.text_input("Add note", key=f"note_{alert['alert_id']}")
    b1, b2, b3, b4 = st.columns(4)

    def persist(status: str) -> None:
        save_feedback(
            alert["alert_id"],
            alert["client_id"],
            alert["clinic_name"],
            alert["family_name"],
            alert["category_type"],
            alert["alert_type"],
            status,
            note,
        )

    if b1.button("Mark as contacted"):
        persist("contacted")
        st.success("Feedback guardat")
    if b2.button("Mark as false positive"):
        persist("false_positive")
        st.warning("Feedback guardat")
    if b3.button("Mark as recovered"):
        persist("recovered")
        st.success("Feedback guardat")
    if b4.button("Add note"):
        persist("noted")
        st.info("Nota guardada")


elif page == "Feedback":
    st.title("Feedback")
    feedback = load_feedback()
    if feedback.empty:
        st.info("Encara no hi ha feedback registrat.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Registres", len(feedback))
        c2.metric("Contacted", int((feedback["status"] == "contacted").sum()))
        c3.metric("False positive", int((feedback["status"] == "false_positive").sum()))
        c4.metric("Recovered", int((feedback["status"] == "recovered").sum()))
        st.dataframe(feedback.sort_values("timestamp", ascending=False), use_container_width=True, hide_index=True)
        st.download_button(
            "Exportar feedback",
            feedback.to_csv(index=False).encode("utf-8"),
            "feedback.csv",
            "text/csv",
        )

    st.markdown("#### Base per aprenentatge futur")
    st.write(
        "El feedback queda guardat a `storage/feedback.csv`. En una iteració següent es pot creuar amb vendes "
        "posteriors per mesurar recuperació, ajustar llindars i reduir falsos positius per família, segment i canal."
    )
